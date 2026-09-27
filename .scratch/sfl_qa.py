# -*- coding: utf-8 -*-
"""sfl_qa.py — READ-ONLY: Q1 12-file sample tables, Q4 index-shape evidence,
Q5 correlation vs map size. Writes sfl_qa_out.txt + sfl_sample12.md."""
import struct, glob, os, re, random, collections, math
import sfl_fields as F

TREE = r'D:\TLGL\.scratch\out\tree'
FILES = F.FILES
OUT = open(r'D:\TLGL\.scratch\sfl_qa_out.txt', 'w', encoding='utf-8')
def log(*a):
    print(*a, file=OUT)

def fmt_val(c, pl):
    if c in (1, 2, 3, 10, 16):
        return 'f=%.6g i=%d' % (F.f32(pl[0]), pl[0])
    if c in (6, 7, 8):
        return '(' + ', '.join('%.6g' % F.f32(x) for x in pl) + ')'
    return '[' + ', '.join(str(x) for x in pl) + ']'

def sec_stream_lines(d):
    """all record lines with absolute byte offsets"""
    lines = []
    lines.append('  chunk77 @24 hdr%s sub77@44 [39,n=%d,W=%d] z=%d' % (d['h77'], d['n77'], d['W77'], d['h77'][3]))
    for i, c, f, w in d['recs77']:
        lines.append('    @%5d fld %2d/%-3d pw=%d  %s' % (64 + 4 * i, c, f, w, fmt_val(c, d['words77'][i+1:i+1+w])))
    lines.append('  chunk76 @%d hdr%s sub@%d%s' % (d['p76'], d['h76'], d['p76'] + 20, d['sub76']))
    for i, c, f, w in d['recs76']:
        lines.append('    @%5d fld %2d/%-3d pw=%d  %s' % (d['p76'] + 40 + 4 * i, c, f, w, fmt_val(c, d['words76'][i+1:i+1+w])))
    tail = d['words76'][d['stop76']:]
    lines.append('    @%5d tail76(%d words): %s' % (d['p76'] + 40 + 4 * d['stop76'], len(tail), fmt_val(4, tail)))
    if d['h40']:
        lines.append('  chunk40 @%d hdr(z=%d L=%d) sub40@%d %s' % (d['p40'], d['h40'][3], d['h40'][4], d['p40'] + 20, d['sub40']))
        for i, c, f, w in (d['recs40'] or []):
            lines.append('    @%5d fld %2d/%-3d pw=%d  %s' % (d['p40'] + 40 + 4 * i, c, f, w, fmt_val(c, d['words40'][i+1:i+1+w])))
    lines.append('  strtab @%d flag=%d count=%d strings=%s' % (d['strtab'], d['strflag'], len(d['strings']),
                 [s for s, h in d['strings'] if 0 < len(s) < 45][:12]))
    return lines

# ---------- Q1: 12-file sample ----------
random.seed(20260924)
by_pre = collections.defaultdict(list)
for f in FILES:
    m = re.match(r'(w1351_)?(fb|ll|gj|cj|hd|mqts|empt)', os.path.basename(f))
    by_pre[m.group(2)].append(f)
sample = random.sample(by_pre['fb'], 4) + random.sample(by_pre['ll'], 4) + random.sample(by_pre['gj'], 4)
with open(r'D:\TLGL\.scratch\sfl_sample12.md', 'w', encoding='utf-8') as g:
    for f in sample:
        d = F.parse_file(f)
        g.write('\n### %s  (%d bytes)\n\n```text\n' % (os.path.basename(f), d['size']))
        for ln in sec_stream_lines(d):
            g.write(ln + '\n')
        g.write('```\n')
print('sample files:', [os.path.basename(x) for x in sample])

# ---------- Q4: index-shape tests over all 297 ----------
log('===== Q4 index-shape evidence =====')
n_scene = {}
scene_files = {}
for f in FILES:
    d = os.path.dirname(f)
    sc = [p for p in glob.glob(os.path.join(d, '*.scene'))]
    n_scene[f] = len(sc)
    scene_files[f] = sc
cnt_hist = collections.Counter(n_scene.values())
log('scene-count hist:', cnt_hist.most_common(12))
# strtab count vs scene count
pairs_sc = []
# all numeric values in records, checking offset/grid shapes
max_val_seen = 0
offset_like = 0
for f in FILES:
    d = F.parse_file(f)
    allnum = []
    for words in (d['words77'], d['words76'], d['words40'] or ()):
        for w in words:
            allnum.append(w)
    n = d['size']
    for w in allnum:
        max_val_seen = max(max_val_seen, w if w < 0x80000000 else 0)
    if 16 < w < n:
        pass
    # any value equal to scene count?
    sc = n_scene[f]
    if sc in allnum:
        pairs_sc.append((os.path.basename(f), sc))
