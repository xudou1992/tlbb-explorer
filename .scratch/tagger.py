"""Rule-based asset tagging layer over the TLBB reverse-engineered asset DB.

Every tag emitted here is the result of one named, auditable rule that reads only
four kinds of evidence recorded in resources.db:

  (a) dir / hub_path        - the folder names chosen by the asset packager
  (b) member roles          - agroups.n_* and the member resources' paths/types
  (c) referenced names      - agroup_names.name and props.refs of the hub resource
  (d) shader class          - props.shader of the hub resource (JBCF)

Nothing is inferred from "what the asset probably looks like": lexicons that are not
readable from the database itself are declared in LEXICON_* below and are always
emitted with confidence='medium' so a human can audit them first.

Importing this module has no side effects; run it as __main__ to emit the TSV report.
"""

from __future__ import annotations

import collections
import json
import os
import re
import sqlite3
from dataclasses import dataclass, field
from typing import Callable, Iterable

# --------------------------------------------------------------------------- paths

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "resources.db")
OUT_DIR = os.path.join(HERE, "out")
TAGS_TSV = os.path.join(OUT_DIR, "tags.tsv")
REPORT_TXT = os.path.join(OUT_DIR, "tags_report.txt")

# ------------------------------------------------------------------ vocabulary

TAG_VOCAB = (
    "boss", "npc", "monster", "pet",
    "player-male", "player-female", "player-part",
    "weapon", "mount", "accessory",
    "effect", "skill-effect", "scene-effect",
    "building", "tileset", "map-props",
    "item-icon", "ui", "mask", "texture-atlas",
    "shared-material", "animation-set", "audio", "table/config", "unknown",
)

# --- LEXICON_NPC_CLASS ----------------------------------------------------------
# Category token that the packager writes into the asset folder name under
# data/source/npc/quest/.  This is the one place a pinyin gloss is asserted rather
# than read out of the schema, so assert_lexicons() below re-counts the quest folders
# on every run and refuses to produce output if these keys stop covering >=97% of
# them - a rename or a new category then fails loudly instead of silently tagging
# nothing.  The report prints every folder token it met.
LEXICON_NPC_CLASS = {
    "boss": ("boss", "npc"),
    "monster": ("monster", "npc"),
    "pets": ("pet", "npc"),
    "npc": ("npc",),
    "new": ("npc",),          # w1351_new_npc_* / w1351_new_<person name>
    "zuoqi": ("mount", "npc"),
    "shenghuo": ("npc",),     # 生活 life-skill / gathering NPCs
    "wuhun": ("accessory",),
    "chibang": ("accessory",),
    "wuqi": ("weapon",),
    "ui": ("ui",),
    "caiji": ("map-props",),
    "drop": ("map-props",),
}

# --- LEXICON_NPC_DIR ------------------------------------------------------------
# Second path segment under data/source/npc/.  These are pinyin words written by
# the art team; the gloss is recorded in the report so a human can reject one.
LEXICON_NPC_DIR = {
    "wuqi": ("weapon",),               # 武器  weapon
    "toukui": ("accessory",),          # 头盔  helmet
    "guajian": ("accessory",),         # 挂件  pendant / attachable
    "chibang": ("accessory",),         # 翅膀  wings
    "changjingdaoju": ("map-props",),  # 场景道具  scene prop
    "dynamic": ("map-props",),         # animated scene prop
    "model": ("effect",),              # w1351_model_* VFX prop models
}

# --- LEXICON_BUILDING -----------------------------------------------------------
# Only applied to map-module assets (mobile_maps*), never to a character tree.
# 'fw' is a stem field the packager uses systematically inside map props
# (w1351_smeh_fwyuanding_001, w1351_ly__fwshuangcenglou_001 = two-storey house), and
# it never occurs in an npc/monster/pets name.  This is an asserted pinyin gloss, not
# a schema fact, so R1j is capped at medium and spot-check by filtering tags.tsv for
# rule R1j (the report lists 10 example gids for it).
LEXICON_BUILDING = ("fw", "fangwu")

# --- LEXICON_COMBAT -------------------------------------------------------------
# Applied only to already-effect-classified assets, matched against stem +
# props.refs, to separate skill VFX from ambient/scene VFX.
LEXICON_COMBAT = ("skill", "buff", "behit", "vertigo", "attack", "hit", "hurt")

# ------------------------------------------------------------------ helpers

_TOKEN_RE = re.compile(r"^w1351_([a-z][a-z0-9]+)")
_W1351_ANY_RE = re.compile(r"^w\d{4}_([a-z][a-z0-9]+)")


def stem_token(text: str) -> str | None:
    """First category token of a w1351_<token>_... style name."""
    if not text:
        return None
    m = _TOKEN_RE.match(text) or _W1351_ANY_RE.match(text)
    return m.group(1) if m else None


def fields(text: str) -> list[str]:
    return [f for f in (text or "").split("_") if f]


def evidence(s: str, limit: int = 90) -> str:
    """Rule columns must stay single-line, tab-free and short."""
    s = re.sub(r"\s+", " ", str(s)).strip()
    return s[:limit]


def _loads(props: str | None) -> dict:
    if not props:
        return {}
    try:
        v = json.loads(props)
    except (ValueError, TypeError):
        return {}
    return v if isinstance(v, dict) else {}


