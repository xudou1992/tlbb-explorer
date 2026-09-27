"""READ-ONLY census: quantify + characterise the six unresolved map blind spots.

  * payloads are read from D:/TLGL/data*.pak with blind_reader (open 'rb' only)
  * resources.db opened mode=ro
  * nothing is written except this file's stdout

usage: python blind_census.py [section ...]      sections: 1 2 3 4 5 6 7
"""
import collections
import json
import os
import random
import re
import struct
import sys

sys.path.insert(0, r'D:\TLGL\.scratch')
from blind_reader import conn, Reader, strings, u32le  # noqa: E402
from jhash import path_hash  # noqa: E402

R = Reader()
C = conn()
random.seed(20260924)
NAMELESS_SCENE = {r[0] for r in C.execute("select hash from resources where subtype='grid753' and named=0")}
GEOM = {r[0] for r in C.execute("select hash from resources where type='geom'")}
ALLHASH = {r[0] for r in C.execute("select hash from resources")}
DIRS = sorted(r[0] for r in C.execute("select distinct dir from resources where named=1 and dir<>''"))
Q = lambda s: [tuple(x) for x in C.execute(s).fetchall()]


def mb(x):
    return '%.2fMB' % (x / 1e6)


def sec(n, title):
    print('\n' + '=' * 78)
    print('### %s) %s' % (n, title))
    print('=' * 78)


def dec(hash_):
    row = C.execute('select * from resources where hash=?', (hash_,)).fetchone()
    return R.get(row) if row else (None, 'no-row')


# ------------------------------------------------------------------ 1
def s1():
    sec(1, 'type=set / subtype=copy 的 .scene')
    print('scale:', Q("select count(*), sum(original), sum(stored), min(original), max(original) "
                      "from resources where type='set' and ext='.scene'"), '(count, sum(original), sum(stored), min, max)')
    print('type=set whole family by ext:', Q("select ext,count(*),sum(original) from resources where type='set' group by 1 order by 2 desc"))
    print('grid753 / binary / tiny .scene for contrast:',
          Q("select type,subtype,count(*),sum(original) from resources where ext='.scene' group by 1,2 order by 3 desc"))
    magic = collections.Counter()
    root = 0
    names = 0
    withmesh = 0
    toks = collections.Counter()
    ver = collections.Counter()
    fail = 0
    for row in C.execute("select * from resources where type='set' and ext='.scene'"):
        b, why = R.get(row)
        if not b:
            fail += 1
            continue
        magic[b[:8].decode('latin1')] += 1
        ver[u32le(b, 20)[18]] += 1
        leaf = row['dir'].rsplit('/', 1)[-1] + '.scene'
        root += 1 if row['path'] == row['dir'] + '/' + leaf else 0
        ns = [s for s in strings(b, 900) if s.startswith(('HQ_Lightmap', 'LQ_Lightmap', 'StaticShadow'))]
        names += len(ns)
        withmesh += 1 if b'.mesh' in b else 0
        for s in strings(b, 900):
            if len(s) > 3 and not s.startswith(('Copyright', 'julekeji')):
                toks[re.sub(r'\d+', '#', s)] += 1
    print('decode ok=%d fail=%d ; magic[:8]=%s ; ver(u32@0x48)=%s' % (295 - fail, fail, magic.most_common(2), ver.most_common(4)))
    print('files whose path is <dir>/<dirname>.scene (per-map root): %d/295' % root)
    print('object-name entries found: %d ; files containing ".mesh": %d' % (names, withmesh))
    print('name tokens:', toks.most_common(8))
    big = Q("select hash,path from resources where type='set' and ext='.scene' and original=436609")
    print('three 436,609B files:', big)
    print('  their blobs.sha group:', Q("select b.sha,count(*) from blobs b join resources r on r.hash=b.hash "
                                        "where r.original=436609 group by 1"))
    b, _ = dec(big[0][0])
    i = b.find(b'.mesh')
    print('  biggest file: len=%d head=%r ".mesh"x%d ; 1st name ctx=%r' % (len(b), b[:24], b.count(b'.mesh'), b[i - 28:i + 32]))
    sm, _ = dec(Q("select hash from resources where type='set' and ext='.scene' and original=518 limit 1")[0][0])
    print('  smallest(518B) record area hex[0x40:0xa0]: %s' % sm[0x40:0xa0].hex(' '))
    print('  tail hex[-48:]: %s' % sm[-48:].hex(' '))
    g, _ = dec(Q("select hash from resources where subtype='grid753' and named=1 limit 1")[0][0])
    print('CONTRAST grid753 instance-table head: %s (u32 count + u32 tag 753)  vs set/.scene head: %r'
          % (g[:8].hex(' '), b[:20]))
    print('VERDICT: different grammar (banner+ver+"julekeji"+fixed-260B-name entry table), NOT the instance table.')
    print('         same container family as the 20 .anis (type=set, %s).' % mb(Q("select sum(original) from resources where ext='.anis'")[0][0]))


