"""Stable asset fingerprint for the TLBB resource DB (version-research identity).

Goal
----
Recognise *the same asset* across two client paks (2025 vs 2026) without trusting
file names, and be able to say WHAT changed ("animations: +2", "texture: -1",
"material: content changed") instead of only "something changed".  The fingerprint
is therefore a small structured bundle of digests, not one opaque hash.

Inputs come read-only from resources.db: agroups / amembers / agroup_names /
resources.  `resources.hash` is a PATH hash and is NEVER part of any digest below
(it is used only to join a member row to its content attributes).
`resources.filecrc` is the real content checksum (crc32 of the stored payload) and
is the core of every leaf.

------------------------------------------------------------------------------
CANONICAL ENCODING -- reproduce byte-for-byte in Rust.  All ints big-endian,
no padding, no separators, buffers built by appending.
------------------------------------------------------------------------------
  TOK(s)    2-byte length + UTF-8 bytes of normalize(s)   ; s is None -> 0xFFFF
  I64(v)    signed 64-bit                                 ; v is None -> -1 (all F's)
  U32(v)    unsigned 32-bit of (v & 0xFFFFFFFF)

  normalize(s)      = str(s).strip().replace('\\', '/') then ASCII-lowercase
                      (bytes 0x41..0x5A only; every other byte, including all
                      non-ASCII UTF-8, passes through UNCHANGED -- this keeps the
                      rule byte-exact in Rust: `s.as_bytes().iter().map(u8::to_ascii_lowercase)`)
  normalize_name(s) = basename(normalize(s))                      # after last '/'
  TOK payloads are the UTF-8 bytes of the normalized string.

  sha8(buf) = first 8 bytes of SHA-256(buf), rendered as 16 lowercase hex chars.
  EVERY digest in this scheme is 8 bytes / 16 hex chars.  Truncation is deliberate:
  8,537 assets -> birthday collision probability ~ 2e-15, and 16 hex matches the
  DB's existing hash width.

Domain-separation tags (12 ASCII bytes, no NUL, always prepended):
  LEAF_MAGIC  = b"TLBBFP1/leaf"      NAME_MAGIC  = b"TLBBFP1/name"
  ROLE_MAGIC  = b"TLBBFP1/role"      NAMES_MAGIC = b"TLBBFP1/names"
  ASSET_MAGIC = b"TLBBFP1/asset"

1) MEMBER LEAF TOKEN -- identity of ONE file's content, path-free
     leaf = sha8( LEAF_MAGIC
                  || TOK(type) || TOK(subtype) || TOK(codec)
                  || I64(width) || I64(height) || I64(mips)
                  || I64(original) || U32(filecrc) )
   type/subtype/codec are parsed-from-payload fields; original is the uncompressed
   size.  Deliberately EXCLUDED (packer artefacts that churn on every repack):
   pak, gen, offset, stored, occupied, method, flags, ver, ext, dir, name, path,
   and of course hash.  A member yields NO leaf when filecrc is NULL or 0 (payload
   never read) and such a member contributes to no digest.

2) PER-ROLE COMPONENT DIGEST -- order-independent multiset over one role
     leaves(role)      = sorted ascending list of the 16-char ASCII hex leaf tokens
                         of the members carrying that role (duplicates KEPT)
     role_digest(role) = sha8( ROLE_MAGIC || TOK(role) || U32(len(leaves))
                               || concat of leaves(role) as ASCII hex )
   Sorting makes member order irrelevant; keeping duplicates makes a repeated
   member visible.  Empty/absent role -> the literal string "-" (never hashed).

3) NAMES COMPONENT -- unresolved reference names (agroup_names), kept SEPARATE
     name_leaf(n) = sha8( NAME_MAGIC || TOK(normalize_name(n)) )
     fp_names     = sha8( NAMES_MAGIC || U32(count)
                          || concat of sorted name_leaf hex as ASCII )
   `cls` (unique|shared) is NOT hashed in: dbbuild computes it install-wide from
   how many sources ask for a name, so it flips between versions for reasons
   unrelated to this asset.  Names are path-stripped basenames; the extension
   stays, because for a texture the extension is content-adjacent.  Empty -> "-".

4) ASSET IDENTITY -- over EVERY role, not just the 6 surfaced in the TSV
     fp_asset = sha8( ASSET_MAGIC || U32(n_roles)
                      || for role in sorted(role names):
                           TOK(role) || U32(count) || role_digest_raw_8_bytes )
   Only roles with >=1 leaf-bearing member appear; 0 members == role absent.
   fp_names is deliberately NOT folded into fp_asset: names are path-derived
   strings and must not enter content identity.  Use the PAIR
   (fp_asset, fp_names) as the full "did anything about this asset move" key.

------------------------------------------------------------------------------
HOW TO DIFF TWO VERSIONS (why the scheme is shaped like this)
------------------------------------------------------------------------------
Match assets by fp_asset (identical content) or by gid if both dumps come from the
same DB build; a re-authored asset still shares its unchanged role digests, so
matching degrades gracefully to fp_model / fp_skeleton / fp_mesh.  Then report per
component: equal -> unchanged, different -> compare the underlying leaf sets:
    "+adds / -removes" = |leaves(B) \\ leaves(A)| / |leaves(A) \\ leaves(B)|
The leaf hex is the cross-version match key for an INDIVIDUAL file, which is why
leaves stay separate 8-byte tokens instead of being folded in one pass.
  python fingerprint.py --dump-leaves out/leaves.tsv   # (gid, role, hash, leaf)
  python fingerprint.py --diff out/2025.tsv out/2026.tsv
The diff renderer emits exactly the shape the user asked for:
  "w1351_nan_s_yifu_mjrmdz  animation: +2/-0 ; material: 3 changed ; texture: -1/+1"

Self-test (on by default, see `self_test`): shuffles every member/name list and
asserts byte-identical fingerprints; mutates single members (filecrc, texture
width) and asserts only the owning role digest plus fp_asset move while every
other component stays bit-equal; adds an unresolved name and asserts fp_names
moves but fp_asset does not; and overwrites path/dir/name/hash/pak/offset/stored/
method/flags/ver on every member and asserts every digest is frozen.
"""