# ---------------------------------------------------------------------- context


@dataclass
class Asset:
    gid: int
    hub: str
    hub_path: str
    dir: str
    stem: str
    kind: str
    n: int
    n_mesh: int
    n_mtl: int
    n_ani: int
    n_ske: int
    n_tex: int
    n_other: int
    names: list = field(default_factory=list)      # agroup_names.name
    member_paths: list = field(default_factory=list)
    member_anis: list = field(default_factory=list)  # action suffix per .ani member
    shader: str | None = None
    props_refs: list = field(default_factory=list)
    hub_ext: str = ""
    fan_in: int = 0          # distinct assets that reference this group's members

    # --- derived, cheap, cached -------------------------------------------
    @property
    def folder(self) -> str:
        """The asset's own folder name, when hub_path is inside one."""
        if not self.hub_path:
            return ""
        parts = self.hub_path.split("/")
        return parts[-2] if len(parts) >= 2 else ""

    @property
    def search_text(self) -> str:
        return " ".join((self.stem, self.folder, self.hub_path, self.dir)).lower()

    @property
    def wide_text(self) -> str:
        """stem + folder + every referenced name."""
        return " ".join((self.search_text, *self.names, *self.props_refs)).lower()


@dataclass
class Hit:
    tag: str
    rule: str
    confidence: str


# ------------------------------------------------------------------- corpus load


def open_db(path: str = DB_PATH) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{path.replace(os.sep, '/')}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def has_table(con: sqlite3.Connection, name: str) -> bool:
    row = con.execute("select 1 from sqlite_master where type='table' and name=?",
                      (name,)).fetchone()
    return row is not None


TEX_EXTS = (".tga", ".png", ".dds", ".webp", ".jpeg", ".jpg")


def shared_texture_census(con: sqlite3.Connection, min_refs: int = 20) -> dict[str, int]:
    """{texture filename: how many distinct assets reference it}.

    Keyed by the FULL filename including extension: keying on the stem alone makes
    `foo.mtl` collide with `foo.tga` and invents atlases out of plain materials.

    Read from whichever name-census table the current build of resources.db
    provides: `texnames` (all names) or, when the rebuild has not created it yet,
    `dangling` (names with no hash in the install).  Both carry n_refs.
    """
    for tbl in ("texnames", "dangling"):
        if not has_table(con, tbl):
            continue
        out = {}
        for row in con.execute(
                f"select name, n_refs from {tbl} "
                f"where n_refs>=? and ext in ({','.join('?' * len(TEX_EXTS))})",
                (min_refs, *TEX_EXTS)):
            out[row["name"]] = row["n_refs"]
        if out:
            return out
    return {}


def action_lexicon(con: sqlite3.Connection, min_count: int = 50) -> dict[str, str]:
    """Derive the animation 'action' vocabulary from the .ani file names themselves.

    Returns {action_class: last_underscore_field}.  A field qualifies when it
    occurs on at least `min_count` .ani resources, so the vocabulary is read out of
    the install, not written by hand.
    """
    cnt: collections.Counter = collections.Counter()
    for row in con.execute("select path from resources where ext='.ani' and path<>''"):
        base = row["path"].rsplit("/", 1)[-1][:-4]
        tail = base.split("_")[-1]
        cnt[tail] += 1
    lex: dict[str, str] = {}
    for tail, c in cnt.items():
        if c < min_count:
            continue
        cls = re.sub(r"\d+$", "", tail)
        lex[tail] = cls or tail
    return lex


def part_tokens(con: sqlite3.Connection, min_count: int = 12) -> set[str]:
    """Body-part words the packager actually uses inside data/source/player.

    Derived, and position-sensitive: in this naming scheme the slot marker is a
    bare `s` (body) or `t` (head) field and the word that *follows* it is the slot
    (w1351_nan_s_yifu_mjrmdz -> yifu).  Counting only that position is what keeps
    cosmetic variant names out of the set - a plain field census would also return
    `chushi` (a chef hairstyle, w1351_nan_t_toufa_chushi_030) and one-off names like
    s_yuyuqinchou, none of which is a body slot.
    """
    cnt: collections.Counter = collections.Counter()
    for row in con.execute(
        "select stem from agroups where dir like 'data/source/player%'"
    ):
        fs = fields(row["stem"])
        for i, f in enumerate(fs):
            if f in ("s", "t") and i + 1 < len(fs) and fs[i + 1].isalpha():
                cnt[fs[i + 1]] += 1
                break
    return {f for f, c in cnt.items() if c >= min_count}


def area_codes(con: sqlite3.Connection | None = None, share: float = 0.9) -> set[str]:
    """Tokens that occur (almost) exclusively inside mobile_maps_source.

    Those are map-module codes (ly / dl / sz / ...).  Derived, not guessed: a token
    is accepted only when >=`share` of the named groups carrying it are map props.
    """
    own = con is None
    con = con or open_db()
    try:
        per_tok: collections.defaultdict = collections.defaultdict(collections.Counter)
        for row in con.execute("select stem, dir from agroups where dir<>''"):
            t = stem_token(row["stem"])
            if not t:
                continue
            per_tok[t]["map" if row["dir"].startswith("mobile_maps") else "other"] += 1
        out = set()
        for t, c in per_tok.items():
            tot = sum(c.values())
            if tot >= 15 and c["map"] / tot >= share:
                out.add(t)
        return out
    finally:
        if own:
            con.close()