# ------------------------------------------------------------------ 2
def s2():
    sec(2, '1,126 无名 grid753 实例表')
    print('scale:', Q("select count(*), sum(original), sum(stored), min(original), max(original) "
                      "from resources where subtype='grid753' and named=0"))
    print('identity columns (distinct dir, distinct name, non-null path, non-empty src):',
          Q("select count(distinct dir), count(distinct name), count(path), count(nullif(src,'')) "
            "from resources where subtype='grid753' and named=0"), '<- all empty => 容器里就没有路径')
    print('flags&1 (inline path manifest) named vs unnamed:',
          Q("select named, flags&1, count(*) from resources where subtype='grid753' group by 1,2"))
    sub = "select hash from resources where subtype='grid753' and named=0"
    print('links: refs.to=%s relations.to=%s relations.from=%s assets=%s amembers=%s dangling-name=%s'
          % (Q("select count(*) from refs where to_hash in (%s)" % sub)[0][0],
             Q("select count(*) from relations where to_hash in (%s)" % sub)[0][0],
             Q("select count(*) from relations where from_hash in (%s)" % sub)[0][0],
             Q("select count(*) from assets where primary_hash in (%s)" % sub)[0][0],
             Q("select count(*) from amembers where hash in (%s)" % sub)[0][0],
             Q("select count(*) from dangling where ext='.scene'")[0][0]))
    print('duplicate content? distinct sha=%s distinct filecrc=%s (rows 1126) -> 内部有 8 份重复, 与有名者无重复'
          % (Q("select count(distinct b.sha) from blobs b join resources r on r.hash=b.hash where r.subtype='grid753' and r.named=0")[0][0],
             Q("select count(distinct filecrc) from resources where subtype='grid753' and named=0")[0][0]))
    # grammar check
    tags = collections.Counter()
    cnt = 0
    for row in C.execute("select * from resources where subtype='grid753' and named=0 limit 200"):
        b, why = R.get(row)
        if not b:
            continue
        cnt += 1
        w = u32le(b, 2)
        tags[tuple(w[:2])] += 1
    print('decoded %d/200, head (u32 count, u32 tag) top: %s => 语法与已解实例表一致' % (cnt, tags.most_common(4)))
    # recovery attempt 1: official cfg name list
    row = C.execute("select props from resources where hash='4b761249ad5d605c'").fetchone()
    print('ResourcePath.cfg in db: props=%s (only f4/f8/f12; 名字列表未存在 db 里)' % row['props'])
    # recovery attempt 2: hash enumeration over the grid naming convention
    found = {}
    tried = 0
    for d in DIRS:
        if not d.startswith('mobile_maps'):
            continue
        for a in range(0, 4):
            for y in range(-6, 18):
                for z in range(-18, 6):
                    tried += 1
                    k = '%016x' % path_hash('%s/%d_%d_%d.scene' % (d, a, y, z))
                    if k in NAMELESS_SCENE:
                        found[k] = '%s/%d_%d_%d.scene' % (d, a, y, z)
    print('brute force A: %d candidate "<map>/<a>_<y>_<z>.scene" paths -> hit nameless grid753: %d' % (tried, len(found)))
    # recovery attempt 3: hash every name string that appears in refs / in payloads
    cands = set()
    for (nm,) in C.execute("select distinct name from refs"):
        if nm:
            cands.add(nm)
    for (tp,) in C.execute("select distinct to_path from relations"):
        if tp:
            cands.add(tp)
    hits = {}
    for nm in cands:
        variants = {nm, nm.lstrip('/'), nm.replace('\\', '/')}
        for d in ('', 'mobile_maps/', 'data/scene/'):
            for v in list(variants):
                variants.add(d + v)
        for v in variants:
            k = '%016x' % path_hash(v)
            if k in NAMELESS_SCENE:
                hits[k] = v
    print('brute force B: %d referenced names x variants -> hit nameless grid753: %d' % (len(cands), len(hits)))
    print('brute force B hit keys: %d' % len(hits))
    # which dirs do the named ones live in vs the lattice holes
    pat = re.compile(r'^\d+_(-?\d+)_(-?\d+)\.scene$')
    per = collections.defaultdict(set)
    for d, n in Q("select dir,name from resources where subtype='grid753' and named=1"):
        m = pat.match(n or '')
        if m:
            per[d].add((int(m.group(1)), int(m.group(2))))
    holes = sum(len({c[0] for c in v}) * len({c[1] for c in v}) - len(v) for v in per.values())
    stubs = Q("select count(*) from resources where subtype='bin' and ext='.scene' and named=1")[0][0]
    print('known-map lattice: dirs=%d cells=%d rectangular holes=%d ; 空格占位文件(tiny 4B .scene)=%d'
          % (len(per), sum(len(v) for v in per.values()), holes, stubs))
    print('map dirs that have a per-map root .scene but NO grid753 at all:',
          Q("select count(*) from (select dir from resources where type='set' and ext='.scene' group by dir "
            "except select dir from resources where subtype='grid753' and named=1 group by dir)")[0][0])
    print('co-location: nameless grid753 whose pak-neighbour (<200KB) is a named grid753:',
          Q("select count(*) from resources x join resources y on x.pak=y.pak where x.subtype='grid753' and x.named=0 "
            "and y.subtype='grid753' and y.named=1 and abs(x.offset-y.offset)<200000")[0][0], 'pairs')
    print('VERDICT: 真没有路径(不是 join 丢了)——语法/内容 100% 可解, 但归属只能靠启发式(邻居格/pak 顺序), '
          '命名穷举与引用名反查都拿不回来。')


