# 把「逐份撕裂峰值」(census_signatures.tsv) 和「逐份硬权重/混合权重计数」(mixcensus.tsv)
# 按干名连起来，验一条机制假设：撕的是不是**硬权重为主**的那批部件。
#   机制预言：hard/covered 越高越撕；混合多骨顶点占主导的部件不该撕。
# 连不上/重名的份数如实报出来，不藏。
import io, os, statistics

cen = {}
dup = 0
for line in io.open(r'.scratch/census_signatures.tsv', encoding='utf-8'):
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
for line in io.open(r'.scratch/dyn/mixcensus.tsv', encoding='utf-8'):
    p = line.rstrip('\n').split('|')
    if len(p) < 8 or p[0] == 'file':
        continue
    stem = os.path.splitext(os.path.basename(p[0]))[0]
    if stem not in cen:
        nokey += 1
        continue
    covered = int(p[3])
    hard = int(p[5])
    multi = int(p[6])
    frac = int(p[7])
    if covered == 0:
        continue
    rows.append((cen[stem][0], hard / covered, multi / covered, frac / covered, covered, stem))

out = io.open(r'.scratch/dyn/hard_vs_tear.txt', 'w', encoding='utf-8', newline='')
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

# 反过来问：不撕的那批（peak<=1.05）长什么样
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
out.write('最硬又不撕的 8 份 / 混合多却撕得狠的 8 份（stem · 硬占比 · 多骨占比 · peak）\n')
for r in sorted([x for x in rows if x[0] <= 1.05], key=lambda x: -x[1])[:8]:
    out.write('  %-44s %.3f %.3f %7.2f\n' % (r[5], r[1], r[2], r[0]))
for r in sorted([x for x in rows if x[0] > 2.0], key=lambda x: x[1])[:8]:
    out.write('  %-44s %.3f %.3f %7.2f\n' % (r[5], r[1], r[2], r[0]))
out.close()
print(open(r'.scratch/dyn/hard_vs_tear.txt', encoding='utf-8').read())