log('files where some u32 in body == scene-file-count:', len(pairs_sc), pairs_sc[:10])
# monotone non-decreasing offset chains of length>=5 inside [44,size)?
chain_hits = 0
for f in FILES:
    d = F.parse_file(f)
    for words in (d['words77'], d['words76'], d['words40'] or ()):
        run = []
        for w in words:
            if 44 <= w <= d['size'] and w % 4 == 0:
                if not run or w >= run[-1]:
                    run.append(w)
                else:
                    run = [w]
            else:
                run = []
            if len(run) >= 6:
                chain_hits += 1
                break
log('u32 values in [44,size) forming monotone 4-aligned chains >=6:', chain_hits)
# correlation: z40 / L40 / n77 / strtab-count vs scene count
def pearson(xs, ys):
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if sx == 0 or sy == 0:
        return None, mx, my
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy), mx, my
xs, ys = [], []
zz, nn, ss = [], [], []
for f in FILES:
    d = F.parse_file(f)
    xs.append(d['size'])
    ys.append(n_scene[f])
    zz.append(d['h40'][3] if d['h40'] else 0)
    nn.append(d['n77'])
    ss.append(len(d['strings']))
r1, m1, m2 = pearson(xs, ys)
r2, _, _ = pearson(zz, ys)
r3, _, _ = pearson(nn, ys)
r4, _, _ = pearson(ss, ys)
log('corr(sfl size, scene count)=%.3f  mean sfl=%.0f mean scenes=%.1f' % (r1, m1, m2))
log('corr(z40, scene count)=%.3f  corr(n77, scene count)=%.3f  corr(strtab cnt, scene count)=%.3f' % (r2, r3, r4))
log('z40 hist:', collections.Counter(zz).most_common())
# does z40 equal number of cloud texture names?
z_vs_tex = 0
for f in FILES:
    d = F.parse_file(f)
    n_tex = sum(1 for s, h in d['strings'] if s.lower().endswith('.tga'))
    z = d['h40'][3] if d['h40'] else 0
    if z == n_tex:
        z_vs_tex += 1
log('files where z40 == #tga strings:', z_vs_tex)

# ---------- Q5: 10-map scale table ----------
log('\n===== Q5 correlation detail (10 maps) =====')
random.seed(7)
samp10 = random.sample(FILES, 10)
rows = []
for f in samp10:
    dmap = os.path.dirname(f)
    d = F.parse_file(f)
    scenes = glob.glob(os.path.join(dmap, '*.scene'))
    nobj = 0
    nonzero = 0
    for sp in scenes:
        b = open(sp, 'rb').read(12)
        if len(b) >= 4:
            c = struct.unpack_from('<I', b, 0)[0]
            if len(b) == 12 or True:
                hdr = struct.unpack_from('<3I', b, 0) if len(b) >= 12 else (0, 0, 0)
                if hdr[1] in (753, 749):
                    nobj += hdr[0]
                    nonzero += 1 if hdr[0] else 0
    mp = glob.glob(os.path.join(dmap, '*.map'))
    mapw = struct.unpack_from('<6I', open(mp[0], 'rb').read(24), 0) if mp else None
    rows.append((os.path.basename(f), d['size'], d['n77'], d['h40'][3] if d['h40'] else 0,
                 len(d['strings']), len(scenes), nonzero, nobj, mapw))
log('%-46s %6s %4s %4s %4s %6s %5s %7s  map hdr[0..5]' % ('sfl', 'size', 'n77', 'z40', 'str', 'scenes', 'full', 'objs'))
for r in rows:
    log('%-46s %6d %4d %4d %4d %6d %5d %7d  %s' % (r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8]))
for idx, label in ((1, 'size'), (2, 'n77'), (3, 'z40'), (4, 'strcnt')):
    a = [r[idx] for r in rows]
    b = [r[7] for r in rows]
    c = [r[5] for r in rows]
    ra, _, _ = pearson([float(x) for x in a], [float(x) for x in b])
    rc, _, _ = pearson([float(x) for x in a], [float(x) for x in c])
    log('corr(%s) with objs=%.3f scenes=%.3f' % (label, ra, rc))
OUT.close()
print('wrote sfl_qa_out.txt')