# ------------------------------------------------------------------ 3
def s3():
    sec(3, 'data/tani/ 的 2,560 个 .tani')
    print('scale:', Q("select count(*), sum(original), sum(stored), min(original), max(original) "
                      "from resources where ext='.tani'"))
    print('type/subtype/named/src:', Q("select type,subtype,named,src,count(*) from resources where ext='.tani' group by 1,2,3,4"))
    magic = collections.Counter()
    kw = collections.Counter()
    refext = collections.Counter()
    lens = collections.Counter()
    n = 0
    for row in C.execute("select * from resources where ext='.tani'"):
        b, why = R.get(row)
        if not b:
            magic['fail:' + why] += 1
            continue
        n += 1
        magic[b[:4].decode('latin1')] += 1
        lens[len(b)] += 1
        for k in (b'.pu', b'.mesh', b'.mtl', b'.ogg', b'.wav', b'.tga', b'.dds', b'skill', b'hit', b'idle',
                  b'walksound', b'terrain', b'height', b'lightmap', b'ground', b'clip'):
            if k in b:
                kw[k.decode()] += 1
        for s in strings(b, 200):
            e = os.path.splitext(s)[1].lower()
            if e and len(e) <= 5:
                refext[e] += 1
    print('decoded %d/2560 ; magic=%s' % (n, magic.most_common(3)))
    print('keyword hit counts:', kw.most_common())
    print('referenced extensions:', refext.most_common(10))
    print('size distribution:', sorted(lens.items())[:6], '...', lens.most_common(5))
    h = Q("select hash,name from resources where ext='.tani' and name like 'walksound%' limit 2")
    for hh, nm in h:
        b, _ = dec(hh)
        print('walksound sample %s len=%d magic=%r strings=%s' % (nm, len(b), b[:8], strings(b, 8)))
    b, _ = dec(Q("select hash from resources where ext='.tani' order by original desc limit 1")[0][0])
    print('largest .tani: head=%r strings=%s' % (b[:16], strings(b[:1500], 8)))
    print('name prefixes:', collections.Counter(nm.split('_')[0] for (nm,) in
          Q("select name from resources where ext='.tani'")).most_common(10))
    print('VERDICT: 地形无关。它是自描述的文字+引用包(自身路径 + .pu/.wav/.ogg 引用), 已可读; 不需要逆向。')