def load_assets(con: sqlite3.Connection, lex: dict[str, str]) -> dict[int, Asset]:
    assets: dict[int, Asset] = {}
    for row in con.execute("select * from agroups"):
        a = Asset(
            gid=row["id"], hub=row["hub"], hub_path=row["hub_path"] or "",
            dir=row["dir"] or "", stem=row["stem"] or "", kind=row["kind"] or "",
            n=row["n"] or 0, n_mesh=row["n_mesh"] or 0, n_mtl=row["n_mtl"] or 0,
            n_ani=row["n_ani"] or 0, n_ske=row["n_ske"] or 0, n_tex=row["n_tex"] or 0,
            n_other=row["n_other"] or 0,
        )
        assets[a.gid] = a

    for row in con.execute("select gid, name, cls from agroup_names"):
        a = assets.get(row["gid"])
        if a is not None:
            a.names.append(row["name"])

    paths = {
        row["hash"]: (row["path"] or "", row["ext"] or "")
        for row in con.execute("select hash, path, ext from resources")
    }
    hub_hashes = {a.hub for a in assets.values()}
    hub_props: dict[str, str] = {}
    for row in con.execute("select hash, props from resources where props is not null"):
        if row["hash"] in hub_hashes:
            hub_props[row["hash"]] = row["props"]
    for row in con.execute("select gid, hash, role from amembers"):
        a = assets.get(row["gid"])
        if a is None:
            continue
        p, _ext = paths.get(row["hash"], ("", ""))
        if p:
            a.member_paths.append(p)
            if p.endswith(".ani"):
                base = p.rsplit("/", 1)[-1][:-4].split("_")[-1]
                if base in lex:
                    a.member_anis.append(lex[base])

    for gid, a in assets.items():
        p, _ = paths.get(a.hub, ("", ""))
        a.hub_ext = p[p.rfind("."):] if p and "." in p else ""
        d = _loads(hub_props.get(a.hub))
        a.shader = d.get("shader")
        refs = d.get("refs")
        if isinstance(refs, list):
            a.props_refs = [x for x in refs if isinstance(x, str)]

    # inbound fan-in: how many distinct resources reference this group's members.
    hash2gid: dict[str, set] = {}
    for row in con.execute("select gid, hash from amembers"):
        hash2gid.setdefault(row["hash"], set()).add(row["gid"])
    fans: dict[int, set] = {}
    for row in con.execute("select from_hash, to_hash from refs where to_hash is not null"):
        for gid in hash2gid.get(row["to_hash"], ()):
            if row["from_hash"] != assets[gid].hub:
                fans.setdefault(gid, set()).add(row["from_hash"])
    for gid, s in fans.items():
        assets[gid].fan_in = len(s)
    return assets


# ------------------------------------------------------------------ the rules
#
# A rule is (rule_id, accepts(Asset)->bool, tags(Asset)->[(tag, confidence)]).
# The emitted `rule` column is "<rule_id>:<matched evidence>", so any row in
# out/tags.tsv can be traced back to the exact string that caused it.

Rules = list[tuple[str, Callable[[Asset], "str | None"],
                   Callable[[Asset, str], Iterable[Hit]]]]


def _h(tag: str, rule: str, ev: str, conf: str = "high") -> Hit:
    return Hit(tag, evidence(f"{rule}:{ev}", 200), conf)


# --- (a) dir / hub_path -----------------------------------------------------

def r_npc_class(a: Asset) -> str | None:
    if not a.dir.startswith("data/source/npc/quest/"):
        return None
    blob = (a.folder + " " + a.stem).lower()
    for tok, _tags in LEXICON_NPC_CLASS.items():
        if re.search(rf"(^|_)({tok})(_|$)", blob):
            return tok
    return None


def tags_npc_class(a: Asset, tok: str) -> Iterable[Hit]:
    for tag in LEXICON_NPC_CLASS[tok]:
        yield _h(tag, "R1a:npc-quest-folder-token", f"token={tok} in {a.folder or a.stem}")


def r_npc_tree(a: Asset) -> str | None:
    """Fallback for the ~100 quest assets whose folder carries no recognised
    category token (e.g. w1351_denglong01, chuansong001).  The packager put them in
    the npc/quest tree, so the only honest tag available is npc, at medium
    confidence, with the folder recorded as the evidence."""
    if not a.dir.startswith("data/source/npc/quest/"):
        return None
    if r_npc_class(a):
        return None
    return a.folder or a.stem


def tags_npc_tree(a: Asset, ev: str) -> Iterable[Hit]:
    yield _h("npc", "R1a2:npc-quest-tree-fallback", ev, "medium")


def r_npc_subdir(a: Asset) -> str | None:
    m = re.match(r"^data/source/npc/([a-z]+)(?:/|$)", a.dir)
    return m.group(1) if m and m.group(1) in LEXICON_NPC_DIR else None


def tags_npc_subdir(a: Asset, sub: str) -> Iterable[Hit]:
    for tag in LEXICON_NPC_DIR[sub]:
        yield _h(tag, "R1b:npc-subdir", f"dir=data/source/npc/{sub}")


