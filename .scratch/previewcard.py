"""Asset thumbnail cards for the TLBB resource browser.

    python previewcard.py [--limit N] [--size 224] [--out previews]

Builds one square PNG per asset group (agroups.id -> <out>/<gid>.png) with a
three-level fallback so the asset list reads like an asset library instead of a
database table:

  L1 real texture    at least one member whose resources.type='texture' has a
                     payload that decodes -> that texture (largest `original`)
                     rendered over a dark checkerboard.
  L2 material card   no decodable texture but >=1 material member -> a material
                     node: shader class, material file names, up to 6 referenced
                     texture names.  The texture bytes may be unresolvable, the
                     material relationship is real and is what gets shown.
  L3 placeholder     neither -> [MODEL]/[MESH]/[ANI]/[SCENE]/[SFX] glyph block
                     by dominant role, the stem, and the member counts.

Read-only by construction: resources.db is opened with mode=ro, payloads come
from the already-extracted out/all tree, no .pak is touched.  Decoders are
imported from explorer.py, never reimplemented.

Resumable: a group whose PNG already exists is not re-rendered.  Interrupt
safe: every card is written to <gid>.png.tmp.NNN then os.replace()d, so a
half-written card can never be mistaken for a finished one.

Stdlib + Pillow only.
"""
import argparse
import collections
import json
import os
import sqlite3
import sys
import time

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, 'resources.db')
sys.path.insert(0, HERE)
import explorer  # noqa: E402  (import-safe: the server lives behind __main__)

# ------------------------------------------------------------------ palette
BG = (24, 26, 30)            # card background  #181a1e
BORDER = (43, 47, 54)        # 1px card border  #2b2f36
PANEL = (30, 33, 39)
PANEL_HI = (37, 41, 48)
STEM = (201, 205, 212)       # light grey stem text
TXT = (168, 174, 184)
DIM = (126, 132, 143)
FAINT = (86, 92, 102)
RULE = (49, 54, 62)

LEVEL_COL = {                # (text, panel fill, outline)
    'L1': ((126, 214, 168), (28, 46, 40), (58, 96, 78)),
    'L2': ((223, 171, 100), (48, 40, 28), (98, 76, 46)),
    'L3': ((140, 149, 165), (34, 38, 45), (62, 69, 81)),
}
ROLE_COL = {
    'MODEL': (122, 162, 247),
    'MESH': (158, 206, 106),
    'ANI': (224, 175, 104),
    'SCENE': (187, 154, 247),
    'SFX': (247, 118, 142),
}
SHADER_COL = {
    'DynModelShader': (126, 170, 235),
    'NewSfxShader': (233, 130, 152),
    'none': (126, 132, 143),
}
NAME_COL = {'unique': (176, 186, 200), 'shared': (112, 120, 133)}
TEX_EXT = ('.tga', '.dds', '.png', '.jpg', '.jpeg', '.webp', '.bmp')

# dominant-role buckets, highest priority first
ROLE_OF = {'model': 'MODEL', 'mesh': 'MESH', 'texture': 'MODEL',
           'animation': 'ANI', 'skeleton': 'ANI',
           'scene': 'SCENE', 'map': 'SCENE',
           'effect': 'SFX', 'other': 'SFX', 'material': 'SFX'}
ROLE_PRIORITY = ('MODEL', 'MESH', 'ANI', 'SCENE', 'SFX')

FONT_CANDIDATES = {
    'sans': ['C:/Windows/Fonts/segoeui.ttf', 'C:/Windows/Fonts/arial.ttf',
             'C:/Windows/Fonts/tahoma.ttf',
             '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
             '/System/Library/Fonts/Helvetica.ttc'],
    'mono': ['C:/Windows/Fonts/consola.ttf', 'C:/Windows/Fonts/cour.ttf',
             '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf',
             '/System/Library/Fonts/Menlo.ttc'],
}
_fonts = {}