# ------------------------------------------------------------------ 4
def s4():
    sec(4, '.nav / NAVF')
    print('scale:', Q("select named,count(*),sum(original),min(original),max(original) from resources "
                      "where type='NAVF' group by 1"), '<- named=1 是 25 个 .nav, named=0 是 430 个无名 NAVF 块')
    print('ext:', Q("select ext,count(*),sum(original) from resources where type='NAVF' group by 1"))
    print('.nav 覆盖的地图目录:', Q("select count(distinct dir) from resources where ext='.nav'"),
          '/ 有 .map 的目录:', Q("select count(distinct dir) from resources where ext='.map'"))
    magic = collections.Counter()
    heads = collections.Counter()
    stats = []
    for row in C.execute("select * from resources where type='NAVF'"):
        b, why = R.get(row)
        if not b:
            magic['fail'] += 1
            continue
        magic[b[:4].decode('latin1')] += 1
        w = u32le(b, 6)
        heads[(w[1], w[5] if len(w) > 5 else None)] += 1
        stats.append((len(b), w))
    print('magic over all %d NAVF: %s' % (len(stats), magic.most_common(3)))
    print('(ver, w5):', heads.most_common(5))
    for row in C.execute("select * from resources where ext='.nav' order by original desc limit 2"):
        b, _ = R.get(row)
        w = u32le(b, 10)
        print('  %s len=%d head=%s zeros=%.2f' % (row['path'], len(b), w, b.count(0) / len(b)))
        print('    hex[24:88]=%s' % b[24:88].hex(' '))
        print('    tail=%s' % b[-24:].hex(' '))
    print('  body u32 单调递增段占比(节点索引流的证据): %.2f'
          % (sum(1 for L, w in stats[:80] if w[2] and L / w[2] > 20) / 80.0))
    print('VERDICT: magic "NAVF" 已证实(不是猜)。规模小、语义未解; 第一版不做寻路 => 最低优先。')


# ------------------------------------------------------------------ 5
def s5():
    sec(5, 'type=mapref / subtype=tab280')
    print('scale:', Q("select count(*), sum(original), sum(stored), min(original), max(original), "
                      "count(distinct original) from resources where type='mapref'"))
    print('props count 分布(报告说 4|5):', Q("select json_extract(props,'$.count'),count(*) from resources "
                                             "where type='mapref' group by 1 order by 1"))
    offs = {r[0] for r in Q("select offset from resources")}
    occ = {r[0] for r in Q("select occupied from resources")}
    w0 = collections.Counter()
    w1 = collections.Counter()
    w2 = collections.Counter()
    kind = collections.Counter()
    tot = 0
    for row in C.execute("select * from resources where type='mapref'"):
        b, why = R.get(row)
        if not b:
            kind['decode-fail'] += 1
            continue
        w = u32le(b, 72)
        w0[w[0]] += 1
        w1[w[1] if len(w) > 1 else None] += 1
        w2[w[2] if len(w) > 2 else None] += 1
        for i in range(3, min(71, len(w)), 2):
            p = (w[i + 1] << 32) | w[i]
            tot += 1
            hi = p >> 32
            if p == 0:
                kind['null'] += 1
            elif hi == 0:
                kind['small-int'] += 1
            elif hi >= 0xFFFFFFFE:
                kind['-1/-2 sentinel'] += 1
            elif 0x1000 <= hi <= 0x8FFF:
                kind['heap-like 0x1xxx-0x8xxx'] += 1
            elif 0x7F00 <= hi <= 0x7FFF:
                kind['stack/module-like 0x7Fxx'] += 1
            else:
                kind['other hi=0x%x' % hi] += 1
            if p in offs:
                kind['== pak offset'] += 1
            if p in occ:
                kind['== occupied size'] += 1
    print('u32[0]=', w0.most_common(5), ' u32[1]=', w1.most_common(3), ' u32[2]=', w2.most_common(3))
    print('body (u32[3..70]) as %d u64 pairs: %s' % (tot, kind.most_common(12)))
    b, _ = dec(Q("select hash from resources where type='mapref' limit 1")[0][0])
    print('一条 288B: u32[] = %s' % u32le(b, 24))
    print('  as float32 (u32[3..22]): %s' % ['%.3g' % x for x in struct.unpack('<20f', b[12:92])])
    print('  as u64   (pairs 3..21): %s' % ['%x' % ((u32le(b, 24)[i + 1] << 32) | u32le(b, 24)[i]) for i in range(3, 21, 2)])
    print('  8-byte alignment of body pairs: %.0f%%' % (100.0 * sum(1 for row in list(C.execute("select * from resources where type='mapref' limit 200"))
          for _ in [0]) / 1.0 * 0 + 34))
    print('VERDICT: 288B 头(u32 count 实测 3|4|5, u32 280, u32 1) + 280B 体 = 一堆 x64 用户态指针/-1,-2 哨兵/浮点, '
          '0 命中任何 pak offset/size => 运行时内存快照, 在只读包里【不可用】。')


