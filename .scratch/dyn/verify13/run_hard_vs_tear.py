# 第 11 条「硬权重无混合」的分档表重跑：连本轮新生成的 mixcensus_re.tsv（不是旧档），
# 输出写进 verify13，不覆盖 .scratch/dyn/hard_vs_tear.txt。
import io, os, statistics

OUT = r'D:/TLGL/.scratch/dyn/verify13/11_hard_vs_tear_re.txt'
MIX = r'D:/TLGL/.scratch/dyn/verify13/mixcensus_re.tsv'   # 本轮重跑出来的全库明细

cen = {}
dup = 0
for line in io.open(r'D:/TLGL/.scratch/census_signatures.tsv', encoding='utf-8'):
    p = line.rstrip('\n').split('|')
    if len(p) < 6 or p[0] == 'file':
        continue
    stem = p[0]
    try:
        peak = float(p[4])
    except ValueError:
        continue
    if stem in cen:
        dup += 1
        continue
    cen[stem] = (peak, p[1])

rows = []
nokey = 0
for line in io.open(MIX, encoding='utf-8'):
    p = line.rstrip('\n').split('|')
    if len(p) < 8 or p[0] == 'file':
        continue
    stem = os.path.splitext(os.path.basename(p[0]))[0]
    if stem not in cen:
        nokey += 1
        continue
    covered, hard, multi, frac = int(p[3]), int(p[5]), int(p[6]), int(p[7])
    if covered == 0:
        continue
    rows.append((cen[stem][0], hard / covered, multi / covered, frac / covered, covered, stem))

out = io.open(OUT, 'w', encoding='utf-8', newline='')
out.write('可连上的份数 %d（census %d 份、mixcensus 里没配上的 %d 份、census 重名 %d 份）\n'
          % (len(rows), len(cen), nokey, dup))
if not rows:
    out.write('一行都没连上，下面不写\n')
    out.close()
    raise SystemExit

buckets = [(0.0, 0.01), (0.01, 0.10), (0.10, 0.30), (0.30, 0.60), (0.60, 0.90), (0.90, 1.01)]
out.write('硬权重占比分档 → 撕裂峰值（现口径 peak）\n')
out.write('档            份数  撕(peak>2)  中位peak  p90peak   多骨占比中位  小数权重占比中位\n')
for lo, hi in buckets:
    g = [r for r in rows if lo <= r[1] < hi]
    if not g:
        continue
    pk = sorted(r[0] for r in g)
    torn = sum(1 for r in g if r[0] > 2.0)
    q = lambda f: pk[min(int(len(pk) * f), len(pk) - 1)]
    out.write('%4.2f~%4.2f  %5d  %5d (%4.1f%%)  %7.2f  %8.2f     %8.3f       %8.3f\n'
              % (lo, hi, len(g), torn, 100.0 * torn / len(g), q(0.5), q(0.9),
                 statistics.median(r[2] for r in g), statistics.median(r[3] for r in g)))

calm = [r for r in rows if r[0] <= 1.05]
wild = [r for r in rows if r[0] > 2.0]
if calm:
    out.write('不撕（peak<=1.05）%d 份：硬权重占比中位 %.3f · 多骨占比中位 %.3f · 带表顶点中位 %.0f\n'
              % (len(calm), statistics.median(r[1] for r in calm),
                 statistics.median(r[2] for r in calm), statistics.median(r[4] for r in calm)))
if wild:
    out.write('撕（peak>2）   %d 份：硬权重占比中位 %.3f · 多骨占比中位 %.3f · 带表顶点中位 %.0f\n'
              % (len(wild), statistics.median(r[1] for r in wild),
                 statistics.median(r[2] for r in wild), statistics.median(r[4] for r in wild)))
out.close()
print('hard_vs_tear rerun written')