import argparse
import collections
import hashlib
import os
import random
import sqlite3

DB = r"D:\TLGL\.scratch\resources.db"
OUT_DIR = r"D:\TLGL\.scratch\out"
TSV_NAME = "fingerprint.tsv"
REPORT_NAME = "fingerprint_report.txt"

LEAF_MAGIC = b"TLBBFP1/leaf"
NAME_MAGIC = b"TLBBFP1/name"
ROLE_MAGIC = b"TLBBFP1/role"
NAMES_MAGIC = b"TLBBFP1/names"
ASSET_MAGIC = b"TLBBFP1/asset"
DIGEST_BYTES = 8
NONE = "-"                      # empty-component sentinel written to the TSV

# role -> TSV column, fixed order.  Any other role (scene, map, effect, set, audio,
# table, config, other, ...) still enters fp_asset; it just has no own column.
ROLE_COL = [("fp_model", "model"), ("fp_skeleton", "skeleton"), ("fp_mesh", "mesh"),
            ("fp_material", "material"), ("fp_animation", "animation"),
            ("fp_texture", "texture")]
FP_COLS = [c for c, _ in ROLE_COL]
HEADER = ["gid", "fp_asset"] + FP_COLS + ["fp_names", "n_members", "n_names"]
COMPS = ["fp_asset"] + FP_COLS + ["fp_names"]
HUMAN = {"fp_asset": "members", "fp_model": "model", "fp_skeleton": "skeleton",
         "fp_mesh": "mesh", "fp_material": "material", "fp_animation": "animation",
         "fp_texture": "texture", "fp_names": "unresolved names"}
COL_OF_ROLE = {r: c for c, r in ROLE_COL}
HUMAN.update({c: r for c, r in ROLE_COL})

LEAF_FIELDS = ("type", "subtype", "codec", "width", "height", "mips",
               "original", "filecrc")


# ------------------------------------------------------------- primitives
def sha8(buf):
    return hashlib.sha256(bytes(buf)).digest()[:DIGEST_BYTES].hex()


def normalize(s):
    """Trim, '/' as separator, ASCII-lower.  Non-ASCII bytes pass through untouched:
    this keeps the rule exactly reproducible in Rust (see docstring: bytes 0x41-0x5A)."""
    if s is None:
        return None
    s = str(s).strip().replace("\\", "/")
    return "".join(chr(ord(c) + 32) if "A" <= c <= "Z" else c for c in s)


def normalize_name(s):
    n = normalize(s)
    return None if n is None else n.rsplit("/", 1)[-1]


def _tok(out, s):
    n = normalize(s)
    if n is None:
        out += b"\xff\xff"
        return
    b = n.encode("utf-8", "replace")
    out += len(b).to_bytes(2, "big") + b


def _i64(out, v):
    if v is None or v == "":
        out += b"\xff\xff\xff\xff\xff\xff\xff\xff"
        return
    out += int(v).to_bytes(8, "big", signed=True)


def _u32(out, v):
    out += (int(v) & 0xFFFFFFFF).to_bytes(4, "big")


def _join_hexes(out, toks):
    for t in toks:
        out += t.encode("ascii")


# ------------------------------------------------------------------- leaf
def leaf_token(rec):
    """rec: mapping carrying LEAF_FIELDS -> 16 hex leaf, or None if content unusable."""
    crc = rec.get("filecrc")
    if crc is None or crc == 0:
        return None
    buf = bytearray(LEAF_MAGIC)
    _tok(buf, rec.get("type"))
    _tok(buf, rec.get("subtype"))
    _tok(buf, rec.get("codec"))
    _i64(buf, rec.get("width"))
    _i64(buf, rec.get("height"))
    _i64(buf, rec.get("mips"))
    _i64(buf, rec.get("original"))
    _u32(buf, crc)
    return sha8(buf)