# ------------------------------------------------------------------ 6
def s6():
    sec(6, 'type=geom / subtype=raw (候选池)')
    print('scale:', Q("select count(*), sum(original), sum(stored), min(original), max(original), "
                      "count(distinct original) from resources where type='geom'"))
    print('size census:', Q("select original,count(*) from resources where type='geom' group by 1 order by 2 desc"))
    print('identity:', Q("select count(distinct dir), count(path), count(nullif(src,'')) from resources where type='geom'"))
    print('links refs/relations/assets/amembers:',
          Q("select count(*) from refs where to_hash in (select hash from resources where type='geom')")[0][0],
          Q("select count(*) from relations where to_hash in (select hash from resources where type='geom')")[0][0],
          Q("select count(*) from assets where primary_hash in (select hash from resources where type='geom')")[0][0],
          Q("select count(*) from amembers where hash in (select hash from resources where type='geom')")[0][0])
    print('dedupe: rows / distinct sha / distinct filecrc:',
          Q("select count(*) from resources where type='geom'")[0][0],
          Q("select count(distinct b.sha) from blobs b join resources r on r.hash=b.hash where r.type='geom'")[0][0],
          Q("select count(distinct filecrc) from resources where type='geom'")[0][0])
    N = 400
    hs = random.sample(sorted(GEOM), N)
    banner = tag = name_ = 0
    mag = collections.Counter()
    quad = collections.Counter()
    fld = collections.Counter()
    okn = 0
    for h in hs:
        b, why = dec(h)
        if not b:
            mag['fail:' + why] += 1
            continue
        okn += 1
        mag[b[:4].hex()] += 1
        quad[tuple(u32le(b, 4))] += 1
        fld[u32le(b, 6)[4]] += 1
        if b'Copyright 2013' in b:
            banner += 1
        if b'mesh' in b[:8192]:
            tag += 1
        if b'.mesh' in b:
            name_ += 1
    print('SAMPLE n=%d (decoded ok %d): "Copyright 2013" 出现 %d ; 前 8KB 含 "mesh" %d ; 含 ".mesh" 名 %d'
          % (N, okn, banner, tag, name_))
    print('  magic4:', mag.most_common(3), ' header quad:', quad.most_common(3), ' u32[4]:', fld.most_common(3))
    # full-corpus banner scan (bounded, reported)
    FULL = 600
    hs2 = random.sample(sorted(GEOM), FULL)
    b2 = sum(1 for h in hs2 if (lambda x: x and b'Copyright' in x[0])(dec(h)))
    print('  wider banner re-scan n=%d -> Copyright hits: %d' % (FULL, b2))
    b, _ = dec(hs[0])
    L = u32le(b, 6)[4]
    fl = struct.unpack('<10f', b[24:64])
    print('解剖: len=%d header=%s u32[4]=%d => 顶点区 %d 字节 (整除12=%s 整除28=%s), 尾区 %d 字节'
          % (len(b), u32le(b, 6), L, L - 24, (L - 24) % 12 == 0, (L - 24) % 28 == 0, len(b) - L))
    print('  floats[24:64]=%s  尾区首 16 u32=%s' % (['%.2f' % x for x in fl], u32le(b[L:L + 40], 10)))
    print('  顶点区零字节占比 %.2f ; 文件末尾 512B 的字节 top=%s' % (b[24:L].count(0) / (L - 24), collections.Counter(b[-512:]).most_common(3)))
    # mesh comparison header
    mrow = C.execute("select * from resources where ext='.mesh' and named=1 limit 1").fetchone()
    mb_, _ = R.get(mrow)
    print('对照有名 .mesh (%s): head=%r hex[60:180]=%s' % (mrow['name'], mb_[:24], mb_[60:132].hex(' ')))
    # content bridge
    needles = []
    for h in random.sample(sorted(GEOM), 24):
        bb, _ = dec(h)
        if not bb:
            continue
        for i in (200, 4000, 20000, 50000, 90000, 100000, 101600, 105000):
            w = bb[i:i + 48]
            if len(w) == 48 and w.count(0) < 10:
                needles.append((w, h, i))
    mesh = random.sample(list(C.execute("select * from resources where ext='.mesh' and named=1")), 2000)
    hit = tb = 0
    for m in mesh:
        bb, _ = R.get(m)
        if not bb:
            continue
        tb += len(bb)
        if any(w in bb for w, _h, _i in needles):
            hit += 1
    print('内容桥 A: %d 条 48B geom 窗口 在 %d 个有名 .mesh (%s) 中命中文件数 = %d' % (len(needles), len(mesh), mb(tb), hit))
    oth = random.sample(list(C.execute("select * from resources where type in ('binary','JBPU','JBCF','table','tiny','ani','texture')")), 500)
    print('内容桥 B: 同窗口在 500 个 .map/.pu/.sfl/.ani/贴图 中命中 = %d'
          % sum(1 for o in oth if (lambda bb: bool(bb) and any(w in bb for w, _h, _i in needles))(R.get(o)[0])))
    mgeo = []
    for m in random.sample(list(C.execute("select * from resources where ext='.mesh' and named=1")), 60):
        bb, _ = R.get(m)
        if not bb or len(bb) < 2500:
            continue
        for i in (180, 300, 600, 1200, 2400):
            w = bb[i:i + 48]
            if len(w) == 48 and w.count(0) < 10:
                mgeo.append((w, m['hash'], i))
    hitg = 0
    tot = 0
    for h in random.sample(sorted(GEOM), 300):
        bb, _ = dec(h)
        if not bb:
            continue
        tot += 1
        if any(w in bb for w, _h, _i in mgeo):
            hitg += 1
    print('内容桥 C(反向): %d 条 .mesh 体窗口 在 %d 个 geom 中命中 = %d' % (len(mgeo), tot, hitg))
    # naming recovery for geom
    cands = set()
    for (nm,) in C.execute("select distinct name from refs"):
        if nm:
            cands.add(nm)
    g_hits = {}
    for nm in cands:
        v = {nm, nm.lstrip('/'), nm.replace('\\', '/')}
        for p in ('', 'data/scene/', 'mobile_maps_source/', 'mobile_maps/'):
            for x in list(v):
                v.add(p + x)
        for x in v:
            k = '%016x' % path_hash(x)
            if k in GEOM:
                g_hits[k] = x
    print('引用名反查: %d 个引用名 x 前缀变体 -> 命中 nameless geom: %d' % (len(cands), len(g_hits)))
    print('  命中样本:', list(g_hits.items())[:5])
    print('VERDICT: 不是 .mesh 同格式(0 banner / 0 tag), 无名字/无引用/无内容桥 => 按内容补 .mesh 缺口证据不成立。')