# Trees where nan/nv genuinely denotes the player body (as opposed to an NPC or an
# effect-prop variant named after the body it is attached to).
PLAYER_TREES = ("data/source/player/", "data/source/npc/toukui",
                "data/source/npc/guajian", "data/source/npc/chibang", "ui/")


def in_player_tree(a: Asset) -> bool:
    return a.dir.startswith(PLAYER_TREES) or a.hub_path.startswith(PLAYER_TREES)


def r_gender(a: Asset) -> str | None:
    if not in_player_tree(a):
        return None
    m = re.search(r"(^|_)(nan|nv)(_|$)", a.dir + "/" + a.hub_path + "/" + a.stem)
    return m.group(2) if m else None


def tags_gender(a: Asset, g: str) -> Iterable[Hit]:
    tag = "player-male" if g == "nan" else "player-female"
    src = "dir" if g in a.dir else "stem"
    conf = "high" if a.dir.startswith("data/source/player/") else "medium"
    yield _h(tag, "R1c:gender-token", f"{g}({src})", conf)


def make_r_part(parts: set[str]):
    """player-part = the asset is one clothing/hair/face/glove/shoe slot of the
    player paper-doll, i.e. a body-part token appears in its own name.

    Gated to the player trees on purpose: a boss also ships yifu/lian/shoutao
    meshes, but that makes it a part-based character model, not player equipment.
    """
    def r(a: Asset) -> str | None:
        if not parts or not in_player_tree(a):
            return None
        names = [a.hub_path.rsplit("/", 1)[-1]] if a.hub_path else []
        names += [p.rsplit("/", 1)[-1] for p in a.member_paths]
        for nm in names:
            hit = [f for f in fields(nm.rsplit(".", 1)[0]) if f in parts]
            if hit:
                return f"{hit[0]}<-{nm}"
        return None

    def tags(a: Asset, ev: str) -> Iterable[Hit]:
        yield _h("player-part", "R1d:body-part-token", ev, "high")

    return r, tags


def r_effect_dir(a: Asset) -> str | None:
    if not a.dir.startswith("data/effect/"):
        return None
    return a.dir.split("/")[2] if len(a.dir.split("/")) > 2 else ""


def tags_effect_dir(a: Asset, fam: str) -> Iterable[Hit]:
    yield _h("effect", "R1e:effect-texture-family", f"family={fam or 'root'}")


def r_map_prop(a: Asset) -> str | None:
    return "mobile_maps_source" if a.dir.startswith("mobile_maps_source") else None


def tags_map_prop(a: Asset, ev: str) -> Iterable[Hit]:
    yield _h("map-props", "R1f:map-prop-tree", ev)


def r_tileset(a: Asset) -> str | None:
    if not a.dir.startswith("mobile_maps/"):
        return None
    return a.hub_ext or "sfl"


def tags_tileset(a: Asset, ev: str) -> Iterable[Hit]:
    yield _h("tileset", "R1g:map-scene-file", f"dir={a.dir.split('/')[1]} ext={ev}")


def r_ui(a: Asset) -> str | None:
    return a.dir if a.dir.startswith("ui/") else None


def tags_ui(a: Asset, ev: str) -> Iterable[Hit]:
    yield _h("ui", "R1h:ui-tree", ev)
    if "/icon/" in ev:
        yield _h("item-icon", "R1h:ui-tree", "icon subdir " + ev)


def r_shared_material(a: Asset) -> str | None:
    if a.dir.startswith("data/sharematerial"):
        return a.dir
    if a.stem.lower().startswith("template"):
        return "stem=" + a.stem
    return None


def tags_shared_material(a: Asset, ev: str) -> Iterable[Hit]:
    yield _h("shared-material", "R1i:sharematerial", ev)


def r_building(a: Asset) -> str | None:
    if not a.dir.startswith(("mobile_maps_source", "mobile_maps/")):
        return None
    fs = fields(a.stem.lower())
    for f in fs[2:]:
        for w in LEXICON_BUILDING:
            if f.startswith(w) and len(f) > len(w):
                return f"{w} in {a.stem}"
    return None


def tags_building(a: Asset, ev: str) -> Iterable[Hit]:
    yield _h("building", "R1j:building-lexicon", ev, "medium")


# --- (b) member roles ------------------------------------------------------

def r_animation_set(a: Asset) -> str | None:
    if len(a.member_anis) < 4:
        return None
    cls = set(a.member_anis)
    if len(cls) < 3:
        return None
    return f"{len(a.member_anis)} ani / {len(cls)} actions {{{','.join(sorted(cls))}}}"


def tags_animation_set(a: Asset, ev: str) -> Iterable[Hit]:
    yield _h("animation-set", "R2a:action-set-completeness", ev)


def r_mask_only(a: Asset) -> str | None:
    if re.match(r"^w1351_mask_", a.stem):
        return "stem=" + a.stem
    return None


def tags_mask(a: Asset, ev: str) -> Iterable[Hit]:
    yield _h("mask", "R2b:mask-name", ev)


# --- (c) referenced names --------------------------------------------------