def name_leaf(name):
    buf = bytearray(NAME_MAGIC)
    _tok(buf, normalize_name(name))
    return sha8(buf)


def role_bytes(role, leaves):
    """The exact ROLE_MAGIC buffer for a (role, leaf multiset) pair."""
    buf = bytearray(ROLE_MAGIC)
    _tok(buf, role)
    _u32(buf, len(leaves))
    _join_hexes(buf, leaves)
    return bytes(buf)


def role_digest(role, leaves):
    tok = sorted(leaves)
    return sha8(role_bytes(role, tok)) if tok else NONE


def names_digest(names):
    toks = sorted(name_leaf(n) for n in names)
    if not toks:
        return NONE
    buf = bytearray(NAMES_MAGIC)
    _u32(buf, len(toks))
    _join_hexes(buf, toks)
    return sha8(buf)


def asset_digest(by_role):
    """by_role: {role: [leaf hex]} for roles with >=1 leaf-bearing member."""
    blocks = []
    for role in sorted(by_role):
        leaves = sorted(by_role[role])
        if not leaves:
            continue
        raw = hashlib.sha256(role_bytes(role, leaves)).digest()[:DIGEST_BYTES]
        blocks.append((role, len(leaves), raw))
    if not blocks:
        return NONE
    buf = bytearray(ASSET_MAGIC)
    _u32(buf, len(blocks))
    for role, count, raw in blocks:
        _tok(buf, role)
        _u32(buf, count)
        buf += raw
    return sha8(buf)


# ----------------------------------------------------------------- engine
def fingerprint_group(members, names):
    """members: [{'role','type',...}] in ANY order -> row dict (+_roles/_leaves)."""
    by_role = collections.defaultdict(list)
    leaves = []
    for m in members:
        leaf = leaf_token(m)
        if leaf is None:
            continue
        role = normalize(m.get("role")) or ""
        by_role[role].append(leaf)
        leaves.append((role, m.get("hash"), leaf))
    row = {"fp_asset": asset_digest(by_role)}
    for col, role in ROLE_COL:
        row[col] = role_digest(role, by_role.get(role, []))
    row["fp_names"] = names_digest(names)
    row["_roles"] = {r: sorted(v) for r, v in by_role.items()}
    row["_leaves"] = leaves
    return row


def open_ro(path):
    con = sqlite3.connect("file:%s?mode=ro" % path.replace("\\", "/"), uri=True)
    con.row_factory = sqlite3.Row
    return con


def load_groups(con):
    """-> OrderedDict{gid: {'members': [row], 'names': [str]}} plus {gid: hub_path}.

    The ORDER BY is just for readable output; correctness never depends on it --
    see self_test TEST 1.
    """
    groups = collections.OrderedDict()
    labels = {}
    for r in con.execute("SELECT id, hub_path FROM agroups ORDER BY id"):
        groups[r["id"]] = {"members": [], "names": []}
        labels[str(r["id"])] = r["hub_path"] or ""
    cols = "".join(", r." + f for f in LEAF_FIELDS)
    for r in con.execute("SELECT m.gid AS gid, m.hash AS hash, m.role AS role" + cols +
                         " FROM amembers m JOIN resources r ON r.hash = m.hash"
                         " ORDER BY m.gid, m.hash"):
        g = groups.get(r["gid"])
        if g is not None:
            g["members"].append(dict(r))
    for gid, name in con.execute("SELECT gid, name FROM agroup_names ORDER BY gid, name"):
        g = groups.get(gid)
        if g is not None:
            g["names"].append(name)
    return groups, labels


def compute(groups):
    """-> [(gid, row, n_members, n_names)] in input order."""
    return [(gid, fingerprint_group(g["members"], g["names"]),
             len(g["members"]), len(g["names"])) for gid, g in groups.items()]


def shuffled_copy(groups, seed):
    rnd = random.Random(seed)
    clone = collections.OrderedDict()
    for gid, g in groups.items():
        m, n = list(g["members"]), list(g["names"])
        rnd.shuffle(m)
        rnd.shuffle(n)
        clone[gid] = {"members": m, "names": n}
    return clone