def getfont(kind, px):
    """Truetype if any is installed, else the plain PIL default font.

    Never picks a CJK face and never raises: with no truetype at all the
    bundled PIL default is used, which renders the (ASCII) text a little
    coarser but keeps the cards readable.
    """
    px = max(6, int(px))
    key = (kind, px)
    if key in _fonts:
        return _fonts[key]
    f = None
    for path in FONT_CANDIDATES.get(kind, []) + FONT_CANDIDATES['sans']:
        if not os.path.exists(path):
            continue
        try:
            f = ImageFont.truetype(path, px)
            break
        except Exception:
            f = None
    if f is None:
        try:
            f = ImageFont.load_default(size=px)
        except TypeError:
            f = ImageFont.load_default()
        except Exception:
            f = ImageFont.load_default()
    _fonts[key] = f
    return f


_probe = ImageDraw.Draw(Image.new('RGB', (8, 8)))
_cache_len = {}


def tlen(s, font):
    key = (s, id(font))
    v = _cache_len.get(key)
    if v is None:
        try:
            v = _probe.textlength(s, font=font)
        except Exception:
            v = len(s) * 6
        _cache_len[key] = v
    return v


def clip(s, font, maxw):
    """ASCII-safe middle-of-the-line truncation with '..'."""
    if tlen(s, font) <= maxw:
        return s
    keep = max(1, int(len(s) * max(0.05, (maxw - 6) / max(1.0, tlen(s, font)))))
    while keep > 1 and tlen(s[:keep] + '..', font) > maxw:
        keep -= 1
    return s[:keep] + '..'


def rrect(d, box, rad, **kw):
    if hasattr(d, 'rounded_rectangle'):
        d.rounded_rectangle(box, radius=rad, **kw)
    else:                                    # very old Pillow
        d.rectangle(box, **kw)


def vcenter(d, y0, h, s, font):
    """Draw-size independent vertical centring for a single text line."""
    try:
        bb = d.textbbox((0, 0), s, font=font)
        return y0 + (h - (bb[3] - bb[1])) / 2 - bb[1]
    except Exception:
        return y0 + h * 0.15


# ------------------------------------------------------------------- data
def load_plan(con):
    """Three bulk queries, then everything is in-memory."""
    groups = con.execute(
        'select id, stem, kind, n, n_mesh, n_mtl, n_ani, n_ske, n_tex, n_other '
        'from agroups order by id').fetchall()

    members = {}
    for gid, h, role, typ, name, props in con.execute(
            'select m.gid, m.hash, m.role, r.type, r.name, r.props '
            'from amembers m left join resources r on r.hash = m.hash'):
        members.setdefault(gid, []).append((role, typ, name, h, props))

    texsize = {}
    for gid, h, orig in con.execute(
            'select m.gid, m.hash, r.original from amembers m '
            "join resources r on r.hash = m.hash where r.type = 'texture'"):
        cur = texsize.get(gid)
        if cur is None or (orig or 0) > cur[1]:
            texsize[gid] = (h, orig or 0)

    names = {}
    for gid, nm, cls in con.execute(
            "select gid, name, cls from agroup_names "
            "order by gid, case cls when 'unique' then 0 else 1 end, name"):
        names.setdefault(gid, []).append((nm, cls))
    return groups, members, texsize, names


_props_cache = {}


def props_of(props):
    if props in _props_cache:
        return _props_cache[props]
    d = {}
    if props:
        try:
            d = json.loads(props) or {}
        except Exception:
            d = {}
    if len(_props_cache) < 40000:
        _props_cache[props] = d
    return d


def classify(gid, members, texsize):
    """-> (level, extra) where extra carries what the renderer needs."""
    rows = members.get(gid) or []
    hash_ = texsize.get(gid)
    if hash_:
        return 'L1', {'hash': hash_[0]}
    mtl = [r for r in rows if r[0] == 'material']
    if not mtl:
        # an anonymous JBCF that carries a shader class or texture names IS a material;
        # role comes from the extension, which these files do not have.  A .pu carries
        # 'fx' instead and names its own material, so it is an asset card too.
        mtl = [r for r in rows
               if r[4] and ('"shader"' in r[4] or '"refs"' in r[4] or '"fx"' in r[4])]
    if mtl:
        return 'L2', {'mtl': mtl}
    return 'L3', {}