def r_grid_tiles(a: Asset) -> str | None:
    """A map scene file whose members are literally x_z_y grid chunks."""
    grid = [p.rsplit("/", 1)[-1] for p in a.member_paths
            if re.match(r"^\d+_\d+_-?\d+\.scene$", p.rsplit("/", 1)[-1])]
    if len(grid) >= 4:
        return f"{len(grid)} grid chunks e.g. {grid[0]}"
    return None


def tags_grid_tiles(a: Asset, ev: str) -> Iterable[Hit]:
    yield _h("tileset", "R2g:scene-grid-chunks", ev)


def r_shared_by_fanin(a: Asset) -> str | None:
    """A material that the install genuinely re-uses: >=20 distinct assets
    reference this group's members.  Quantitative, not name based."""
    if a.hub_ext == ".mtl" and a.fan_in >= 20:
        return f"{a.fan_in} referencing assets"
    return None


def tags_shared_by_fanin(a: Asset, ev: str) -> Iterable[Hit]:
    yield _h("shared-material", "R2f:inbound-fan-in", ev)


def make_r_area(area: set[str]):
    def r(a: Asset) -> str | None:
        if not a.dir.startswith(("data/effect/", "data/source/npc/model/")):
            return None
        for nm in list(a.names) + list(a.props_refs):
            t = stem_token(nm.rsplit(".", 1)[0])
            if t and t in area:
                return f"area-code {t} in ref {nm}"
        return None

    def tags(a: Asset, ev: str) -> Iterable[Hit]:
        yield _h("scene-effect", "R3a:effect-carries-map-module-code", ev, "medium")

    return r, tags


def make_r_token_map(token_map: dict[str, tuple[str, ...]]):
    """Recover unnamed groups (dir='') from the names their payload references."""
    def r(a: Asset) -> str | None:
        if a.hub_path:
            return None
        for nm in list(a.props_refs) + list(a.names):
            t = stem_token(nm.rsplit(".", 1)[0])
            if t and t in token_map:
                return f"{t}<-{nm}"
        return None

    def tags(a: Asset, ev: str) -> Iterable[Hit]:
        tok = ev.split("<-")[0]
        for tag in token_map[tok]:
            yield _h(tag, "R3b:learned-token-from-references", ev, "medium")

    return r, tags


def make_r_combat():
    def r(a: Asset) -> str | None:
        if not a.dir.startswith(("data/effect/", "data/source/npc/model/")):
            return None
        blob = a.wide_text
        for w in LEXICON_COMBAT:
            if re.search(rf"(^|_){w}", blob):
                return f"marker={w} stem={a.stem}"
        return None

    def tags(a: Asset, ev: str) -> Iterable[Hit]:
        yield _h("skill-effect", "R3c:combat-marker-in-names", ev, "medium")

    return r, tags


def r_audio_member(a: Asset) -> str | None:
    for p in a.member_paths:
        if p.endswith((".wav", ".ogg", ".mp3")):
            return p
    return None


def tags_audio(a: Asset, ev: str) -> Iterable[Hit]:
    yield _h("audio", "R2d:audio-member", ev)


def r_table_member(a: Asset) -> str | None:
    for p in a.member_paths:
        if p.endswith((".tab", ".tbl", ".ini", ".xml", ".lua", ".txt")):
            return p
    return None


def tags_table(a: Asset, ev: str) -> Iterable[Hit]:
    yield _h("table/config", "R2e:table-member", ev)


# --- (d) shader class ------------------------------------------------------

def r_sfx_shader(a: Asset) -> str | None:
    return a.shader if a.shader == "NewSfxShader" else None


def tags_sfx_shader(a: Asset, ev: str) -> Iterable[Hit]:
    yield _h("effect", "R4a:shader=NewSfxShader", ev)


def r_dyn_model(a: Asset) -> str | None:
    # DynModelShader is used by 6,837 resources spanning npc, player and map props,
    # so it identifies the renderer, not the asset class.  Kept as a no-op rule so
    # the audit trail shows it was consulted and deliberately produced nothing.
    return a.shader if a.shader == "DynModelShader" else None


def tags_dyn_model(a: Asset, ev: str) -> Iterable[Hit]:
    return ()


# ------------------------------------------------------------------ pipeline


@dataclass
class Diagnostics:
    """Everything the rule set derived from the corpus rather than from a literal."""
    token_map: dict = field(default_factory=dict)        # token -> accepted tags
    ambiguous: dict = field(default_factory=dict)        # token -> split tag votes
    atlas: dict = field(default_factory=dict)            # texture -> inbound refs
    action_lex: dict = field(default_factory=dict)
    parts: set = field(default_factory=set)
    area: set = field(default_factory=set)