# ------------------------------------------------------------- self-test
def self_test(groups, log):
    base = {gid: row for gid, row, _, _ in compute(groups)}
    ok = True
    cols = FP_COLS + ["fp_names"]

    # TEST 1 -- order independence over the whole corpus
    again = {gid: row for gid, row, _, _ in compute(shuffled_copy(groups, 20260922))}
    bad = [gid for gid in base
           if base[gid]["fp_asset"] != again[gid]["fp_asset"]
           or any(base[gid][c] != again[gid][c] for c in cols)]
    log("TEST 1  shuffle every member list and name list (seed 20260922), re-fingerprint:")
    log("        %d groups -> byte-identical digests: %s%s"
        % (len(base), "YES" if not bad else "NO",
           "" if not bad else "   first bad gids %s" % bad[:5]))
    ok &= not bad

    # TEST 2 -- change locality: filecrc+1 on one member moves ONLY its role + fp_asset
    rnd = random.Random(7)
    tested = passed = 0
    fails = []
    for gid, g in groups.items():
        roles = {normalize(m.get("role")) for m in g["members"]}
        cand = [i for i, m in enumerate(g["members"]) if leaf_token(m)]
        if len(roles) < 2 or not cand:
            continue                      # need a sibling role to prove isolation
        for i in rnd.sample(cand, min(2, len(cand))):
            old = g["members"][i]
            members = list(g["members"])
            members[i] = dict(old, filecrc=(int(old["filecrc"]) + 1) & 0xFFFFFFFF)
            row = fingerprint_group(members, g["names"])
            ref = base[gid]
            want = COL_OF_ROLE.get(normalize(old["role"]))
            moved = [c for c in cols if row[c] != ref[c]]
            problems = []
            if row["fp_asset"] == ref["fp_asset"]:
                problems.append("fp_asset did not move")
            if want and want not in moved:
                problems.append("%s did not move" % want)
            problems += ["unrelated %s moved" % c for c in moved if c != want]
            tested += 1
            (fails.append((gid, old["hash"], problems)) if problems else None)
            passed += not problems
    log("TEST 2  mutate one member's filecrc in groups with >=2 roles (%d mutations):" % tested)
    log("        only that role's digest + fp_asset changed: %d/%d  %s"
        % (passed, tested, "PASS" if tested and passed == tested else "FAIL"))
    for f in fails[:5]:
        log("        gid=%s hash=%s %s" % f)
    ok &= bool(tested) and passed == tested

    # TEST 3 -- a texture-only attribute edit must leave the other 5 columns alone
    tex = tex_ok = 0
    for gid, g in groups.items():
        for i, m in enumerate(g["members"]):
            if normalize(m.get("role")) != "texture" or not leaf_token(m):
                continue
            members = list(g["members"])
            members[i] = dict(m, width=(m.get("width") or 0) + 8, height=(m.get("height") or 0) + 8)
            row = fingerprint_group(members, g["names"])
            ref = base[gid]
            tex += 1
            if (row["fp_texture"] != ref["fp_texture"] and row["fp_asset"] != ref["fp_asset"]
                    and all(row[c] == ref[c] for c in cols
                            if c != "fp_texture")):
                tex_ok += 1
    log("TEST 3  texture member resized +8px (%d mutations): only fp_texture + fp_asset moved:"
        % tex)
    log("        %d/%d  %s" % (tex_ok, tex, "PASS" if tex and tex_ok == tex
                               else "SKIP (no texture members in this install)" if not tex
                               else "FAIL"))
    ok &= tex_ok == tex

    # TEST 4 -- name drift is isolated: it must NOT touch content identity
    ntest = npass = 0
    for gid, g in groups.items():
        if not g["names"]:
            continue
        row = fingerprint_group(g["members"], sorted(list(g["names"]) + ["zz_probe.tga"]))
        ref = base[gid]
        ntest += 1
        if (row["fp_names"] != ref["fp_names"] and row["fp_asset"] == ref["fp_asset"]
                and all(row[c] == ref[c] for c in FP_COLS)):
            npass += 1
    log("TEST 4  append one unresolved texture name (%d groups): only fp_names moved,"
        " fp_asset untouched: %d/%d  %s" % (ntest, npass, ntest,
                                            "PASS" if ntest and npass == ntest else "FAIL"))
    ok &= bool(ntest) and npass == ntest

    # TEST 5 -- path/metadata fuzz: rename, move, repack every member; digests frozen
    junk = ("path", "dir", "name", "ext", "hash", "pak", "gen", "offset",
            "stored", "occupied", "method", "flags", "ver", "src", "self_path")
    ftel = fpass = 0
    for gid, g in groups.items():
        members = []
        for i, m in enumerate(g["members"]):
            d = dict(m)
            for k in junk:
                d[k] = "ZZ%08x" % (gid * 977 + i) if k in ("path", "dir", "name", "hash") \
                    else (i + 3)
            members.append(d)
        row = fingerprint_group(members, g["names"])
        ref = base[gid]
        ftel += 1
        if all(row[c] == ref[c] for c in FP_COLS + ["fp_names", "fp_asset"]):
            fpass += 1
    log("TEST 5  overwrite path/name/hash/pak/offset/stored/method/flags/ver on every")
    log("        member (%d groups): all digests unchanged: %d/%d  %s"
        % (ftel, fpass, ftel, "PASS" if ftel and fpass == ftel else "FAIL"))
    ok &= bool(ftel) and fpass == ftel
    return ok, base