# ------------------------------------------------------------------ render
def frame(S):
    im = Image.new('RGB', (S, S), BG)
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, S - 1, S - 1], outline=BORDER)
    return im, d


def badge(d, S, u, lvl):
    txt, fill, line = LEVEL_COL[lvl]
    f = getfont('mono', 9 * u)
    w = max(18 * u, tlen(lvl, f) + 9 * u)
    box = [S - 6 * u - w, 6 * u, S - 6 * u, 20 * u]
    rrect(d, box, 3 * u, fill=fill, outline=line, width=1)
    d.text((box[0] + (box[2] - box[0] - tlen(lvl, f)) / 2,
            vcenter(d, box[1], box[3] - box[1], lvl, f)), lvl, font=f, fill=txt)


def footer(d, S, u, stem, right):
    """Stem band: light grey name bottom-left, counts bottom-right."""
    fnum = getfont('mono', 8 * u)
    ry = S - 25 * u
    if right:
        d.text((S - 8 * u - tlen(right, fnum), ry + 2 * u), right, font=fnum,
               fill=FAINT)
        room = S - 16 * u - tlen(right, fnum) - 8 * u
    else:
        room = S - 16 * u
    f = None
    for px in (13, 12, 11, 10, 9):
        cand = getfont('sans', px * u)
        if tlen(stem, cand) <= room or px == 9:
            f = cand
            break
    d.text((8 * u, S - 23 * u), clip(stem, f, room), font=f, fill=STEM)


def glyph_box(d, S, u, role, y0=None):
    col = ROLE_COL[role]
    label = '[%s]' % role
    f = getfont('mono', 14 * u)
    tw = tlen(label, f)
    bw, bh = max(52 * u, tw + 20 * u), 30 * u
    x0 = (S - bw) / 2
    if y0 is None:
        y0 = 40 * u
    fill = tuple(int(BG[i] + (col[i] - BG[i]) * 0.14) for i in range(3))
    line = tuple(int(BG[i] + (col[i] - BG[i]) * 0.55) for i in range(3))
    rrect(d, [x0, y0, x0 + bw, y0 + bh], 4 * u, fill=fill, outline=line, width=1)
    d.text((x0 + (bw - tw) / 2, vcenter(d, y0, bh, label, f)), label, font=f,
           fill=col)
    return y0 + bh


# ---- L1 -----------------------------------------------------------------
_decoded = {}


def texture_png_bytes(hash_, payloads, size, info_out):
    path = payloads.get(hash_)
    if not path:
        info_out['error'] = 'payload missing'
        return None
    key = (path, size)
    if key in _decoded:
        return _decoded[key]
    try:
        with open(path, 'rb') as fh:
            raw = fh.read()
    except Exception as e:
        info_out['error'] = 'read: %s' % e
        return None
    img, info = explorer.decode_jmt1(raw)
    if img is None:
        info_out['error'] = info.get('error', 'decode failed')
        return None
    info_out.update(info)
    png = explorer.over_checker(img, size)
    if len(_decoded) < 300:
        _decoded[key] = png
    return png


def card_l1(S, u, gid, stem, hash_, payloads, meta, n):
    box_w, box_h = S - 16 * u, S - 60 * u
    px = int(min(box_w, box_h))
    png = texture_png_bytes(hash_, payloads, px, meta)
    if png is None:
        return None
    import io
    tex = Image.open(io.BytesIO(png))
    tex.load()
    im, d = frame(S)
    f = getfont('mono', 9 * u)
    cap = '%dx%d %s' % (meta.get('width') or tex.width,
                        meta.get('height') or tex.height,
                        meta.get('codec') or '?')
    d.text((8 * u, 8 * u), cap, font=f, fill=DIM)
    x0 = int((S - tex.width) / 2)
    y0 = int(22 * u + (box_h - tex.height) / 2)
    im.paste(tex.convert('RGB'), (x0, y0))
    d.rectangle([x0 - 1, y0 - 1, x0 + tex.width, y0 + tex.height], outline=RULE)
    badge(d, S, u, 'L1')
    footer(d, S, u, stem or ('unnamed #%d' % gid), '%d mbrs' % n)
    return im