def build_rules(assets: dict[int, Asset], area: set[str], parts: set[str],
                con: sqlite3.Connection) -> tuple[Rules, Diagnostics]:
    """Instantiate every rule, including the ones needing a corpus-wide census.

    Returns (rules, diagnostics).
    """
    # --- learned token -> tags -----------------------------------------------
    # Reuse the dir-based rules as the single source of truth: run every R1* rule
    # over the groups that DO have a path and record which tags each w1351_<token>
    # produces.  Nothing is hand-mapped here, so R3b can only ever emit tags the
    # packager's own directory layout already justified elsewhere.
    rp, tp = make_r_part(parts)
    dir_rules: Rules = [
        ("R1a", r_npc_class, tags_npc_class),
        ("R1b", r_npc_subdir, tags_npc_subdir),
        ("R1c", r_gender, tags_gender),
        ("R1d", rp, tp),
        ("R1e", r_effect_dir, tags_effect_dir),
        ("R1f", r_map_prop, tags_map_prop),
        ("R1g", r_tileset, tags_tileset),
        ("R1h", r_ui, tags_ui),
        ("R1i", r_shared_material, tags_shared_material),
    ]
    tok_tags: collections.defaultdict = collections.defaultdict(collections.Counter)
    tok_total: collections.Counter = collections.Counter()
    for a in assets.values():
        if not a.hub_path:
            continue
        t = stem_token(a.stem) or stem_token(a.folder)
        if not t:
            continue
        tags = set()
        for _rid, accepts, mk in dir_rules:
            ev = accepts(a)
            if ev:
                tags |= {h.tag for h in mk(a, ev)}
        if not tags:
            continue
        tok_total[t] += 1
        for tag in tags:
            tok_tags[t][tag] += 1

    # A token is accepted only when >=20 named groups carry it AND >=85% of those
    # groups agree on each tag we keep (support measured per tag, over group count).
    token_map: dict[str, tuple[str, ...]] = {}
    ambiguous: dict[str, dict[str, int]] = {}
    for t, total in tok_total.items():
        if total < 20:
            continue
        keep = tuple(sorted(tag for tag, k in tok_tags[t].items() if k / total >= 0.85))
        if keep:
            token_map[t] = keep
        else:
            # seen often enough but the layout disagrees, e.g. 'll' lives both in
            # mobile_maps_source (props) and mobile_maps (scene files)
            ambiguous[t] = dict(tok_tags[t])

    # texture atlas candidates: texture names the install reuses across >=20 assets
    atlas: dict[str, int] = shared_texture_census(con)

    def r_atlas(a: Asset) -> str | None:
        """True only when the group itself OWNS the reused sheet - one of its
        members is that texture file.  Materials that merely *sample* it, and
        same-stem .mtl files, are not atlases."""
        own = {p.rsplit("/", 1)[-1] for p in a.member_paths
               if p.lower().endswith(TEX_EXTS)}
        if a.hub_path.lower().endswith(TEX_EXTS):
            own.add(a.hub_path.rsplit("/", 1)[-1])
        for nm in sorted(own & set(atlas)):
            return f"{nm} sampled by {atlas[nm]} assets"
        return None

    def tags_atlas(a: Asset, ev: str) -> Iterable[Hit]:
        return [_h("texture-atlas", "R2c:owned-shared-texture-sheet", ev, "medium")]

    rules: list = [
        ("R1a", r_npc_class, tags_npc_class),
        ("R1a2", r_npc_tree, tags_npc_tree),
        ("R1b", r_npc_subdir, tags_npc_subdir),
        ("R1c", r_gender, tags_gender),
        ("R1d", rp, tp),
        ("R1e", r_effect_dir, tags_effect_dir),
        ("R1f", r_map_prop, tags_map_prop),
        ("R1g", r_tileset, tags_tileset),
        ("R1h", r_ui, tags_ui),
        ("R1i", r_shared_material, tags_shared_material),
        ("R1j", r_building, tags_building),
        ("R2a", r_animation_set, tags_animation_set),
        ("R2b", r_mask_only, tags_mask),
        ("R2c", r_atlas, tags_atlas),
        ("R2f", r_shared_by_fanin, tags_shared_by_fanin),
        ("R2g", r_grid_tiles, tags_grid_tiles),
        ("R2d", r_audio_member, tags_audio),
        ("R2e", r_table_member, tags_table),
        ("R3a", *make_r_area(area)),
        ("R3b", *make_r_token_map(token_map)),
        ("R3c", *make_r_combat()),
        ("R4a", r_sfx_shader, tags_sfx_shader),
        ("R4b", r_dyn_model, tags_dyn_model),
    ]
    diag = Diagnostics(token_map=token_map, ambiguous=ambiguous, atlas=atlas,
                       parts=parts, area=area)
    return rules, diag


def tag_all(assets: dict[int, Asset], rules: list) -> dict[int, list[Hit]]:
    out: dict[int, list[Hit]] = {}
    for gid, a in assets.items():
        hits: list[Hit] = []
        seen: set[tuple[str, str]] = set()
        for rid, accepts, tags in rules:
            try:
                ev = accepts(a)
            except Exception as exc:                      # a broken rule must be loud
                raise RuntimeError(f"rule {rid} failed on gid {gid}") from exc
            if not ev:
                continue
            for h in tags(a, ev):
                key = (h.tag, h.rule)
                if key not in seen:
                    seen.add(key)
                    hits.append(h)
        if not hits:
            ev = (f"dir={a.dir or '(unnamed)'} stem={a.stem or '(none)'} "
                  f"names={len(a.names)} shader={a.shader}")
            hits.append(Hit("unknown",
                            evidence(f"R0:no-rule-matched:{ev}"), "high"))
        out[gid] = hits
    return out


def tag_database(db_path: str = DB_PATH
                 ) -> tuple[dict[int, Asset], dict[int, list[Hit]], Diagnostics]:
    con = open_db(db_path)
    try:
        assert_lexicons(con)          # refuse to tag if the folder vocabulary moved
        lex = action_lexicon(con)
        parts = part_tokens(con)
        area = area_codes(con)
        assets = load_assets(con, lex)
        rules, diag = build_rules(assets, area, parts, con)
        diag.action_lex = lex
        hits = tag_all(assets, rules)
        return assets, hits, diag
    finally:
        con.close()