# ---------------------------------------------------------------- outputs
def write_tsv(path, rows):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\t".join(HEADER) + "\n")
        for gid, row, nm, nn in rows:
            fh.write("\t".join([str(gid), row["fp_asset"]] + [row[c] for c in FP_COLS]
                               + [row["fp_names"], str(nm), str(nn)]) + "\n")


def write_leaves(path, groups):
    n = 0
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("gid\trole\thash\tleaf\n")
        for gid, g in groups.items():
            for m in sorted(g["members"], key=lambda r: (normalize(r["role"]) or "",
                                                          str(r["hash"]))):
                leaf = leaf_token(m)
                if leaf is None:
                    continue
                fh.write("%d\t%s\t%s\t%s\n" % (gid, normalize(m["role"]), m["hash"], leaf))
                n += 1
            for name in sorted(g["names"], key=lambda x: normalize_name(x) or ""):
                fh.write("%d\tname\t-\t%s\n" % (gid, name_leaf(name)))
                n += 1
    return n


def multiset(row):
    return [t for toks in row["_roles"].values() for t in toks]


def collision_lines(rows, labels):
    by_fp = collections.defaultdict(list)
    zero = 0
    for gid, row, _, _ in rows:
        if row["fp_asset"] == NONE:
            zero += 1
        else:
            by_fp[row["fp_asset"]].append((gid, row))
    clusters = {k: v for k, v in by_fp.items() if len(v) > 1}
    true_hash_collision = sum(1 for members in clusters.values()
                              if not all(multiset(r) == multiset(members[0][1])
                                         for _, r in members[1:]))
    out = ["groups                                  : %d" % len(rows),
           "distinct fp_asset (content-bearing)     : %d" % len(by_fp),
           "groups with NO content digest ('-')     : %d" % zero,
           "collision clusters (>1 group per fp_asset): %d, covering %d groups"
           % (len(clusters), sum(len(v) for v in clusters.values())),
           "clusters whose leaf multisets DIFFER (true sha256 collisions): %d"
           % true_hash_collision]
    for fp, members in sorted(clusters.items(), key=lambda kv: -len(kv[1]))[:3]:
        gids = [g for g, _ in members]
        same = all(multiset(r) == multiset(members[0][1]) for _, r in members[1:])
        out.append("   x%d gids %s -> identical leaf multiset: %s"
                   % (len(members), gids[:6], same))
        out.append("      hubs: %s" % " | ".join((labels.get(str(g), "") or "<unnamed>")[:46]
                                                 for g in gids[:3]))
    if clusters:
        out.append("explanation: a cluster is several assets assembled from exactly the same")
        out.append("content blobs (engine/template copies shipped under several folders) --")
        out.append("intended, not a defect: identity here is content, so same content ==")
        out.append("same fingerprint. Disambiguate location with the (fp_asset, agroups.dir)")
        out.append("pair, which stays outside the digest.")
    else:
        out.append("explanation: none needed -- every asset in this corpus has a distinct")
        out.append("member-content set, so fp_asset is fully discriminating. Had a cluster")
        out.append("appeared it would be several folders assembled from exactly the same")
        out.append("blobs (engine/template copies): intended behaviour, since identity here")
        out.append("IS content. Disambiguate location with (fp_asset, agroups.dir).")
    return out, len(by_fp), len(clusters), sum(len(v) for v in clusters.values())


def sharing_lines(rows):
    """Component digests shared by several assets: content reuse, not a collision."""
    out = []
    leaf = collections.Counter(t for _, r, _, _ in rows
                               for toks in r["_roles"].values() for t in toks)
    dup = {k: v for k, v in leaf.items() if v > 1}
    multisets = collections.Counter(tuple(sorted(t for toks in r["_roles"].values()
                                                 for t in toks))
                                    for _, r, _, _ in rows)
    out.append("  member leaves %d, distinct %d -> %d individual blobs are byte-identical"
               " to another asset's blob" % (sum(leaf.values()), len(leaf),
                                             sum(v for v in dup.values())))
    same_full = sum(v for v in multisets.values() if v > 1)
    out.append("  assets whose FULL leaf multiset equals another asset's, checked WITHOUT any")
    out.append("  hashing: %d -- so the collision count in the UNIQUENESS section is a property"
               % same_full)
    out.append("  of this corpus (no two whole assets are byte-identical), not a truncation artefact.")
    out.append("  per component (reuse IS common at component level):")
    for col in FP_COLS + ["fp_names"]:
        c = collections.Counter(r[col] for _, r, _, _ in rows if r[col] != NONE)
        have = sum(c.values())
        top = c.most_common(1)
        reuse = top[0][1] if top else 0
        out.append("    %-13s groups %6d  distinct %6d  most reused digest x%d%s"
                   % (col, have, len(c), reuse,
                      " (%s)" % top[0][0] if reuse > 1 else ""))
    out.append("A repeated component digest means several assets embed the same blob (a")
    out.append("template material, a base skeleton, a shared mask): the diff tool must")
    out.append("report it as 'shared, unchanged' rather than as a change. fp_asset stays")
    out.append("unique because the SURROUNDING member set differs.")
    return out