# ---- L2 -----------------------------------------------------------------
def card_l2(S, u, gid, stem, mtl_rows, tex_names, n, kind):
    shaders = collections.Counter()
    files = []
    refs = []
    for role, typ, name, h, props in mtl_rows:
        p = props_of(props)
        fx = p.get('fx')
        if fx:
            chip = ' '.join(x for x in ((fx.get('renderer') or [''])[0],
                                        (fx.get('blend') or [''])[0]) if x)
            shaders[chip or 'none'] += 1
            files.extend(fx.get('material') or [])
            refs.extend(fx.get('texture') or [])
            continue
        sh = p.get('shader')
        if not sh:
            for r in (p.get('refs') or []):
                if r.endswith('Shader'):
                    sh = r
                    break
        shaders[sh or 'none'] += 1
        if name:
            files.append(name)
        for r in (p.get('refs') or []):
            if r.lower().endswith(TEX_EXT):
                refs.append(r)
    shader = shaders.most_common(1)[0][0]
    shader_col = SHADER_COL.get(shader, SHADER_COL['none'])

    listed = []
    seen = set()
    for nm, cls in tex_names:
        if nm and nm not in seen:
            seen.add(nm)
            listed.append((nm, cls))
    if len(listed) < 6:
        for nm in refs:
            if nm not in seen:
                seen.add(nm)
                listed.append((nm, 'shared'))
    total = len(listed)

    im, d = frame(S)
    fc = getfont('mono', 9 * u)
    ft = getfont('mono', 9.5 * u)
    fl = getfont('mono', 7.5 * u)

    # shader chip
    lbl = shader if shader != 'none' else 'no shader'
    w = tlen(lbl, fc) + 10 * u
    box = [8 * u, 7 * u, 8 * u + w, 21 * u]
    fill = tuple(int(BG[i] + (shader_col[i] - BG[i]) * 0.16) for i in range(3))
    line = tuple(int(BG[i] + (shader_col[i] - BG[i]) * 0.5) for i in range(3))
    rrect(d, box, 3 * u, fill=fill, outline=line, width=1)
    d.text((box[0] + 5 * u, vcenter(d, box[1], box[3] - box[1], lbl, fc)), lbl,
           font=fc, fill=shader_col)
    nm_mtl = len(mtl_rows)
    tail = '%d mtl' % nm_mtl
    d.text((box[2] + 6 * u, vcenter(d, box[1], box[3] - box[1], tail, fl)), tail,
           font=fl, fill=FAINT)

    # material file names -- expand into the freed space when there is no
    # texture list to show, so the card never has a bottom half of nothing
    mat_lines = 2 if total >= 4 else (3 if total >= 2 else 4)
    y = 27 * u
    room = S - 30 * u
    shown = files[:mat_lines]
    for fn in shown:
        d.rectangle([9 * u, y + 3 * u, 11 * u, y + 5 * u], fill=shader_col)
        d.text((16 * u, y), clip(fn, ft, room), font=ft, fill=TXT)
        y += 12 * u
    if len(files) > mat_lines:
        d.text((16 * u, y), '+%d more' % (len(files) - mat_lines), font=fl,
               fill=FAINT)
        y += 11 * u
    elif not files:
        d.text((16 * u, y), '(unnamed material)', font=fl, fill=FAINT)
        y += 11 * u

    y = max(y + 4 * u, 54 * u)
    d.line([8 * u, y, S - 8 * u, y], fill=RULE, width=1)
    y += 5 * u
    lab = 'T E X T U R E S'
    d.text((8 * u, y), lab, font=fl, fill=FAINT)
    d.text((8 * u + tlen(lab, fl) + 5 * u, y), '%d' % total, font=fl,
           fill=(223, 171, 100) if total else FAINT)
    y += 11 * u

    bottom = S - 32 * u
    avail = max(14 * u, bottom - y)
    rows = min(total, 6)
    extra = 11 * u if total > 6 else 0
    if total:
        rowh = min(17 * u, max(10 * u, (avail - extra) / float(rows)))
        block = rowh * rows + extra
        # keep the rows under their label; only a little centring drift
        y += min(max(0.0, (avail - block) / 2.0), 10 * u)
        rail = tuple(int(BG[i] + (223 - BG[i]) * 0.30) for i in range(3))
        d.rectangle([8 * u, y + 1 * u, 9 * u, y + rowh * rows - 2 * u], fill=rail)
        for i, (tn, cls) in enumerate(listed[:6]):
            col = NAME_COL.get(cls, NAME_COL['shared'])
            ry = y + rowh * i
            d.rectangle([13 * u, ry + rowh * 0.36, 16 * u,
                         ry + rowh * 0.36 + 3 * u], fill=col)
            d.text((21 * u, ry), clip(tn, ft, S - 29 * u), font=ft, fill=col)
        if total > 6:
            d.text((21 * u, y + rowh * rows + 1 * u),
                   '+%d more' % (total - 6), font=fl, fill=FAINT)
    else:
        msg = 'no texture refs in material'
        if tlen(msg, fl) > S - 30 * u:
            msg = 'no texture refs'
        d.text((13 * u, y + max(0.0, (avail - 10 * u) / 2)), msg, font=fl,
               fill=FAINT)

    badge(d, S, u, 'L2')
    footer(d, S, u, stem or ('unnamed #%d' % gid), '%d mbrs' % n)
    return im


