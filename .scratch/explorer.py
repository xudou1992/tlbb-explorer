"""TLBB Resource Explorer -- read-only browser over resources.db.

    python explorer.py [--port 8765]

Browse and search the 105k indexed assets by recovered path, content type and
provenance; inspect one asset together with its dependency edges; render JMT1
textures (DXT1 / DXT5 / RGBA) as PNG on demand.

Read-only: the database is opened with mode=ro and payloads come from the
already-extracted .scratch/out tree, never from the .pak files.
"""
import argparse
import io
import json
import os
import sqlite3
import struct
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, 'resources.db')
OUT_ALL = os.path.join(HERE, 'out', 'all')
PREV = os.path.join(HERE, 'previews')
VER = os.path.join(HERE, 'versions')
sys.path.insert(0, HERE)

_cache = {}


def payloads():
    if 'p' not in _cache:
        m = {}
        for pak in os.listdir(OUT_ALL):
            d = os.path.join(OUT_ALL, pak)
            if not os.path.isdir(d):
                continue
            for fn in os.listdir(d):
                if len(fn) >= 16:
                    m.setdefault(fn[:16], os.path.join(d, fn))
        _cache['p'] = m
    return _cache['p']


def db():
    con = sqlite3.connect('file:%s?mode=ro' % DB.replace('\\', '/'), uri=True)
    con.row_factory = sqlite3.Row
    return con


# ----------------------------------------------------------------- JMT1 codecs
def _rgb565(v):
    return (((v >> 11) & 31) * 255 + 15) // 31,            (((v >> 5) & 63) * 255 + 31) // 63,            ((v & 31) * 255 + 15) // 31, 255