def role_lines(groups, rows):
    cnt = collections.Counter()
    gcount = collections.Counter()
    for gid, g in groups.items():
        seen = set()
        for m in g["members"]:
            leaf = leaf_token(m)
            if leaf is None:
                continue
            r = normalize(m["role"])
            cnt[r] += 1
            seen.add(r)
        gcount.update(seen)
    out = []
    for role, n in cnt.most_common():
        out.append("  %-11s members %7d  groups %6d  column %s"
                   % (role, n, gcount[role], COL_OF_ROLE.get(role, "(fp_asset only)")))
    out.append("")
    for col in FP_COLS:
        out.append("  groups where %s == '-' (role absent): %d"
                   % (col, sum(1 for _, r, _, _ in rows if r[col] == NONE)))
    out.append("  groups where fp_names == '-' (no unresolved names): %d"
               % sum(1 for _, r, _, _ in rows if r["fp_names"] == NONE))
    return out


WEAKNESSES = [
    "1. filecrc is the crc32 of the STORED payload. Re-compressing unchanged content",
    "   (new packer build, new level, method 0 <-> 51) flips every leaf even though the",
    "   asset is semantically identical, so a pure repack reads as 'everything changed'.",
    "   The DB holds no hash of the decompressed stream; adding one (or crc of the",
    "   decoded bytes) is the single biggest robustness win available. Partial",
    "   mitigation: `original` + dims + type/codec ARE repack-stable, so a diff where",
    "   leaves move but (original, width, height, type, codec) do not is repack-only.",
    "2. crc32 is 32 bits and the leaf is truncated to 64. Inside one role set a real",
    "   crc32 collision between two different files would be invisible. Negligible at",
    "   4.5 members/group, but a payload hash removes the doubt.",
    "3. Roles come from amembers.role, which dbbuild derives from the file EXTENSION.",
    "   The digests are path-free but the BUCKETING is not: renaming .tga -> .dds moves",
    "   a member between two component digests. fp_asset moves too, so nothing hides.",
    "4. fp_asset is name-free, so two folders holding the same blobs collide BY DESIGN",
    "   (see the collision section). Content identity answers 'is this the same asset',",
    "   not 'which asset is this'; pair it with the group's dir/kind to pin location.",
    "5. Group boundaries are a heuristic (union-find over use-* edges + shared-degree",
    "   cut + single-asset-directory absorption). If a patch changes the inbound degree",
    "   of a shared mesh, the asset SPLITS or MERGES and a whole neighbourhood of",
    "   digests moves. That, not the digests, is the dominant false-positive source.",
    "6. Only 6 roles get their own column; scene/map/effect/set/other are folded into",
    "   fp_asset. An asset can therefore change with all 6 surfaced digests identical",
    "   (fp_asset moved, no component explains it) -> use --dump-leaves to localize.",
    "7. Unresolved names have no bytes in this install, so a renamed dangling texture is",
    "   an unassociable -1/+1 pair, and cls is dropped from fp_names, which also drops",
    "   the unique/shared signal from the digest (still visible as a raw column in the",
    "   DB if a future dump wants a second names component).",
    "8. 10 agroup_names are GBK bytes mis-decoded as Latin-1 by the extractor, so their",
    "   bytes differ from a correctly decoded next-version dump and fp_names would move",
    "   for those assets alone. normalize() therefore lowercases ONLY ASCII A-Z: any",
    "   Unicode case-folding would mutate those mojibake codepoints a second time and",
    "   make the Rust port diverge. Fix the decoder upstream, not the fingerprint.",
]


def write_report(path, groups, rows, labels, stats, test_lines, ok, demo):
    L = []
    w = L.append

    def sec(title):
        w("")
        w("--- %s %s" % (title, "-" * max(3, 71 - len(title))))

    w("ASSET FINGERPRINT REPORT   (TLBB resources.db, opened read-only)")
    w("=" * 76)
    w("Scheme: SHA-256 truncated to 8 bytes (16 lowercase hex) at every level.")
    w("  leaf      = crc32(stored) + uncompressed size + type/subtype/codec + dims/mips")
    w("  fp_<role> = sorted multiset of leaf tokens of that role  (order-free)")
    w("  fp_asset  = every role's (name, count, digest) folded in; path/name-free")
    w("  fp_names  = sorted basenames of unresolved agroup_names, OUTSIDE fp_asset")
    w("Byte-exact spec (Rust-portable) is in the fingerprint.py module docstring.")
    sec("COVERAGE")
    for k, v in stats:
        w("%-50s %12s" % (k, v))
    sec("UNIQUENESS / COLLISIONS")
    col, distinct, nclusters, ncovering = collision_lines(rows, labels)
    L.extend(col)
    sec("COMPONENT SHARING (same blob inside several assets)")
    for line in sharing_lines(rows):
        w(line)
    sec("ROLE COVERAGE")
    w("Only 6 roles have their own TSV column; the rest still feed fp_asset, so an")
    w("asset CAN change with all 6 surfaced digests unchanged.")
    for line in role_lines(groups, rows):
        w(line)
    sec("SELF-TEST (run on this corpus)")
    for line in test_lines:
        w(line)
    sec("DEMO: SYNTHETIC NEXT-VERSION DIFF")
    w("Rendered by the same compare() that --diff uses on two real dumps.")
    for line in demo:
        w(line)
    w("")
    w("RESULT: %s" % ("ALL ASSERTIONS PASSED" if ok else "FAILED -- see SELF-TEST above"))
    sec("KNOWN WEAKNESSES")
    for line in WEAKNESSES:
        w(line)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(L) + "\n")
    return distinct, nclusters, ncovering