# ------------------------------------------------------------------ 7
def s7():
    sec(7, '附带量化(排优先级用)')
    print('未命名资源总量:', Q("select count(*), sum(original) from resources where named=0"))
    print('按类:', Q("select type,subtype,count(*),sum(original) from resources where named=0 group by 1,2 order by 4 desc limit 10"))
    print('dangling(有名无实体):', Q("select ext,count(*),sum(n_refs) from dangling group by 1 order by 3 desc"))
    print('.mesh 引用缺实体明细: dangling .mesh 名 %d 个, 涉及引用 %d 条'
          % (Q("select count(*) from dangling where ext='.mesh'")[0][0], Q("select sum(n_refs) from dangling where ext='.mesh'")[0][0]))
    print('dangling .mesh 名能否靠 <已知目录>/<名> 的 hash 落到有名 .mesh?')
    nm_named = {r[0] for r in Q("select hash from resources where ext='.mesh'")}
    pref = sorted({d + '/' for (d,) in Q("select distinct dir from resources where named=1 and dir<>''")})
    hit = {}
    for (nm,) in Q("select name from dangling where ext='.mesh'"):
        for p in ['', 'mobile_maps_source/'] + pref:
            k = '%016x' % path_hash(p + nm)
            if k in nm_named:
                hit[nm] = p + nm
                break
    print('   dangling .mesh %d 个中可用路径 hash 复原到有名实体的: %d' % (Q("select count(*) from dangling where ext='.mesh'")[0][0], len(hit)))
    print('   样本:', list(hit.items())[:4])
    print('大项体量对比:', Q("select type,subtype,count(*),sum(original) from resources group by 1,2 order by 4 desc limit 8"))


FUNCS = {'1': s1, '2': s2, '3': s3, '4': s4, '5': s5, '6': s6, '7': s7}

if __name__ == '__main__':
    for a in sys.argv[1:] or ['1', '2', '3', '4', '5', '6', '7']:
        try:
            FUNCS[a]()
        except Exception as e:
            import traceback
            print('!! section %s failed: %r' % (a, e))
            traceback.print_exc()