# ------------------------------------------------------------------- outputs


def merge_hits(hits: dict[int, list[Hit]]) -> list[tuple[int, str, str, str]]:
    """Collapse to exactly one row per (gid, tag).

    When several independent rules prove the same tag (e.g. an effect material that
    sits in data/effect/textures/fire AND declares NewSfxShader) every rule is kept,
    joined by ';', so the audit trail is not lost, and the highest confidence wins.
    """
    rank = {"high": 0, "medium": 1}
    rows: list[tuple[int, str, str, str]] = []
    for gid, hs in hits.items():
        grouped: collections.OrderedDict = collections.OrderedDict()
        for h in hs:
            grouped.setdefault(h.tag, []).append(h)
        for tag, group in grouped.items():
            rules = ";".join(dict.fromkeys(g.rule for g in group))
            conf = min((g.confidence for g in group), key=rank.__getitem__)
            rows.append((gid, tag, evidence(rules, 260), conf))
    rows.sort(key=lambda r: (r[0], r[1]))
    return rows


def write_tsv(hits: dict[int, list[Hit]], path: str = TAGS_TSV) -> int:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    rows = merge_hits(hits)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("gid\ttag\trule\tconfidence\n")
        for r in rows:
            f.write("\t".join(str(x) for x in r) + "\n")
    return len(rows)


def write_report(assets: dict[int, Asset], hits: dict[int, list[Hit]],
                 diag: Diagnostics, path: str = REPORT_TXT) -> str:
    total = len(assets)
    # Count from the merged rows so the report can never disagree with tags.tsv.
    rows = merge_hits(hits)
    merged_rule = {(g, t): r for g, t, r, _c in rows}
    per_tag: collections.Counter = collections.Counter()
    per_tag_gid: collections.defaultdict = collections.defaultdict(list)
    per_rule: collections.Counter = collections.Counter()
    conf: collections.defaultdict = collections.defaultdict(collections.Counter)
    for gid, tag, rule, rconf in rows:
        per_tag[tag] += 1
        per_tag_gid[tag].append(gid)
        conf[tag][rconf] += 1
        for rid in rule.split(";"):
            per_rule[rid.split(":")[0]] += 1

    tags_per_gid: collections.Counter = collections.Counter()
    for _gid, tag, _rule, _c in rows:
        if tag != "unknown":
            tags_per_gid[_gid] += 1
    cnt_tags = collections.Counter(tags_per_gid.get(gid, 0) for gid in assets)
    unknown = cnt_tags.get(0, 0)
    named = total - unknown

    L: list[str] = []
    w = L.append
    w("TLBB asset tagger - coverage report")
    w("db: resources.db (read-only)   assets(agroups): %d" % total)
    w("")
    w("== overall coverage ==")
    w("  tagged (>=1 non-unknown tag): %d  (%.1f%%)" % (named, 100.0 * named / total))
    w("  unknown                     : %d  (%.1f%%)" % (unknown, 100.0 * unknown / total))
    w("  exactly 1 tag : %d" % cnt_tags.get(1, 0))
    w("  2 or more tags: %d" % sum(v for k, v in cnt_tags.items() if k >= 2))
    w("  total (gid,tag) rows: %d" % sum(per_tag.values()))
    w("")
    w("== coverage per tag ==")
    w("  %-16s %6s %7s   %s" % ("tag", "assets", "%oftotal", "high/medium"))
    for tag in TAG_VOCAB:
        c = per_tag.get(tag, 0)
        w("  %-16s %6d %6.1f%%   %d/%d" % (tag, c, 100.0 * c / total,
                                           conf[tag]["high"], conf[tag]["medium"]))
    w("")
    w("== rule firings ==")
    for rid, c in per_rule.most_common():
        w("  %-42s %6d" % (rid, c))
    w("")
    w("== 10 example gids per tag (spot-check) ==")
    for tag in TAG_VOCAB:
        gids = sorted(per_tag_gid.get(tag, []))
        if not gids:
            w("  [%s] 0 hits" % tag)
            continue
        w("  [%s] %d hits" % (tag, len(gids)))
        for gid in gids[:10]:
            a = assets[gid]
            r = merged_rule.get((gid, tag), "")
            w("     gid=%-5d %-58s %s" % (gid, evidence(a.hub_path or "(unnamed)", 58), r))
        w("")
    w("== unknown assets, listed in full ==")
    unk = sorted(gid for gid, hs in hits.items() if hs[0].tag == "unknown")
    tok_re_used = collections.Counter()
    for gid in unk:
        a = assets[gid]
        pool = a.props_refs + a.names
        toks = {stem_token(n.rsplit(".", 1)[0]) for n in pool}
        toks.discard(None)
        if not toks:
            tok_re_used["no w1351_ name anywhere in (a)-(d)"] += 1
        elif any(t in diag.ambiguous for t in toks):
            tok_re_used["only token is ambiguous (see below)"] += 1
        else:
            tok_re_used["token seen <20 times in named groups"] += 1
    w("  %d assets.  Reason breakdown:" % len(unk))
    for k, v in tok_re_used.most_common():
        w("    %4d  %s" % (v, k))
    w("  Ambiguous tokens deliberately rejected by R3b:")
    for t in sorted(diag.ambiguous):
        w("    %-10s votes=%s" % (t, diag.ambiguous[t]))
    w("  Each unknown asset, with the evidence it had:")
    for gid in unk:
        a = assets[gid]
        pool = (a.props_refs + a.names)[:4]
        w("   gid=%-5d shader=%-15s refs=%s" % (gid, a.shader, evidence(", ".join(pool), 110)))
    w("")
    w("== lexicons the rules depend on ==")
    w("  NPC quest folder tokens : %s" % ", ".join(sorted(LEXICON_NPC_CLASS)))
    w("  NPC subdirs             : %s" % ", ".join(sorted(LEXICON_NPC_DIR)))
    w("  building words          : %s  (medium confidence only)" % ", ".join(LEXICON_BUILDING))
    w("  combat markers          : %s  (medium confidence only)" % ", ".join(LEXICON_COMBAT))
    w("  DERIVED body-part words (R1d, from data/source/player stems >=12x): %s"
      % ", ".join(sorted(diag.parts)))
    w("  DERIVED map-module codes (R3a, >=90%% inside mobile_maps*): %d of them"
      % len(diag.area))
    w("     %s" % evidence(", ".join(sorted(diag.area)), 200))
    w("  DERIVED animation actions (R2a, from .ani names >=50x): %d"
      % len(diag.action_lex))
    w("     %s" % evidence(", ".join(sorted(diag.action_lex)), 200))
    w("  learned token -> tags   : %d tokens" % len(diag.token_map))
    for t in sorted(diag.token_map):
        w("     %-12s -> %s" % (t, ",".join(diag.token_map[t])))
    w("")
    w("== rules that produced nothing (and why) ==")
    dead = [t for t in TAG_VOCAB if per_tag.get(t, 0) == 0]
    for tag in dead:
        w("  %s" % tag)
    if not dead:
        w("  (none)")
    w("")
    w("  Structural notes, verified against the DB:")
    w("   - audio: 0 of the 38,781 amembers rows join to a resources row of type")
    w("     wav/ogg/mp3, even though resources holds 218 wav + 168 ogg + 39 mp3.")
    w("     Audio was never grouped into an asset, so no rule can tag it.")
    w("   - table/config: exactly 1 amembers row joins to type='table', and it is")
    w("     gid 2321 member 60690e02ab947f3d = .../w1351_fb_cuju_001/1_1_-3.scene,")
    w("     a terrain grid chunk whose payload happens to start with a u32 header.")
    w("     It is a map tile, not a config table, so R2e correctly refuses to tag it.")
    w("   - R4b (DynModelShader, 6,837 uses) is registered but emits nothing on")
    w("     purpose: that shader appears on npc, player and map-prop assets alike,")
    w("     so it identifies the renderer, not the asset class.")
    w("   - scene-effect / skill-effect stay tiny because the install separates them")
    w("     nowhere. refs has 24,886 inbound edges into group members, but they land")
    w("     on data/source/npc (20,498) and data/sharematerial (4,153); only 1 of the")
    w("     2,051 data/effect/textures groups and 1 of the 3,196 map props receives")
    w("     any inbound edge at all.  So 'which gameplay feature uses this effect'")
    w("     is not recoverable, and the 2,023 NewSfxShader materials can only be")
    w("     tagged 'effect', never 'skill-effect' vs 'scene-effect'.")
    text = "\n".join(L) + "\n"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return text