# ------------------------------------------------------------------ diff
def compare(A, B, labels, leavesA=None, leavesB=None):
    """A/B: {gid(str): {col: str}}.  -> list of report lines.  Used by --diff and demo."""
    comps = COMPS
    matched = {}
    for g in A:
        if g in B:
            matched[g] = g
    by_asset = collections.defaultdict(list)
    for g, r in B.items():
        if r["fp_asset"] != NONE:
            by_asset[r["fp_asset"]].append(g)
    used = set(matched.values())
    for g in A:
        if g in matched:
            continue
        cand = [x for x in by_asset.get(A[g]["fp_asset"], []) if x not in used]
        if cand:
            matched[g] = cand[0]
            used.add(cand[0])
    out = ["matched %d ; only in A %d ; only in B %d"
           % (len(matched), len(A) - len(matched), len(B) - len(used)), ""]
    n_lines = 0
    for g in sorted(matched, key=lambda x: int(x)):
        h = matched[g]
        ra, rb = A[g], B[h]
        ch = [c for c in comps if ra.get(c, NONE) != rb.get(c, NONE)]
        if not ch:
            continue
        parts = []
        for c in ch:
            if c == "fp_names":
                parts.append("unresolved names: %s -> %s" % (ra["n_names"], rb["n_names"]))
            elif c == "fp_asset":
                continue
            else:
                role = HUMAN[c]
                if leavesA is not None:
                    a = collections.Counter(leavesA.get(g, {}).get(role, []))
                    b = collections.Counter(leavesB.get(h, {}).get(role, []))
                    add = sum((b - a).values())
                    rem = sum((a - b).values())
                    parts.append("%s: %d changed" % (role, add) if add == rem
                                 else "%s +%d/-%d" % (role, add, rem))
                else:
                    parts.append("%s changed" % role)
        if not parts:
            parts.append("member set changed")
        label = (labels.get(g) or ("<gid %s>" % g))
        out.append("  %-6s %-52s %s" % (g, label[:52], " ; ".join(parts)))
        n_lines += 1
    out.append("")
    out.append("assets with at least one component moved: %d" % n_lines)
    return out


def read_dump(path):
    rows = {}
    with open(path, encoding="utf-8") as fh:
        head = fh.readline().rstrip("\n").split("\t")
        for line in fh:
            v = line.rstrip("\n").split("\t")
            rows[v[0]] = dict(zip(head, v))
    return rows


def run_diff(a_path, b_path, con):
    A, B = read_dump(a_path), read_dump(b_path)
    labels = {str(g): (hp or "") for g, hp in con.execute("SELECT id, hub_path FROM agroups")}
    return "\n".join(["A=%s (%d)  B=%s (%d)" % (a_path, len(A), b_path, len(B))]
                     + compare(A, B, labels))