def decode_block(b, codec):
    """One 4x4 block -> 16 (r,g,b,a) tuples, row-major inside the block."""
    if len(b) < (8 if codec == 'DXT1' else 16):
        return [(0, 0, 0, 0)] * 16
    c0, c1 = struct.unpack('<HH', b[4:8] if codec == 'DXT1' else b[8:12])
    a, c = _rgb565(c0), _rgb565(c1)
    if codec == 'DXT1':
        if c0 > c1:
            pal = [a, c, ((2 * a[0] + c[0]) // 3, (2 * a[1] + c[1]) // 3,
                          (2 * a[2] + c[2]) // 3, 255),
                   ((a[0] + 2 * c[0]) // 3, (a[1] + 2 * c[1]) // 3,
                    (a[2] + 2 * c[2]) // 3, 255)]
        else:
            pal = [a, c, ((a[0] + c[0]) // 2, (a[1] + c[1]) // 2,
                          (a[2] + c[2]) // 2, 255), (0, 0, 0, 0)]
        ci = int.from_bytes(b[4:8], 'little')
        ai, an = None, 0
    else:
        a0, a1 = b[0], b[1]
        al = [a0, a1]
        for i in range(2, 8):
            if a0 > a1:
                al.append(((8 - i) * a0 + (i - 1) * a1) // 7)
            elif i < 6:
                al.append(((6 - i) * a0 + (i - 1) * a1) // 5)
            else:
                al.append(0 if i == 6 else 255)
        pal = [a, c, ((2 * a[0] + c[0]) // 3, (2 * a[1] + c[1]) // 3,
                      (2 * a[2] + c[2]) // 3, 255),
               ((a[0] + 2 * c[0]) // 3, (a[1] + 2 * c[1]) // 3,
                (a[2] + 2 * c[2]) // 3, 255)]
        ci = int.from_bytes(b[12:16], 'little')
        ai, an = int.from_bytes(b[2:8], 'little'), 3
    out = []
    for k in range(16):
        r, g, bl, alpha = pal[(ci >> (2 * k)) & 3]
        if ai is not None:
            alpha = al[(ai >> (an * k)) & 7]
        out.append((r, g, bl, alpha))
    return out


def mip_chain(w, h, n, block):
    """Bytes occupied by `n` mips of a w x h texture with `block`-byte blocks."""
    return sum(((max(1, w >> i) + 3) // 4) * ((max(1, h >> i) + 3) // 4) * block
               for i in range(max(1, n)))


def decode_jmt1(raw):
    """JMT1 payload -> (PIL.Image RGBA, info).

    Layout: [24B header: 'JMT1' + 4CC + u32 marker + u32 payload + u16 w + u16 h + u32 mips]
    then one [u32 mip_size][mip data] per level. The 4CC is unreliable -- the engine tags
    BC3 payloads as "DXT1" -- so the block size is taken from the mip table.
    """
    from PIL import Image
    if raw[:4] != b'JMT1' or len(raw) < 28:
        return None, {'error': 'not a JMT1 payload'}
    tag = raw[4:8].decode('latin1', 'replace')
    w, h = struct.unpack_from('<HH', raw, 16)
    nmip = struct.unpack_from('<I', raw, 20)[0]
    declared = struct.unpack_from('<I', raw, 12)[0]
    info = {'declared_codec': tag, 'width': w, 'height': h, 'mips': nmip, 'declared': declared}
    if not 0 < w <= 8192 or not 0 < h <= 8192 or not 0 < nmip <= 16:
        return None, dict(info, error='implausible header')
    p, sizes = 24, []
    for _ in range(nmip):
        if p + 4 > len(raw):
            return None, dict(info, error='truncated mip table')
        sz = struct.unpack_from('<I', raw, p)[0]
        sizes.append(sz)
        p += 4 + sz
    info['mip_sizes'] = sizes
    if p - len(raw) > 64:
        return None, dict(info, error='mip table overruns payload')
    b0 = ((w + 3) // 4) * ((h + 3) // 4)
    if tag == 'COLW':
        # The engine hands these straight to a WebP demuxer; the bitstream is
        # (w+2)x(h+2), so the extra border is cropped from the bottom/right.
        import io
        try:
            im = Image.open(io.BytesIO(raw[28:28 + sizes[0]]))
            im.load()
        except Exception as e:
            return None, dict(info, error='webp: %s' % e)
        info['codec'] = 'WEBP'
        im = im.convert('RGBA')
        return im.crop((0, 0, min(w, im.width), min(h, im.height))), info
    if tag == 'COLR' and sizes[0] == (w + 2) * (h + 2) * 4:
        info['codec'] = 'RGBA32P'
        im = Image.frombytes('RGBA', (w + 2, h + 2), raw[28:28 + sizes[0]])
        return im.crop((0, 0, w, h)), info
    if sizes[0] == w * h * 4:
        codec, block = 'RGBA32', None
    elif sizes[0] == b0 * 16:
        codec, block = 'BC3', 16
    elif sizes[0] == b0 * 8:
        codec, block = 'BC1', 8
    else:
        return None, dict(info, error='unrecognised mip0 size %d' % sizes[0])
    info['codec'] = codec
    data = raw[28:28 + sizes[0]] if codec == 'RGBA32' else raw[28:28 + b0 * block]
    if len(data) < (w * h * 4 if codec == 'RGBA32' else b0 * block):
        return None, dict(info, error='truncated mip0')
    if codec == 'RGBA32':
        return Image.frombytes('RGBA', (w, h), data[:w * h * 4]), info
    px = bytearray(w * h * 4)
    bw, bh = (w + 3) // 4, (h + 3) // 4
    for by in range(bh):
        for bx in range(bw):
            off = (by * bw + bx) * block
            for k, (r, g, b2, a) in enumerate(decode_block(data[off:off + block],
                                                           'DXT5' if block == 16 else 'DXT1')):
                x, y = bx * 4 + (k % 4), by * 4 + (k // 4)
                if x < w and y < h:
                    o = (y * w + x) * 4
                    px[o:o + 4] = bytes((r, g, b2, a))
    return Image.frombytes('RGBA', (w, h), bytes(px)), info


def over_checker(img, size=192):
    from PIL import Image
    im = img.convert('RGBA')
    im.thumbnail((size, size), Image.NEAREST)
    bg = Image.new('RGBA', im.size, (24, 26, 30, 255))
    for y in range(0, im.size[1], 8):
        for x in range(0, im.size[0], 8):
            if (x // 8 + y // 8) % 2:
                for j in range(y, min(y + 8, im.size[1])):
                    for i in range(x, min(x + 8, im.size[0])):
                        bg.putpixel((i, j), (34, 37, 42, 255))
    bg.alpha_composite(im)
    out = io.BytesIO()
    bg.convert('RGB').save(out, 'PNG')
    return out.getvalue()


# ----------------------------------------------------------------- queries
FACET_COLS = {'type': 'type', 'ext': 'ext', 'src': 'src', 'pak': 'pak', 'codec': 'codec'}


def has(con, table):
    return bool(con.execute('SELECT 1 FROM sqlite_master WHERE type=? AND name=?',
                            ('table', table)).fetchone())


def q_list(qs):
    con = db()
    w, a = [], []
    if qs.get('q'):
        like = '%%%s%%' % qs['q'][0].replace('*', '%')
        w.append('(path LIKE ? OR name LIKE ? OR hash LIKE ?)')
        a += [like, like, like]
    for key, col in FACET_COLS.items():
        v = qs.get(key, [''])[0]
        if v:
            vals = [x for x in v.split(',') if x]
            w.append('%s IN (%s)' % (col, ','.join('?' * len(vals))))
            a += vals
    if qs.get('named', [''])[0]:
        w.append('named=1')
    if qs.get('unnamed', [''])[0]:
        w.append('named=0')
    where = ('WHERE ' + ' AND '.join(w)) if w else ''
    limit = min(int(qs.get('limit', ['200'])[0]), 2000)
    off = int(qs.get('offset', ['0'])[0])
    sort = {'size': 'original', 'path': 'path', 'type': 'type', 'count': 'original'}\
        .get(qs.get('sort', [''])[0], 'original')
    rows = con.execute('SELECT hash,path,name,dir,ext,type,subtype,codec,width,height,mips,'
                       'stored,original,flags,method,pak,gen,offset,src FROM resources '
                       '%s ORDER BY %s DESC LIMIT ? OFFSET ?' % (where, sort), a + [limit, off])
    total = con.execute('SELECT COUNT(*) c, SUM(original) b FROM resources %s' % where, a).fetchone()
    facets = {}
    for key, col in FACET_COLS.items():
        facets[key] = [[r[0], r[1]] for r in con.execute(
            'SELECT %s, COUNT(*) FROM resources WHERE %s IS NOT NULL AND %s != "" '
            'GROUP BY %s ORDER BY 2 DESC LIMIT 24' % (col, col, col, col))]
    return {'total': total['c'], 'bytes': total['b'], 'rows': [dict(r) for r in rows],
            'facets': facets, 'offset': off, 'limit': limit}


def q_search(q):
    """One box, three kinds of answer: assets, files, and referenced-but-missing names.

    Chinese queries work too: the label tables are searched in reverse, so 宠物 finds
    the tag `pet` and 地图道具 finds kind `map-prop`.
    """
    con = db()
    q = (q or '').strip()
    if not q:
        return {'error': 'empty'}
    like = '%' + q.replace('*', '%') + '%'
    codes = sorted({k for g in LABELS.values() for k, v in g.items() if v == q})
    sql = ('SELECT g.*, (SELECT group_concat(t.tag, ",") FROM asset_tags t WHERE t.gid = g.id) '
           'tags FROM agroups g WHERE g.stem LIKE ? OR g.dir LIKE ?')
    args = [like, like]
    if has(con, 'asset_tags'):
        sql += ' OR g.id IN (SELECT gid FROM asset_tags WHERE tag IN (%s))' % ','.join('?' * (len(codes) or 1))
        args += codes or ['__none__']
    assets = [dict(r) for r in con.execute(sql + ' LIMIT 25', args)]
    files = [dict(r) for r in con.execute(
        'SELECT hash, name, path, type, ext, original, codec, width, height, named '
        'FROM resources WHERE name LIKE ? OR path LIKE ? ORDER BY original DESC LIMIT 25',
        (like, like))]
    names = [dict(r) for r in con.execute(
        'SELECT name, ext, n_refs, n_src, cls FROM dangling WHERE name LIKE ? '
        'ORDER BY n_src DESC LIMIT 25', (like,))]
    return {'q': q, 'assets': assets, 'files': files, 'names': names}


def q_versions():
    """What a comparison can be run against: the built snapshot plus dropped-in ones."""
    con = db()
    base = os.path.join(HERE, 'out', 'versionA.json')
    out = {'have_base': os.path.isfile(base),
           'base_mtime': int(os.path.getmtime(base)) if os.path.isfile(base) else None,
           'others': sorted(os.listdir(VER)) if os.path.isdir(VER) else [],
           'assets': con.execute('SELECT COUNT(*) FROM asset_identity').fetchone()[0]
           if has(con, 'asset_identity') else 0,
           'distinct': con.execute('SELECT COUNT(DISTINCT id_asset) FROM asset_identity').fetchone()[0]
           if has(con, 'asset_identity') else 0}
    out['others'] = [f for f in out['others'] if f.endswith('.json')]
    return out


def q_diff(name):
    import identity
    safe = os.path.basename(name or '')
    if not safe.endswith('.json'):
        return {'error': '只能比较 versions 目录里的 .json 快照'}
    p = os.path.join(VER, safe)
    if not os.path.isfile(p):
        return {'error': '找不到快照 ' + safe}
    a = identity.load(os.path.join(HERE, 'out', 'versionA.json'))
    counts, lines = identity.compare(a, identity.load(p))
    return {'with': safe, 'summary': sorted(counts.items(), key=lambda kv: -kv[1]),
            'lines': [{'name': r[0], 'kind': r[1], 'verdict': r[2], 'detail': r[3]}
                      for r in lines[:400]]}


def q_summary():
    """Landing page numbers: what the client actually contains, in plain terms."""
    con = db()
    one = lambda s: con.execute(s).fetchone()[0]
    out = {
        'files': one('SELECT COUNT(*) FROM resources'),
        'bytes': one('SELECT SUM(original) FROM resources'),
        'named': one('SELECT COUNT(*) FROM resources WHERE named=1'),
        'assets': one('SELECT COUNT(*) FROM agroups'),
        'members': one('SELECT SUM(n) FROM agroups'),
        'edges': one('SELECT COUNT(*) FROM relations'),
        'names': one('SELECT COUNT(*) FROM dangling'),
        'paks': one('SELECT COUNT(DISTINCT pak) FROM records'),
        'by_kind': [[r[0], r[1]] for r in con.execute(
            'SELECT kind, COUNT(*) FROM agroups GROUP BY 1 ORDER BY 2 DESC')],
        'by_type': [[r[0], r[1]] for r in con.execute(
            'SELECT type, COUNT(*) FROM resources GROUP BY 1 ORDER BY 2 DESC LIMIT 14')],
        'tex_state': [['完整', one('SELECT COUNT(*) FROM agroups WHERE n_tex>0')],
                      ['贴图未定位', one('SELECT COUNT(*) FROM agroups WHERE n_tex=0 AND names>0')],
                      ['仅文件', one('SELECT COUNT(*) FROM agroups WHERE n_tex=0 AND names=0')]],
        'name_state': [['私人资源', one("SELECT COUNT(*) FROM dangling WHERE cls='unique'")],
                       ['公共资源', one("SELECT COUNT(*) FROM dangling WHERE cls='shared'")]],
    }
    if has(con, 'asset_tags'):
        out['by_tag'] = [[r[0], r[1]] for r in con.execute(
            'SELECT tag, COUNT(*) FROM asset_tags GROUP BY 1 ORDER BY 2 DESC LIMIT 14')]
    if has(con, 'asset_identity'):
        r = con.execute('SELECT COUNT(*), COUNT(DISTINCT id_asset) FROM asset_identity').fetchone()
        out['dup_assets'] = r[0] - r[1]
        out['blobs'] = con.execute('SELECT COUNT(*), SUM(size) FROM blobs').fetchone()[0]
    return out


def q_groups(qs):
    """Asset view: one row per character / prop / effect, not per file."""
    con = db()
    w, a = [], []
    if qs.get('q'):
        like = '%%%s%%' % qs['q'][0].replace('*', '%')
        w.append('(hub_path LIKE ? OR stem LIKE ? OR dir LIKE ?)')
        a += [like, like, like]
    v = qs.get('kind', [''])[0]
    if v:
        vals = [x for x in v.split(',') if x]
        w.append('kind IN (%s)' % ','.join('?' * len(vals)))
        a += vals
    if qs.get('withnames', [''])[0]:
        w.append('names>0')
    if qs.get('tag', [''])[0]:
        w.append('id IN (SELECT gid FROM asset_tags WHERE tag=?)')
        a.append(qs['tag'][0])
    where = ('WHERE ' + ' AND '.join(w)) if w else ''
    limit = min(int(qs.get('limit', ['100'])[0]), 1000)
    off = int(qs.get('offset', ['0'])[0])
    tg = has(con, 'asset_tags')
    rows = [dict(r) for r in con.execute(
        'SELECT * FROM agroups %s ORDER BY n DESC, names DESC LIMIT ? OFFSET ?' % where,
        a + [limit, off])]
    if tg:
        for d in rows:
            d['tags'] = [r[0] for r in con.execute(
                'SELECT tag FROM asset_tags WHERE gid=? ORDER BY confidence, tag', (d['id'],))]
    for d in rows:
        t = con.execute('SELECT m.hash FROM amembers m JOIN resources x ON x.hash=m.hash '
                        'WHERE m.gid=? AND x.type=? ORDER BY x.original DESC LIMIT 1',
                        (d['id'], 'texture')).fetchone()
        d['thumb'] = t[0] if t else None
    tot = con.execute('SELECT COUNT(*) c, SUM(n) b FROM agroups %s' % where, a).fetchone()
    kinds = [[r[0], r[1]] for r in con.execute(
        'SELECT kind, COUNT(*) FROM agroups GROUP BY kind ORDER BY 2 DESC')]
    tagl = [[r[0], r[1]] for r in con.execute(
        'SELECT tag, COUNT(*) FROM asset_tags GROUP BY 1 ORDER BY 2 DESC')] if tg else []
    return {'total': tot['c'], 'members': tot['b'], 'rows': rows, 'kinds': kinds,
            'taglist': tagl, 'offset': off, 'limit': limit}


def q_group(gid):
    con = db()
    g = con.execute('SELECT * FROM agroups WHERE id=?', (gid,)).fetchone()
    if not g:
        return {'error': 'no such group'}
    mem = [dict(r) for r in con.execute(
        'SELECT m.role, x.hash, x.path, x.name, x.ext, x.type, x.codec, x.width, x.height, '
        'x.original, x.named, x.src FROM amembers m JOIN resources x ON x.hash=m.hash '
        'WHERE m.gid=? ORDER BY m.role, x.path', (gid,))]
    names = [dict(r) for r in con.execute(
        'SELECT name, cls FROM agroup_names WHERE gid=? ORDER BY cls, name', (gid,))]
    # graph: members plus the unresolved names they import, wired by real edges only
    nodes, edges = [], []
    for m in mem:
        nodes.append({'id': m['hash'], 'label': m['name'] or m['hash'], 'role': m['role'],
                      'size': m['original']})
    for n in names[:60]:
        nodes.append({'id': 'n:' + n['name'], 'label': n['name'], 'role': 'texture',
                      'dangling': 1, 'cls': n['cls']})
    have = {n['id'] for n in nodes}
    for f, t, rel in con.execute(
            'SELECT r.from_hash, r.to_hash, r.rel FROM relations r '
            'JOIN amembers a ON a.hash=r.from_hash AND a.gid=? '
            'JOIN amembers b ON b.hash=r.to_hash AND b.gid=?', (gid, gid)):
        if f in have and t in have:
            edges.append({'from': f, 'to': t, 'rel': rel})
    for f, nm in con.execute(
            'SELECT r.from_hash, r.name FROM refs r JOIN amembers a ON a.hash=r.from_hash '
            "WHERE a.gid=? AND r.to_hash IS NULL AND r.kind IN ('.tga','.dds','.png')", (gid,)):
        if 'n:' + nm in have:
            edges.append({'from': f, 'to': 'n:' + nm, 'rel': 'name'})
    tags = fp = dup = 0
    if has(con, 'asset_tags'):
        tags = [r[0] for r in con.execute(
            'SELECT tag FROM asset_tags WHERE gid=? ORDER BY confidence, tag', (gid,))]
    if has(con, 'asset_identity'):
        fp = con.execute('SELECT * FROM asset_identity WHERE gid=?', (gid,)).fetchone()
        fp = dict(fp) if fp else None
        if fp:
            dup = con.execute('SELECT COUNT(*)-1 FROM asset_identity WHERE id_asset=?',
                              (fp['id_asset'],)).fetchone()[0]
    elif has(con, 'asset_fingerprint'):
        fp = con.execute('SELECT * FROM asset_fingerprint WHERE gid=?', (gid,)).fetchone()
        fp = dict(fp) if fp else None
    return {'group': dict(g), 'members': mem, 'names': names, 'nodes': nodes,
            'edges': edges, 'tags': tags or [], 'fp': fp, 'dup': dup}


def q_asset(h):
    con = db()
    r = con.execute('SELECT * FROM resources WHERE hash=?', (h,)).fetchone()
    if not r:
        return {'error': 'no such hash'}
    out_edges = [dict(x) for x in con.execute(
        'SELECT r.rel, r.to_hash AS hash, b.name, b.path, b.type, b.original FROM relations r '
        'JOIN resources b ON b.hash=r.to_hash WHERE r.from_hash=? LIMIT 60', (h,))]
    in_edges = [dict(x) for x in con.execute(
        'SELECT r.rel, r.from_hash AS hash, b.name, b.path, b.type, b.original FROM relations r '
        'JOIN resources b ON b.hash=r.from_hash WHERE r.to_hash=? LIMIT 60', (h,))]
    refs = [dict(x) for x in con.execute(
        'SELECT name, kind, to_hash FROM refs WHERE from_hash=? ORDER BY kind, name LIMIT 120',
        (h,))]
    usedby = [dict(x) for x in con.execute(
        'SELECT r.kind AS rel, r.from_hash AS hash, b.path, b.type, b.original FROM refs r '
        'JOIN resources b ON b.hash=r.from_hash WHERE r.to_hash=? LIMIT 60', (h,))]
    return {'asset': dict(r), 'out': out_edges, 'in': in_edges, 'refs': refs,
            'usedby': usedby}


def read_payload(h):
    p = payloads().get(h)
    return open(p, 'rb').read() if p and os.path.isfile(p) else None


# ----------------------------------------------------------------- page
LABELS = {'kind': {'player': '玩家角色', 'npc': 'NPC', 'monster': '怪物', 'pet': '宠物', 'weapon': '武器', 'mount': '坐骑', 'accessory': '挂件', 'effect': '特效', 'skill-effect': '技能特效', 'scene-effect': '场景特效', 'building': '建筑', 'tileset': '地图块', 'map-prop': '地图道具', 'item-icon': '图标', 'ui': '游戏界面', 'shared-material': '公共材质', 'mask': '遮罩', 'texture-atlas': '贴图集', 'animation-set': '动作集', 'audio': '声音', 'table/config': '表格配置', 'scene': '场景', 'tani': '动作数据', 'source': '原始素材', 'data': '数据文件', 'map': '地图', 'other': '其他', 'unknown': '未分类'}, 'role': {'model': '模型', 'skeleton': '骨骼', 'mesh': '子模型', 'material': '材质', 'animation': '动作', 'texture': '贴图', 'scene': '场景', 'effect': '特效', 'map': '地图块', 'set': '集合', 'audio': '声音', 'table': '表格', 'config': '配置', 'other': '其他'}, 'type': {'texture': '贴图', 'ani': '动作', 'JBCF': '配置容器', 'geom': '几何数据', 'scene': '场景', 'mesh': '模型网格', 'JBPU': '粒子特效', 'binary': '未知二进制', 'GATA': '资源包', 'tiny': '小文件', 'mapref': '地图引用', 'text': '文本', 'xml': '配置表', 'NAVF': '导航数据', 'set': '动作集', 'wav': '声音', 'ogg': '声音', 'mp3': '声音', 'webp': '图片', 'jpeg': '图片', 'png': '图片', 'table': '表格', 'missing': '读不到', 'empty': '空文件', 'pe': '程序模块', 'JLUA': '脚本', 'JMDL': '模型', 'JSTR': '文字'}, 'src': {'manifest': '包里自带名字', 'self': '文件里写着自己名字', 'resourcepath': '官方路径表', 'mined': '推导恢复'}, 'codec': {'RGBA32': '普通彩色图', 'BC3': '压缩贴图（带透明）', 'BC1': '压缩贴图', 'WEBP': '网页图片', 'RGBA32P': '普通彩色图（带边距）'}, 'tag': {'boss': 'Boss', 'npc': 'NPC', 'monster': '怪物', 'pet': '宠物', 'weapon': '武器', 'mount': '坐骑', 'accessory': '挂件', 'effect': '特效', 'skill-effect': '技能特效', 'scene-effect': '场景特效', 'building': '建筑', 'tileset': '地图块', 'map-props': '地图道具', 'item-icon': '图标', 'ui': '界面', 'shared-material': '公共材质', 'mask': '遮罩', 'texture-atlas': '贴图集', 'animation-set': '动作集', 'audio': '声音', 'table/config': '表格配置', 'player-part': '身体部件', 'player-male': '男性角色', 'player-female': '女性角色', 'unknown': '未分类'}}


HTML = r'''<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>天龙资源浏览器</title><style>
:root{--bg:#12141a;--fg:#dfe3ea;--dim:#8b93a3;--line:#242833;--acc:#5cc8ff;--chip:#1c2230}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:13px/1.5 ui-monospace,Sarasa Mono SC,Consolas,monospace}
header{position:sticky;top:0;background:#171a21;border-bottom:1px solid var(--line);
padding:10px 16px;display:flex;gap:10px;flex-wrap:wrap;align-items:center;z-index:5}
.brand{display:flex;flex-direction:column;margin-right:6px}
.brand b{font-size:14px}.brand i{font-style:normal;font-size:10px;color:var(--dim)}
.tiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:12px;margin:12px 0}
.tile{border:1px solid var(--line);border-radius:10px;padding:14px 16px;background:#161922;cursor:pointer}
.tile:hover{border-color:var(--acc)}
.tile b{font-size:22px;display:block;color:var(--acc);font-weight:600}
.tile span{color:var(--dim);font-size:12px}
.sec{margin:24px 0 8px;color:var(--dim);font-size:12px;letter-spacing:.06em}
.bar{display:flex;justify-content:space-between;gap:10px;padding:5px 10px;border:1px solid var(--line);
border-radius:7px;background:#161922;cursor:pointer;margin-bottom:4px}
.bar:hover{border-color:var(--acc)}
.bar i{color:var(--dim);font-style:normal}
.bar em{background:#22314a;border-radius:4px;height:8px;flex:1;position:relative;margin:0 8px;display:inline-block}
.bar em b{position:absolute;inset:0 auto 0 0;background:var(--acc);border-radius:4px;display:block}
.row{display:flex;gap:10px;align-items:center;padding:7px 10px;border:1px solid var(--line);
border-radius:8px;background:#161922;cursor:pointer;margin-bottom:5px}
.row:hover{border-color:var(--acc)}.row img{border-radius:5px;object-fit:cover;background:#12141a}
.mut{color:var(--dim);font-size:11px}
input,select{background:var(--chip);color:var(--fg);border:1px solid var(--line);
border-radius:6px;padding:6px 9px;font:inherit;outline:none}
input:focus,select:focus{border-color:var(--acc)}
#q{min-width:340px}main{display:flex;gap:16px;padding:16px;align-items:flex-start}
aside{width:212px;flex:none}aside h4{margin:14px 0 6px;color:var(--dim);font-size:11px;
text-transform:uppercase;letter-spacing:.08em}
.fac{max-height:230px;overflow:auto;border:1px solid var(--line);border-radius:8px}
.fac div{padding:3px 8px;cursor:pointer;display:flex;justify-content:space-between;gap:8px}
.fac div:hover{background:var(--chip)}.fac div.on{background:#20304a;color:var(--acc)}
.fac span{color:var(--dim)}
section{flex:1;min-width:0}
#grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px}
.card{border:1px solid var(--line);border-radius:8px;overflow:hidden;cursor:pointer;background:#161922}
.card.sel{border-color:var(--acc)}
.card img{width:100%;height:110px;object-fit:contain;display:block;background:#0d0f14}
.card .ph{width:100%;height:110px;display:flex;align-items:center;justify-content:center;
color:#3b4150;font-size:11px;letter-spacing:.1em}
.card .t{padding:6px 8px;font-size:11px;word-break:break-all}
.card .m{color:var(--dim);font-size:10px;padding:0 8px 6px}
#tbl{width:100%;border-collapse:collapse}#tbl td{padding:4px 8px;border-bottom:1px solid var(--line);
white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:520px}
#tbl tr:hover{background:#1a1f2b;cursor:pointer}
#detail{position:fixed;right:0;top:0;height:100%;width:min(560px,92vw);background:#141821;
border-left:1px solid var(--line);box-shadow:-18px 0 40px #0009;transform:translateX(100%);
transition:transform .18s ease;overflow:auto;padding:18px;z-index:9}
#detail.open{transform:none}
#detail h3{margin:0 0 4px;font-size:13px;word-break:break-all}
.kv{display:grid;grid-template-columns:104px 1fr;gap:2px 10px;margin:12px 0;font-size:12px}
.kv b{color:var(--dim);font-weight:400}
.tag{display:inline-block;background:var(--chip);border:1px solid var(--line);border-radius:20px;
padding:1px 8px;font-size:11px;margin-right:5px}
.rel a{color:var(--acc);cursor:pointer;text-decoration:none;display:block;padding:2px 0;
white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#bar{display:flex;gap:10px;align-items:center;color:var(--dim);margin:0 0 10px}
button{background:var(--chip);color:var(--fg);border:1px solid var(--line);border-radius:6px;
padding:5px 10px;font:inherit;cursor:pointer}button:hover{border-color:var(--acc)}
.x{float:right;color:var(--dim);cursor:pointer}
</style></head><body>
<header>
 <div class=brand><b>天龙资源浏览器</b><i>天龙八部客户端资源分析工具</i></div>
 <input id="q" placeholder="搜索角色、装备、地图、文件名…" autofocus>
 <select id="view"><option value="home">总览</option><option value="asset">资源库</option>
   <option value="res">全部文件</option><option value="ver">版本比较</option></select>
 <select id="vsel" style="display:none"><option value="">选择要比较的客户端快照…</option></select>
 <select id="kind" style="display:none"><option value="">全部分类</option></select>
 <select id="tag" style="display:none"><option value="">全部标签</option></select>
 <select id="type" style="display:none"><option value="">全部类型</option></select>
 <select id="src" style="display:none"><option value="">命名情况</option></select>
 <select id="named" style="display:none"><option value="">全部</option>
   <option value="1">已有名字</option><option value="0">只有编号</option></select>
 <label id="wn" style="display:none;color:var(--dim);font-size:12px"><input type="checkbox" id="withnames">只看带贴图名的</label>
 <select id="mode" style="display:none"><option value="grid">图片墙</option><option value="table">列表</option></select>
 <button id="go">查找</button>
 <span id="stat" style="color:var(--dim)"></span>
</header>
<main><aside id="facets"></aside><section>
 <div id="bar"><button id="more" style="display:none">加载更多</button></div>
 <div id="grid"></div><table id="tbl" style="display:none"></table>
</section></main>
<div id="detail"></div>
<script>
let st={q:'',type:'',ext:'',src:'',named:'',kind:'',tag:'',withnames:'',view:'home',offset:0,limit:200,rows:[],total:0,tiles:{}};
const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
const fmt=n=>n==null?'-':(n>=1e9?(n/1e9).toFixed(2)+' GB':n>=1e6?(n/1e6).toFixed(2)+' MB':
  n>=1e3?(n/1e3).toFixed(1)+' KB':n+' 字节');
const num=n=>(n==null?0:n).toLocaleString()+' 个';
const ZK=__ZK__;
const zh=(g,k)=>(ZK[g]||{})[k]||k||'—';
const DECC=['BC1','BC3','RGBA32','WEBP','RGBA32P'];
// w1351_ is an internal project prefix; drop it so names read cleanly.
const nice=s=>String(s==null?'':s).replace(/^w1351_/,'')||'';
const state=a=>a.n_tex>0?'贴图已就位':(a.names>0?'贴图未定位':(a.n_mtl>0?'仅材质':'仅文件'));
function url(){const p=new URLSearchParams();
 if(st.view==='asset'){
  if(st.q)p.set('q',st.q);if(st.kind)p.set('kind',st.kind);if(st.tag)p.set('tag',st.tag);
  if(st.withnames)p.set('withnames','1');
  p.set('offset',st.offset);p.set('limit',st.limit);return '/api/groups?'+p}
 for(const k of ['q','type','ext','src','codec','pak','named']) if(st[k]) p.set(k,st[k]);
 p.set('offset',st.offset);p.set('limit',st.limit);return '/api/list?'+p}
async function load(append){
 if(st.view==='home')return st.q?search():home();
 if(st.view==='ver')return versions();
 $('#mode').style.display='';
 const r=await fetch(url());const d=await r.json();
 st.total=d.total;st.rows=append?st.rows.concat(d.rows):d.rows;
 $('#stat').textContent=st.view==='asset'
   ? '共 '+d.total.toLocaleString()+' 项资源 · 由 '+d.members.toLocaleString()+' 个文件组成'
   : d.total.toLocaleString()+' 个文件 · '+fmt(d.bytes);
 if(st.view==='asset') buildKinds(d); else buildFacets(d.facets);
 render();$('#more').style.display=st.rows.length<st.total?'block':'none'}
async function home(){
 const d=await (await fetch('/api/summary')).json();
 $('#stat').textContent='';$('#facets').innerHTML='';$('#more').style.display='none';
 $('#mode').style.display='none';
 $('#grid').style.display='none';const t=$('#tbl');t.style.display='block';
 t.innerHTML=`<div class=sec>资源库总览</div>
 <div class=tiles>
  <div class=tile data-v=asset><b>${d.assets.toLocaleString()}</b><span>项资源（角色 / 装备 / 地图…）</span></div>
  <div class=tile data-v=res><b>${d.files.toLocaleString()}</b><span>个文件 · ${fmt(d.bytes)}</span></div>
  <div class=tile data-v=res><b>${(100*d.named/d.files).toFixed(1)}%</b><span>文件已还原出名字（${d.named.toLocaleString()}）</span></div>
  <div class=tile data-v=asset><b>${d.edges.toLocaleString()}</b><span>条引用关系</span></div>
  ${d.dup_assets?`<div class=tile data-v=ver><b>${d.dup_assets.toLocaleString()}</b><span>项资源与其他资源内容完全相同</span></div>`:''}
 </div>
 <div class=sec>按分类浏览</div>
 ${d.by_kind.map(([k,n])=>`<div class=bar data-kind="${esc(k)}"><span>${esc(zh('kind',k))}</span>
   <em><b style="width:${Math.max(1,100*n/d.by_kind[0][1])}%"></b></em><i>${n.toLocaleString()}</i></div>`).join('')}
 <div class=sec>贴图定位情况（贴图都在包里，只是没有名字可对）</div>
 ${d.tex_state.map(([k,n])=>`<div class=bar><span>${esc(k)}</span>
   <em><b style="width:${Math.max(1,100*n/d.assets)}%"></b></em><i>${n.toLocaleString()}</i></div>`).join('')}
 <div class=sec>未找到对应文件的资源名</div>
 ${d.name_state.map(([k,n])=>`<div class=bar><span>${esc(k)}${k==='私人资源'?'（只有一个资源用到）':'（多个资源共用）'}</span>
   <em><b style="width:${Math.max(1,100*n/d.names)}%"></b></em><i>${n.toLocaleString()}</i></div>`).join('')}
 ${(d.by_tag||[]).length?`<div class=sec>自动分类标签</div>
 ${d.by_tag.map(([k,n])=>`<div class=bar data-tag="${esc(k)}"><span>${esc(zh('tag',k))}</span>
   <em><b style="width:${Math.max(1,100*n/d.by_tag[0][1])}%"></b></em><i>${n.toLocaleString()}</i></div>`).join('')}`:''}
 <div class=sec>文件类型</div>
 ${d.by_type.map(([k,n])=>`<div class=bar data-type="${esc(k)}"><span>${esc(zh('type',k))}</span>
   <em><b style="width:${Math.max(1,100*n/d.by_type[0][1])}%"></b></em><i>${n.toLocaleString()}</i></div>`).join('')}`;
 $$('div.tile').forEach(el=>el.onclick=()=>{$('#view').value=el.dataset.v;$('#view').onchange()});
 $$('div.bar[data-kind]').forEach(el=>el.onclick=()=>{$('#view').value='asset';$('#view').onchange();
   st.kind=el.dataset.kind;$('#kind').value=st.kind;load()});
 $$('div.bar[data-tag]').forEach(el=>el.onclick=()=>{$('#view').value='asset';$('#view').onchange();
   st.tag=el.dataset.tag;$('#tag').value=st.tag;load()});
 $$('div.bar[data-type]').forEach(el=>el.onclick=()=>{$('#view').value='res';$('#view').onchange();
   st.type=el.dataset.type;$('#type').value=st.type;load()})}
async function versions(){
 const v=await (await fetch('/api/versions')).json();
 $('#facets').innerHTML='';$('#mode').style.display='none';$('#more').style.display='none';
 $('#grid').style.display='none';const t=$('#tbl');t.style.display='block';
 const sel=$('#vsel');sel.style.display=v.others.length?'':'none';
 sel.innerHTML='<option value="">选择要比较的客户端快照…</option>'+
  v.others.map(f=>`<option value="${esc(f)}">${esc(f)}</option>`).join('');
 if(!v.have_base){$('#stat').textContent='还没有当前版本快照';
  t.innerHTML='<div style="color:var(--dim);padding:20px">先在命令行运行 <code>python identity.py</code> 生成当前客户端的快照（out/versionA.json），再把别的版本快照放进 versions 目录。';return}
 $('#stat').textContent='当前版本：'+v.assets.toLocaleString()+' 项资源 · 身份证 '+v.distinct.toLocaleString()+' 种';
 if(!v.others.length){t.innerHTML=`<div class=sec>当前版本</div>
  <div style="color:var(--dim);padding:6px 0">${v.assets.toLocaleString()} 项资源已生成身份证；其中 ${v.distinct.toLocaleString()} 种身份证互不相同${v.assets!==v.distinct?'（有 '+(v.assets-v.distinct)+' 项资源内容完全相同，属于重复资产）':''}。</div>
  <div class=sec>怎么比较别的版本</div>
  <div style="color:var(--dim);padding:6px 0;max-width:760px">把另一份客户端（经典版 / 2025 版 / 怀旧版）解包后，在同一台机器上运行 <code>python identity.py --snapshot out/versionB.json</code>，再把生成的 JSON 放进 <code>versions</code> 目录，这里就会出现可选的对比项。</div>`;return}
 if(!sel.value){t.innerHTML='<div class=sec>当前版本</div><div style="color:var(--dim);padding:6px 0">'+
   v.assets.toLocaleString()+' 项资源已生成身份证，其中 '+(v.assets-v.distinct).toLocaleString()+
   ' 项与其他资源内容完全相同。选择右上角的快照即可开始比较。</div>';return}
 diff(sel.value)}
async function diff(name){
 const d=await (await fetch('/api/diff?with='+encodeURIComponent(name))).json();
 const t=$('#tbl');
 if(d.error){t.innerHTML='<div style="color:#f7768e;padding:16px">'+esc(d.error)+'</div>';return}
 $('#stat').textContent='与 '+d.with+' 比较：'+d.summary.map(([k,n])=>k+' '+n).join(' · ');
 t.innerHTML='<div class=sec>差异汇总</div>'+d.summary.map(([k,n])=>
  `<div class=bar><span>${esc(k)}</span><em><b style="width:${Math.max(1,100*n/d.lines.length)}%"></b></em><i>${n.toLocaleString()}</i></div>`).join('')+
  '<div class=sec>明细（最多 400 条）</div>'+
  d.lines.map(r=>`<div class=row><div><b>${esc(nice(r.name)||'未命名资源')}</b> <span class=mut>${esc(zh('kind',r.kind))}</span><div class=mut>${esc(r.detail)}</div></div></div>`).join('')}
function buildKinds(d){const k=d.kinds||[];
 $('#facets').innerHTML='<h4>资源分类</h4><div class=fac data=kind>'+
  k.map(([n,c])=>`<div data-v="${esc(n)}" class="${st.kind===n?'on':''}">
   <span>${esc(zh('kind',n))}</span><span>${c.toLocaleString()}</span></div>`).join('')+'</div>'+
  ((d.taglist||[]).length?`<h4>分类标签</h4><div class=fac data=tag>`+
    d.taglist.map(([n,c])=>`<div data-v="${esc(n)}" class="${st.tag===n?'on':''}">
    <span>${esc(zh('tag',n))}</span><span>${c.toLocaleString()}</span></div>`).join('')+'</div>':'');
 $$('.fac div').forEach(el=>el.onclick=()=>{const key=el.parentElement.dataset.k;
   st[key]=st[key]===el.dataset.v?'':el.dataset.v;st.offset=0;load()});
 const sel=$('#kind');const keep=sel.value;
 sel.innerHTML='<option value="">全部分类</option>'+
  (k||[]).map(([n,c])=>`<option value="${esc(n)}" ${n===keep?'selected':''}>${esc(n)} (${c})</option>`).join('');
 const ts=$('#tag'),tk=ts.value;
 ts.innerHTML='<option value="">全部标签</option>'+
  (d.taglist||[]).map(([n,c])=>`<option value="${esc(n)}" ${n===tk?'selected':''}>${esc(n)} (${c})</option>`).join('')}
function buildFacets(f){
 const lab={type:'文件类型',ext:'文件后缀',src:'名字来源',codec:'图片格式',pak:'所在资源包'};
 $('#facets').innerHTML=Object.entries(f).map(([k,v])=>
  `<h4>${lab[k]||k}</h4><div class=fac data=k=${k}>`+
  v.filter(x=>x[0]).map(([n,c])=>`<div data-v="${esc(n)}" class="${st[k]===n?'on':''}">
   <span style="color:inherit;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(k==='type'?zh('type',n):(k==='src'?zh('src',n):(k==='codec'?zh('codec',n):n)))}</span>
   <span>${c.toLocaleString()}</span></div>`).join('')+'</div>').join('');
 $$('.fac div').forEach(el=>el.onclick=()=>{const k=el.parentElement.dataset.k;
   st[k]=st[k]===el.dataset.v?'':el.dataset.v;st.offset=0;load()});
 for(const k of ['type','src']){const sel=$('#'+k);const keep=sel.value;
   sel.innerHTML=`<option value="">全部${k==='type'?'文件类型':'名字来源'}</option>`+
    (f[k]||[]).filter(x=>x[0]).map(([n,c])=>`<option value="${esc(n)}" ${n===keep?'selected':''}>${esc(k==='type'?zh('type',n):zh('src',n))} (${c})</option>`).join('')}}
function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
async function search(){
 const d=await (await fetch('/api/search?q='+encodeURIComponent(st.q))).json();
 $('#facets').innerHTML='';$('#more').style.display='none';$('#mode').style.display='none';
 $('#grid').style.display='none';const t=$('#tbl');t.style.display='block';
 const n=d.assets.length+d.files.length+d.names.length;
 $('#stat').textContent='“'+d.q+'” 共找到 '+n+' 项';
 let h='';
 if(!n)h='<div style="color:var(--dim);padding:20px">没有找到相关资源。可以试试名字的一部分，或英文拼音（例如 caoshuang）、分类词（例如 宠物）。</div>';
 if(d.assets.length)h+='<div class=sec>资源 '+d.assets.length+' 项</div>'+d.assets.map(a=>
   `<div class=row data-g=${a.id}><img src="/api/preview/${a.id}.png" width=42 height=42 onerror="this.style.visibility='hidden'">
    <div><b>${esc(nice(a.stem)||('未命名 '+a.id))}</b><div class=mut>${esc(zh('kind',a.kind))} · ${a.n} 个文件 · ${esc(state(a))}</div></div></div>`).join('');
 if(d.files.length)h+='<div class=sec>文件 '+d.files.length+' 个</div>'+d.files.map(f=>
   `<div class=row data-h=${f.hash}><div><b>${esc(f.name||'未命名文件')}</b>
    <div class=mut>${esc(zh('type',f.type))} · ${fmt(f.original)} · ${esc(f.path||'')}</div></div></div>`).join('');
 if(d.names.length)h+='<div class=sec>引用了但没找到对应文件 · '+d.names.length+' 个名字</div>'+d.names.map(x=>
   `<div class=row><div><b>${esc(x.name)}</b><div class=mut>${x.n_src>1?'被 '+x.n_src+' 个资源用到':'仅 1 个资源用到'}</div></div></div>`).join('');
 t.innerHTML=h;
 $$('div.row[data-g]').forEach(el=>el.onclick=()=>openGroup(el.dataset.g));
 $$('div.row[data-h]').forEach(el=>el.onclick=()=>openAsset(el.dataset.h));
 if(d.assets.length===1&&!d.files.length&&!d.names.length)openGroup(d.assets[0].id)}
function thumb(a){return a.type==='texture'&&DECC.includes(a.codec)
  ?`<img loading=lazy src="/api/img/${a.hash}?s=192">`:`<div class=ph>${esc(zh('codec',a.codec)||zh('type',a.type))}</div>`}
function render(){
 const g=$('#grid'),t=$('#tbl');
 if(st.view==='home')return;
 if(st.view==='asset')return renderGroups(g,t);
 if($('#mode').value==='grid'){g.style.display='grid';t.style.display='none';
  g.innerHTML=st.rows.map(a=>`<div class="card" data-h=${a.hash}>${thumb(a)}
   <div class=t>${esc(a.name||'未命名文件')}</div><div class=m>${esc(zh('type',a.type))} · ${fmt(a.original)}
    ${a.width?` · ${a.width}×${a.height}`:''}</div></div>`).join('')}
 else{g.style.display='none';t.style.display='table';
  t.innerHTML=st.rows.map(a=>`<tr data-h=${a.hash}><td>${esc(a.name||'未命名文件')}</td>
   <td style="color:var(--dim)">${esc(zh('type',a.type))}</td>
   <td style="color:var(--dim)">${esc(zh('src',a.src))}</td>
   <td style="text-align:right">${fmt(a.original)}</td>
   <td style="color:var(--dim)">${esc(a.dir||'')}</td></tr>`).join('')}
 $$('#grid .card,#tbl tr').forEach(el=>el.onclick=()=>openAsset(el.dataset.h))}
function renderGroups(g,t){
 if($('#mode').value==='grid'){g.style.display='grid';t.style.display='none';
  g.innerHTML=st.rows.map(a=>`<div class="card" data-g=${a.id}>
   <img loading=lazy src="/api/preview/${a.id}.png" onerror="this.outerHTML='<div class=ph>${esc(zh('kind',a.kind))}</div>'">
   <div class=t>${esc(nice(a.stem)||('未命名 '+a.id))}</div>
   <div class=m>${esc(zh('kind',a.kind))} · ${a.n} 个文件</div></div>`).join('')}
 else{g.style.display='none';t.style.display='table';
  t.innerHTML=`<tr style="color:var(--dim);text-align:left"><th>名称</th><th>分类</th>
    <th>包含资源</th><th>状态</th><th>所在目录</th></tr>`+st.rows.map(a=>`<tr data-g=${a.id}>
   <td>${esc(nice(a.stem)||('未命名 '+a.id))}${a.tags&&a.tags.length
     ?` <span style="color:#7aa2f7">${a.tags.slice(0,3).map(t=>esc(zh('tag',t))).join(' · ')}</span>`:''}</td>
   <td style="color:var(--dim)">${esc(zh('kind',a.kind))}</td>
   <td style="text-align:right">${a.n} 个文件</td>
   <td style="color:${state(a)==='贴图未定位'?'#e0b352':'var(--dim)'}">${esc(state(a))}</td>
   <td style="color:var(--dim)">${esc(a.dir)}</td></tr>`).join('')}
 $$('#grid .card,#tbl tr').forEach(el=>el.onclick=()=>openGroup(el.dataset.g))}
const ROLECN={model:'模型',skeleton:'骨骼',mesh:'网格',material:'材质',animation:'动作',
 texture:'贴图',scene:'场景',effect:'特效',map:'地图块',set:'集合',audio:'音频',other:'其他'};
const ROLES=['model','skeleton','mesh','material','animation','texture','other'];
const RC={model:'#7aa2f7',skeleton:'#9ece6a',mesh:'#bb9af7',material:'#e0b352',
 animation:'#7dcfff',texture:'#f7768e',other:'#565f89'};
function graphSVG(d){
 const by={};d.nodes.forEach(n=>{(by[n.role]=by[n.role]||[]).push(n)});
 const cols=ROLES.filter(r=>by[r]&&by[r].length);
 if(!cols.length)return '<div style="color:var(--dim)">这个资源内部没有进一步的引用关系</div>';
 const cw=158,nh=20,gap=5,padx=10;
 let mx=0;cols.forEach(r=>mx=Math.max(mx,by[r].length));
 const W=cols.length*cw+padx,H=Math.max(mx,1)*(nh+gap)+30,pos={};
 cols.forEach((r,ci)=>by[r].forEach((n,i)=>pos[n.id]=[padx+ci*cw,22+i*(nh+gap)]));
 let s=`<svg width=${W} height=${H} style="max-width:100%;background:#12141a;border:1px solid var(--line);border-radius:6px">`;
 d.edges.forEach(e=>{const a=pos[e.from],b=pos[e.to];if(!a||!b)return;
  const x1=a[0]+cw-22,y1=a[1]+nh/2,x2=b[0],y2=b[1]+nh/2;
  s+=`<path d="M${x1} ${y1}C${x1+34} ${y1} ${x2-34} ${y2} ${x2} ${y2}" fill=none stroke="${e.rel==='name'?'#3b4150':'#4a5268'}" stroke-width=1 ${e.rel==='name'?'stroke-dasharray=3,3':''}/>`});
 d.nodes.forEach(n=>{const p=pos[n.id];if(!p)return;
  const c=RC[n.role]||RC.other, t=(n.label||'').slice(0,19);
  s+=`<g class=gn data-h="${n.dangling?'':n.id}" style="cursor:${n.dangling?'default':'pointer'}">
   <rect x=${p[0]} y=${p[1]} width=${cw-26} height=${nh} rx=3 fill="${n.dangling?'#12141a':c}22" stroke="${n.cls==='shared'?'#e0b352':c}" stroke-width=${n.dangling?1:1.4}/>`+
   (n.dangling?`<circle cx=${p[0]+7} cy=${p[1]+nh/2} r=2.5 fill=#e0b352/>`
              :`<circle cx=${p[0]+7} cy=${p[1]+nh/2} r=3 fill=${c}/>`)+
   `<text x=${p[0]+14} y=${p[1]+14} font-size=10 fill=#c0caf5 font-family=ui-monospace,Menlo,monospace>${esc(t)}</text></g>`});
 cols.forEach((r,ci)=>s+=`<text x=${padx+ci*cw} y=12 font-size=10 fill=${RC[r]} font-family=sans-serif>${zh('role',r)} ${by[r].length}</text>`);
 return s+'</svg>'}
async function openGroup(id){
 const d=await (await fetch('/api/group/'+id)).json();const G=d.group;
 const by={};(d.members||[]).forEach(m=>{(by[m.role]=by[m.role]||[]).push(m)});
 const chip=(r,n)=>n?`<span class=tag style="border-color:${RC[r]}55;color:${RC[r]}">${zh('role',r)} ${n}</span>`:'';
 $('#detail').classList.add('open');
 $('#detail').innerHTML=`<span class=x onclick="document.getElementById('detail').classList.remove('open')">关闭</span>
  <div style="display:flex;gap:14px;align-items:flex-start">
   <img src="/api/preview/${id}.png" width=112 height=112 style="border:1px solid var(--line);border-radius:6px;background:#12141a"
        onerror="this.style.display='none'">
   <div style="min-width:0">
    <h3 style="margin-top:0">${esc(nice(G.stem)||('未命名资源 '+id))}</h3>
    <div style="color:var(--dim);font-size:12px">${esc(zh('kind',G.kind))} · 由 ${G.n} 个文件组成 · ${esc(state(G))}</div>
    <div style="margin:6px 0">${chip('model',by.model&&by.model.length)}${chip('skeleton',by.skeleton&&by.skeleton.length)}${chip('mesh',G.n_mesh)}${chip('material',G.n_mtl)}${chip('animation',G.n_ani)}${chip('texture',G.n_tex)}${G.names?`<span class=tag style="color:#f7768e;border-color:#f7768e55">贴图名 ${G.names}</span>`:''}</div>
    ${(d.tags||[]).map(t=>`<span class=tag>${esc(zh('tag',t))}</span>`).join('')}
    <div style="color:var(--dim);font-size:11px;word-break:break-all">${esc(G.dir)}</div>
    ${d.fp?`<div style="color:var(--dim);font-size:11px">资源身份证 ${esc((d.fp.id_asset||'').toUpperCase())}${d.dup?` · 另有 ${d.dup} 项资源与它内容完全相同`:''}</div>
    <div style="color:var(--dim);font-size:11px">内容 ${esc((d.fp.id_content||'').slice(0,8))} · 结构 ${esc((d.fp.id_struct||'').slice(0,8))} · 打包 ${esc((d.fp.id_pack||'').slice(0,8))}</div>`:''}
   </div></div>
  <div style="margin:10px 0"><button onclick="window.open('/api/report/${id}')">导出这个资源的报告</button></div>
  <div class=sec>这个资源由什么组成</div>
  <div style="overflow:auto">${graphSVG(d)}</div>
  ${Object.entries(by).map(([role,ms])=>`<div class=sec>${zh('role',role)} · ${ms.length} 个</div><div class=rel>`+
    ms.map(m=>`<a data-h=${m.hash}>${esc(m.name||'未命名文件')} <span style="color:var(--dim)">${esc(zh('src',m.src))} · ${fmt(m.original)}</span></a>`).join('')+'</div>').join('')}
  ${d.names&&d.names.length?`<div class=sec>引用了但没找到对应文件 · ${d.names.length} 个名字</div>
    <div class=rel>${d.names.map(n=>`<span style="color:${n.cls==='shared'?'#e0b352':'inherit'}">${esc(n.name)}${n.cls==='shared'?' <i style="color:var(--dim)">多个资源共用</i>':' <i style="color:var(--dim)">仅此资源使用</i>'}</span>`).join(' · ')}</div>`:''}`;
 $$('#detail a[data-h]').forEach(el=>el.onclick=()=>openAsset(el.dataset.h));
 $$('#detail g.gn').forEach(el=>el.onclick=()=>el.dataset.h&&openAsset(el.dataset.h))}
async function openAsset(h){
 const d=await (await fetch('/api/asset/'+h)).json();const a=d.asset;
 $('#detail').classList.add('open');
 $('#detail').innerHTML=`<span class=x onclick="document.getElementById('detail').classList.remove('open')">✕ 关闭</span>
  <h3>${esc(a.name||'未命名文件')}</h3>
  <div>${a.type==='texture'?`<img src="/api/img/${h}?s=420" style="max-width:100%;border:1px solid var(--line);border-radius:6px">`
   :`<div class=ph style="height:70px;line-height:70px;color:#3b4150">${esc(a.type)} · 无法预览</div>`}</div>
  <div style="margin-top:10px">${['<span class=tag>'+esc(zh('type',a.type))+'</span>',a.subtype&&a.subtype!==a.type?
    '<span class=tag>'+esc(a.subtype)+'</span>':'',a.codec?'<span class=tag>'+esc(zh('codec',a.codec))+'</span>':'',
    '<span class=tag>'+(a.named?zh('src',a.src):'没名字')+'</span>'].filter(Boolean).join('')}</div>
  <div class=kv>${[['名字',a.name||'未命名文件'],['分类',zh('type',a.type)],
   ['图片尺寸',a.width?a.width+' × '+a.height:'—'],['文件大小',fmt(a.original)],
   ['名字来源',a.named?zh('src',a.src):'没能还原出名字'],['所在资源包',a.pak],['目录',a.dir||'—']]
   .map(([k,v])=>`<b>${esc(k)}</b><span>${esc(v)}</span>`).join('')}
   <details style="grid-column:1/-1;margin-top:8px">
    <summary style="color:var(--dim);cursor:pointer">技术信息（给程序看的）</summary>
    ${[['编号',a.hash],['虚拟路径',a.path||'-'],['子类型',a.subtype||'-'],['图片格式',zh('codec',a.codec)],
     [' mip 层数',a.mips||'-'],['包内大小',fmt(a.stored)+' / 对齐 '+fmt(a.occupied)],
     ['包内位置',a.pak+'.pak 第'+a.gen+'代 @ '+a.offset],['标志位','0x'+(a.flags||0).toString(16)+' / 方法 '+(a.method||0)],
     ['校验码',a.filecrc?'0x'+(a.filecrc>>>0).toString(16):'-'],['文件自述路径',a.self_path||'-']]
     .map(([k,v])=>`<b>${esc(k)}</b><span>${esc(v)}</span>`).join('')}</details></div>
  ${relBlock('它用到了',d.out)}${relBlock('谁在用它',d.in.concat(d.usedby||[]))}
  ${strBlock('它内部记录的文件名',d.refs)}
  ${fxBlock(a)}
  <div style="margin-top:10px"><button onclick="location='/api/blob/${h}'">下载这个文件</button>
   <button onclick="navigator.clipboard.writeText('${h}')">复制编号</button></div>`;
 $$('#detail a[data-h]').forEach(el=>el.onclick=()=>openAsset(el.dataset.h))}
const REL={'use-mtl':'用到材质','use-ske':'用到骨骼','use-mesh':'用到模型','use-ani':'用到动作',
 'use-tex':'用到贴图','use-pu':'用到特效','use-scene':'用到场景','model-part':'属于同一个模型',
 'same-stem':'同名配套文件','ref':'文件里写着'};
function fxBlock(a){let p={};try{p=JSON.parse(a.props||'{}')}catch(e){}
 const f=p.fx;if(!f)return '';
 const row=(k,v)=>{v=[].concat(v||[]);return v.length?`<b>${k}</b><span>${esc(v.join(' · '))}</span>`:''};
 return `<div class=sec>特效构成（粒子系统定义）</div><div class=kv>`+
  row('材质',f.material)+row('贴图',f.texture)+row('模型',f.mesh)+row('混合方式',f.blend)+
  row('渲染方式',f.renderer)+row('发射器',f.emitter)+row('更新器',f.updater)+
  row('动态参数',f.dynamic)+row('其他名字',f.other)+
  `<b>参数区</b><span>${(f.param_bytes||0).toLocaleString()} 字节（数值待解析）</span>`+
  `</div>`}
function relBlock(t,rows){return rows&&rows.length?`<div class=sec>${t} · ${rows.length} 项</div><div class=rel>`+rows.map(r=>
  `<a data-h=${r.hash}>${esc(r.name||(r.path||r.hash))} <span style="color:var(--dim)">${esc(REL[r.rel]||r.rel)} · ${esc(zh('type',r.type))} · ${fmt(r.original)}</span></a>`).join('')+'</div>':''}
function strBlock(t,rows){if(!rows||!rows.length)return '';
 const hit=rows.filter(r=>r.to_hash), miss=rows.filter(r=>!r.to_hash);
 return `<div class=sec>${t} · ${rows.length} 个（${hit.length} 个找得到对应文件）</div><div class=rel>`+
  hit.map(r=>`<a data-h=${r.to_hash}>${esc(r.name)} <span style="color:var(--dim)">${esc(zh('type',r.kind))}</span></a>`).join('')+
  (miss?`<div style="color:#6b7280;padding:4px 0">${esc(miss.map(r=>r.name).join(' · '))}</div>`:'')+'</div>'}
$('#go').onclick=()=>{st.q=$('#q').value.trim();st.type=$('#type').value;st.src=$('#src').value;
 st.named=$('#named').value;st.kind=$('#kind').value;st.tag=$('#tag').value;
 st.withnames=$('#withnames').checked?'1':'';st.view=$('#view').value;st.offset=0;load()};
$('#q').onkeydown=e=>{if(e.key==='Enter')$('#go').click()};
$('#view').onchange=()=>{const v=$('#view').value, a=v==='asset', h=v==='home';
 const v2=$('#vsel');v2.style.display='none';
 if(h||v==='ver'){['kind','tag','type','src','named','wn','mode'].forEach(x=>$('#'+x).style.display='none');
   $('#stat').textContent='';return v==='ver'?versions():home()}
 $('#mode').style.display='';if(a)$('#mode').value='table';
 $('#kind').style.display=a?'':'none';$('#wn').style.display=a?'inline':'none';
 $('#tag').style.display=a?'':'none';$('#type').style.display=a?'none':'';
 $('#src').style.display=a?'none':'';$('#named').style.display=a?'none':'';$('#go').click()};
$('#vsel').onchange=()=>diff($('#vsel').value);
$('#kind').onchange=()=>$('#go').click();
$('#tag').onchange=()=>$('#go').click();
$('#withnames').onchange=()=>$('#go').click();
$('#mode').onchange=render;
$('#more').onclick=()=>{st.offset=st.rows.length;load(true)};
load();
</script></body></html>'''


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype='application/json'):
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        try:
            path, _, qs = self.path.partition('?')
            if path in ('/', '/index.html'):
                zk = json.dumps(LABELS, ensure_ascii=False)
                return self.send(200, HTML.replace('__ZK__', zk).encode(),
                                 'text/html; charset=utf-8')
            if path == '/api/list':
                return self.send(200, json.dumps(q_list(parse_qs(qs))).encode())
            if path == '/api/versions':
                return self.send(200, json.dumps(q_versions(), ensure_ascii=False).encode())
            if path == '/api/diff':
                return self.send(200, json.dumps(q_diff(parse_qs(qs).get('with', [''])[0]),
                                                 ensure_ascii=False).encode())
            if path == '/api/search':
                return self.send(200, json.dumps(q_search(parse_qs(qs).get('q', [''])[0]),
                                                 ensure_ascii=False, default=str).encode())
            if path == '/api/summary':
                return self.send(200, json.dumps(q_summary(), ensure_ascii=False,
                                                 default=str).encode())
            if path == '/api/groups':
                return self.send(200, json.dumps(q_groups(parse_qs(qs)),
                                                 ensure_ascii=False, default=str).encode())
            if path.startswith('/api/group/'):
                return self.send(200, json.dumps(q_group(int(path[11:])),
                                                 ensure_ascii=False, default=str).encode())
            if path.startswith('/api/report/'):
                import report
                gid = int(''.join(c for c in path[12:] if c.isdigit()) or 0)
                html_txt = report.asset_report(report.con(), gid, lambda g: '资源报告_%d.html' % g)
                if not html_txt:
                    return self.send(404, b'{"error":"no such asset"}')
                return self.send(200, report.page(html_txt, '资源报告 · %d' % gid).encode(),
                                 'text/html; charset=utf-8')
            if path.startswith('/api/preview/'):
                gid = ''.join(ch for ch in path[13:] if ch.isdigit())
                f = os.path.join(PREV, gid + '.png')
                if gid and os.path.isfile(f):
                    with open(f, 'rb') as fh:
                        return self.send(200, fh.read(), 'image/png')
                return self.send(404, b'{"error":"no preview"}')
            if path.startswith('/api/asset/'):
                return self.send(200, json.dumps(q_asset(unquote(path[11:])),
                                                 ensure_ascii=False, default=str).encode())
            if path.startswith('/api/img/'):
                h = path[9:]
                raw = read_payload(h)
                if raw is None:
                    return self.send(404, b'{"error":"no payload"}')
                img, info = decode_jmt1(raw)
                if img is None:
                    return self.send(422, json.dumps(info).encode())
                return self.send(200, over_checker(img, int((parse_qs(qs).get('s') or ['192'])[0])),
                                 'image/png')
            if path.startswith('/api/blob/'):
                raw = read_payload(unquote(path[10:]))
                if raw is None:
                    return self.send(404, b'{"error":"no payload"}')
                return self.send(200, raw, 'application/octet-stream')
            return self.send(404, b'{"error":"not found"}')
        except Exception as e:                                    # keep the server alive
            return self.send(500, json.dumps({'error': repr(e)}).encode())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', type=int, default=8765)
    a = ap.parse_args()
    payloads()
    print('TLBB resource explorer  ->  http://127.0.0.1:%d/   (%d payloads indexed)'
          % (a.port, len(_cache['p'])))
    ThreadingHTTPServer(('127.0.0.1', a.port), H).serve_forever()


if __name__ == '__main__':
    main()