# ---- L3 -----------------------------------------------------------------
def card_l3(S, u, gid, stem, rows, n, kind):
    roles = collections.Counter()
    for role, typ, name, h, props in rows:
        roles[ROLE_OF.get(role, 'SFX')] += 1
    role = max(ROLE_PRIORITY,
               key=lambda r: (roles.get(r, 0), -ROLE_PRIORITY.index(r)))
    if not any(roles.values()):
        role = 'SFX'
    col = ROLE_COL[role]

    im, d = frame(S)
    fl = getfont('mono', 7.5 * u)
    ft = getfont('mono', 9 * u)
    fk = getfont('sans', 9 * u)
    k = (kind or 'other').upper()
    d.text((8 * u, 8 * u), k, font=fk, fill=tuple(
        int(BG[i] + (col[i] - BG[i]) * 0.6) for i in range(3)))

    # member counts, dominant roles first
    cnt = collections.Counter(r[0] for r in rows)
    parts = ['%d %s' % (v, k2) for k2, v in
             sorted(cnt.items(), key=lambda kv: (-kv[1], kv[0]))][:3]
    line = '   '.join(parts) if parts else '0 members'
    line = clip(line, ft, S - 20 * u)
    sub = ''
    if not stem and rows:
        sub = 'hub %s' % rows[0][3]

    # centre the whole block in the free area so the card never looks bottom-heavy
    block = 30 * u + 11 * u + 12 * u + (9 * u if sub else 0) + 8 * u + 11 * u
    top, bottom = 24 * u, S - 32 * u
    y = top + max(0, (bottom - top - block) / 2)

    y = glyph_box(d, S, u, role, y) + 11 * u
    d.text(((S - tlen(line, ft)) / 2, y), line, font=ft, fill=DIM)
    y += 12 * u
    if sub:
        d.text(((S - tlen(sub, fl)) / 2, y), sub, font=fl, fill=FAINT)
        y += 9 * u
    y += 8 * u
    d.line([16 * u, y, S - 16 * u, y], fill=RULE, width=1)
    msg = 'no decodable texture, no material member'
    if tlen(msg, fl) > S - 24 * u:
        msg = 'no texture / no material'
    d.text(((S - tlen(msg, fl)) / 2, y + 5 * u), msg, font=fl, fill=FAINT)

    badge(d, S, u, 'L3')
    footer(d, S, u, stem or ('unnamed #%d' % gid), '%d mbrs' % n)
    return im