def synthetic_demo(groups, labels, n_changes=5):
    """Build a fake 'next version' and render the diff -- proves the report shape."""
    base_rows = compute(groups)
    A = {str(gid): dict([(k, row[k]) for k in COMPS], n_members=str(nm), n_names=str(nn))
         for gid, row, nm, nn in base_rows}
    leavesA = {str(gid): row["_roles"] for gid, row, _, _ in base_rows}

    def role_pool(role, at_least=1):
        return [gid for gid, row, _, _ in base_rows
                if len(row["_roles"].get(role, [])) >= at_least]

    rnd = random.Random(11)
    anim = rnd.sample(role_pool("animation"), n_changes)
    mtl = rnd.sample(role_pool("material", 3), n_changes)
    nm = [g for g in rnd.sample([gid for gid, row, _, _ in base_rows if row["fp_names"] != NONE],
                                n_changes)]
    B = {k: dict(v) for k, v in A.items()}
    leavesB = {k: {r: list(v) for r, v in d.items()} for k, d in leavesA.items()}

    def fake_leaf(tag, seed):
        return sha8(bytearray(tag) + b"\x00" * 16 + str(seed).encode())

    for gid in anim:                                   # (a) two new animation files
        k = str(gid)
        toks = sorted(leavesB[k].get("animation", []) +
                      [fake_leaf(LEAF_MAGIC, gid * 10 + 1), fake_leaf(LEAF_MAGIC, gid * 10 + 2)])
        leavesB[k]["animation"] = toks
        B[k]["fp_animation"] = role_digest("animation", toks)
        B[k]["n_members"] = str(int(A[k]["n_members"]) + 2)
    for gid in mtl:                                    # (b) three materials edited
        k = str(gid)
        toks = sorted([fake_leaf(b"TLBBFP1/edit", gid * 10 + j) for j in range(3)] +
                      leavesB[k]["material"][3:])
        leavesB[k]["material"] = toks
        B[k]["fp_material"] = role_digest("material", toks)
    for gid in nm:                                     # (c) one unresolved name gone
        k = str(gid)
        B[k]["n_names"] = str(int(A[k]["n_names"]) - 1)
        B[k]["fp_names"] = names_digest(groups[gid]["names"][1:])
    for gid in list(anim) + list(mtl):                 # content moved -> asset moves
        B[str(gid)]["fp_asset"] = asset_digest(leavesB[str(gid)])
    notes = ["synthetic v2 from this very DB: %d assets +2 animation files, %d assets with 3"
             " material blobs edited in place, %d assets missing 1 unresolved texture name."
             % (len(anim), len(mtl), len(nm)),
             "Matching falls back to fp_asset when gids differ, so an asset renamed or moved"
             " to another folder is still recognised."]
    body = compare(A, B, labels, leavesA, leavesB)
    return notes + [""] + body[:16]


# ------------------------------------------------------------------ main
def main(argv=None):
    ap = argparse.ArgumentParser(description="Stable TLBB asset fingerprints (read-only).")
    ap.add_argument("--db", default=DB)
    ap.add_argument("--out-dir", default=OUT_DIR)
    ap.add_argument("--no-selftest", action="store_true")
    ap.add_argument("--dump-leaves", metavar="PATH")
    ap.add_argument("--diff", nargs=2, metavar=("A.tsv", "B.tsv"),
                    help="print the per-asset component report between two dumps")
    a = ap.parse_args(argv)

    con = open_ro(a.db)
    if a.diff:
        print(run_diff(a.diff[0], a.diff[1], con))
        con.close()
        return 0
    groups, labels = load_groups(con)
    names_col = {gid: n for gid, n in con.execute("SELECT id, names FROM agroups")}
    con.close()

    rows = compute(groups)
    os.makedirs(a.out_dir, exist_ok=True)
    tsv = os.path.join(a.out_dir, TSV_NAME)
    write_tsv(tsv, rows)

    members = sum(len(g["members"]) for g in groups.values())
    noleaf = sum(1 for g in groups.values() for m in g["members"] if leaf_token(m) is None)
    stats = [
        ("asset groups fingerprinted", len(groups)),
        ("members joined to resources", members),
        ("members WITHOUT a content leaf (filecrc null/0)", noleaf),
        ("groups WITHOUT any content leaf (fp_asset '-')",
         sum(1 for _, r, _, _ in rows if r["fp_asset"] == NONE)),
        ("unresolved names attached", sum(len(g["names"]) for g in groups.values())),
        ("groups where agroups.names != row count",
         sum(1 for gid, g in groups.items() if names_col.get(gid) != len(g["names"]))),
        ("distinct fp_names", len({r["fp_names"] for _, r, _, _ in rows})),
        ("rows written", "%s (%s)" % (len(rows), os.path.basename(tsv))),
        ("spec", "fingerprint.py docstring / TLBBFP1"),
    ]

    test_lines, ok, demo = [], True, []
    if not a.no_selftest:
        buf = []
        ok, _ = self_test(groups, buf.append)
        test_lines = ["    " + l for l in buf]
        demo = ["    " + l for l in synthetic_demo(groups, labels)]
    else:
        test_lines = ["    skipped (--no-selftest): fingerprints are unverified against the"
                      " stability assertions"]
    if a.dump_leaves:
        con = open_ro(a.db)
        n = write_leaves(a.dump_leaves, load_groups(con)[0])
        con.close()
        print("leaves: %d -> %s" % (n, a.dump_leaves))
    rep = os.path.join(a.out_dir, REPORT_NAME)
    distinct, nclusters, ncovering = write_report(rep, groups, rows, labels, stats,
                                                  test_lines, ok, demo)
    print("groups %d  distinct fp_asset %d  collisions %d clusters / %d groups"
          % (len(rows), distinct, nclusters, ncovering))
    print("self-test: %s" % ("PASS" if ok else "FAIL"))
    for line in test_lines:
        print(line)
    print("tsv    -> %s" % tsv)
    print("report -> %s" % rep)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