# ------------------------------------------------------------------ asserts


def assert_lexicons(con: sqlite3.Connection) -> None:
    """Fail loudly if the quest folder vocabulary drifted from LEXICON_NPC_CLASS."""
    cnt: collections.Counter = collections.Counter()
    for row in con.execute("select dir from agroups where dir like 'data/source/npc/quest/%'"):
        folder = row["dir"].rsplit("/", 1)[-1]
        t = stem_token(folder)
        cnt[t] += 1
    known = sum(v for k, v in cnt.items() if k in LEXICON_NPC_CLASS)
    tot = sum(cnt.values())
    if tot and known / tot < 0.97:
        missed = {k: v for k, v in cnt.items() if k not in LEXICON_NPC_CLASS}
        raise RuntimeError(
            "LEXICON_NPC_CLASS covers only %.1f%% of quest folders (%d/%d). "
            "Unclassified tokens: %s" % (100.0 * known / tot, known, tot,
                                         sorted(missed.items(), key=lambda x: -x[1])[:15]))


# ------------------------------------------------------------------ __main__


def main() -> int:
    assets, hits, diag = tag_database()
    nrows = write_tsv(hits)
    report = write_report(assets, hits, diag)
    total = len(assets)
    unknown = sum(1 for hs in hits.values() if hs[0].tag == "unknown")
    print(report)
    print("wrote %s (%d rows) and %s" % (TAGS_TSV, nrows, REPORT_TXT))
    print("assets=%d tagged=%d (%.1f%%) unknown=%d (%.1f%%)"
          % (total, total - unknown, 100.0 * (total - unknown) / total, unknown,
             100.0 * unknown / total))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