# --------------------------------------------------------------------- main
def atomic_save(im, path):
    tmp = '%s.tmp.%d' % (path, os.getpid())
    im.save(tmp, 'PNG', optimize=True)
    os.replace(tmp, path)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--limit', type=int, default=0, help='only the first N groups')
    ap.add_argument('--size', type=int, default=224, help='square card edge')
    ap.add_argument('--out', default='previews', help='output directory')
    ap.add_argument('--tsv', default=os.path.join('out', 'previews.tsv'))
    ap.add_argument('--report', default=os.path.join('out', 'preview_report.txt'))
    ap.add_argument('--quiet', action='store_true')
    args = ap.parse_args(argv)

    S = max(96, int(args.size))
    u = S / 224.0
    out = args.out if os.path.isabs(args.out) else os.path.join(HERE, args.out)
    tsv = args.tsv if os.path.isabs(args.tsv) else os.path.join(HERE, args.tsv)
    rep = args.report if os.path.isabs(args.report) else os.path.join(HERE, args.report)
    for p in (out, os.path.dirname(tsv), os.path.dirname(rep)):
        if p and not os.path.isdir(p):
            os.makedirs(p, exist_ok=True)

    t_all = time.time()
    t0 = time.time()
    con = sqlite3.connect('file:%s?mode=ro' % DB.replace('\\', '/'), uri=True)
    con.row_factory = None
    groups, members, texsize, names = load_plan(con)
    con.close()
    t_db = time.time() - t0

    t0 = time.time()
    payloads = explorer.payloads()
    t_payload = time.time() - t0

    todo = groups[:args.limit] if args.limit else groups
    existing = set()
    try:
        for fn in os.listdir(out):
            if fn.endswith('.png'):
                existing.add(fn[:-4])
    except Exception:
        pass

    t0 = time.time()
    t_render = t_decode = 0.0
    counts = collections.Counter()
    skipped = 0
    rows_out = []
    fails = []
    demoted = collections.Counter()
    examples = collections.defaultdict(list)
    n_done = 0

    for gid, stem, kind, n, n_mesh, n_mtl, n_ani, n_ske, n_tex, n_other in todo:
        lvl, extra = classify(gid, members, texsize)
        path = os.path.join(out, '%d.png' % gid)
        src = 'null'
        meta = {}

        if lvl == 'L1':
            # decode once here; card_l1 reuses the (hash,size) cache
            box = int(min(S - 16 * u, S - 60 * u))
            a = time.time()
            got = texture_png_bytes(extra['hash'], payloads, box, meta)
            t_decode += time.time() - a
            if got is None:
                # not actually decodable -> fall through the ladder
                lvl = 'L2' if any(r[0] == 'material'
                                  for r in (members.get(gid) or [])) else 'L3'
                demoted[meta.get('error') or '?'] += 1
            else:
                src = extra['hash']
        elif lvl == 'L2':
            # representative source: the material node the card is drawn from
            src = next((r[3] for r in extra['mtl'] if r[2]),
                       extra['mtl'][0][3])

        counts[lvl] += 1
        if len(examples[lvl]) < 5:
            examples[lvl].append(gid)

        if (os.path.basename(path)[:-4] in existing
                or os.path.exists(path)):
            rows_out.append((gid, lvl, path, src))
            skipped += 1
            n_done += 1
            continue

        a = time.time()
        try:
            if lvl == 'L1':
                im = card_l1(S, u, gid, stem, extra['hash'], payloads, meta, n)
                if im is None:
                    raise RuntimeError('texture vanished mid-run')
            elif lvl == 'L2':
                if extra.get('mtl'):
                    im = card_l2(S, u, gid, stem, extra['mtl'],
                                 names.get(gid) or [], n, kind)
                else:
                    im = card_l3(S, u, gid, stem, members.get(gid) or [], n, kind)
            else:
                im = card_l3(S, u, gid, stem, members.get(gid) or [], n, kind)
            atomic_save(im, path)
        except Exception as e:
            fails.append((gid, '%s: %s' % (type(e).__name__, e)))
            im = None
        t_render += time.time() - a
        rows_out.append((gid, lvl, path, src if im is not None else 'null'))
        n_done += 1
        if not args.quiet and n_done % 500 == 0:
            sys.stderr.write('\r  %d/%d  L1=%d L2=%d L3=%d  %.0fs'
                             % (n_done, len(todo), counts['L1'], counts['L2'],
                                counts['L3'], time.time() - t_all))
            sys.stderr.flush()

    total = time.time() - t_all
    with open(tsv, 'w', newline='') as fh:
        fh.write('gid\tlevel\tpath\tsource_hash_or_null\n')
        for gid, lvl, path, src in rows_out:
            fh.write('%d\t%s\t%s\t%s\n' % (gid, lvl, path.replace('\\', '/'), src))

    bytes_out = 0
    png_n = 0
    try:
        for fn in os.listdir(out):
            if fn.endswith('.png'):
                png_n += 1
                bytes_out += os.path.getsize(os.path.join(out, fn))
    except Exception:
        pass

    stages = [('db load (3 bulk queries)', t_db), ('payload index', t_payload),
              ('texture decode + checker', t_decode), ('card render + write', t_render)]
    slowest = max(stages, key=lambda s: s[1])
    lines = []
    lines.append('previewcard report -- %d cards planned, size %d, out %s'
                 % (len(rows_out), S, out.replace('\\', '/')))
    lines.append('wall clock total      : %.1f s' % total)
    lines.append('groups in this run    : %d (rendered %d, resumed/skipped %d)'
                 % (len(todo), len(todo) - skipped, skipped))
    lines.append('')
    lines.append('level distribution')
    plan_total = len(todo) or 1
    for lvl in ('L1', 'L2', 'L3'):
        lines.append('  %s  %6d  %5.1f%%   %s'
                     % (lvl, counts[lvl], 100.0 * counts[lvl] / plan_total,
                        {'L1': 'decodable texture member',
                         'L2': 'material member card',
                         'L3': 'role glyph placeholder'}[lvl]))
    lines.append('  --  %6d' % sum(counts.values()))
    if demoted:
        lines.append('  L1 demoted (texture member that failed to decode): %d  %s'
                     % (sum(demoted.values()), dict(demoted)))
    lines.append('')
    lines.append('disk')
    lines.append('  png files in out    : %d' % png_n)
    lines.append('  total bytes         : %d (%.1f MiB)'
                 % (bytes_out, bytes_out / 1048576.0))
    lines.append('  mean per card       : %.1f KiB'
                 % (bytes_out / max(1, png_n) / 1024.0))
    lines.append('')
    lines.append('stages')
    for nm, dt in stages:
        lines.append('  %-26s %7.2f s%s' % (nm, dt, '   <- slowest' if nm == slowest[0] else ''))
    lines.append('')
    lines.append('examples (gid per level)')
    for lvl in ('L1', 'L2', 'L3'):
        lines.append('  %s  %s' % (lvl, '  '.join(str(g) for g in examples[lvl])))
    lines.append('')
    lines.append('failures: %d' % len(fails))
    for gid, msg in fails[:10]:
        lines.append('  gid %d  %s' % (gid, msg))
    txt = '\n'.join(lines) + '\n'
    with open(rep, 'w') as fh:
        fh.write(txt)
    print(txt)
    return 0 if not fails else 1


if __name__ == '__main__':
    sys.exit(main())
