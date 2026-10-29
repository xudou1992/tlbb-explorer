# 第 13 条「播放锚」全库级证据重跑（同 anchor_vs_tear.py 的抽样与尺子，
# 只把 EXE/ROOT 换成绝对路径、输出写进 verify13，不覆盖 .scratch/dyn/anchor_vs_tear.txt）。
import io, os, re, subprocess, statistics

EXE = r'D:/TLGL/tlbb-explorer/target/debug/stretch_probe.exe'
ROOT = r'D:/TLGL/.scratch/out/tree'
OUT = r'D:/TLGL/.scratch/dyn/verify13/13_anchor_vs_tear_re.txt'

paths = {}
for line in io.open(r'D:/TLGL/.scratch/dyn/mixcensus.tsv', encoding='utf-8'):
    p = line.rstrip('\n').split('|')
    if len(p) < 8 or p[0] == 'file':
        continue
    stem = os.path.splitext(os.path.basename(p[0]))[0]
    if stem not in paths:
        paths[stem] = p[0].replace('\\', '/')

torn = []
for line in io.open(r'D:/TLGL/.scratch/census_signatures.tsv', encoding='utf-8'):
    q = line.rstrip('\n').split('|')
    if len(q) < 6 or q[0] == 'file':
        continue
    if q[0] in paths and float(q[4]) > 2.0:
        torn.append((float(q[4]), q[0]))
torn.sort(reverse=True)
picked = [s for _, s in torn[:70]] + [s for _, s in torn[len(torn) // 2:][:20]]

row = re.compile(r'^\s*\d+\s*\|\s*(\d+)/(\d+)/([\d.]+)\s*\|\s*(\d+)/(\d+)/([\d.]+)\s*\|\s*(\d+)/(\d+)/([\d.]+)')
res = {'frame0': [], 'bind': [], 'bind_rest': []}
skipped = 0
out = io.open(OUT, 'w', encoding='utf-8', newline='')
out.write('抽样 %d 份撕的（peak>2，全库可量 1,884 份）\n' % len(picked))
for st in picked:
    mesh = os.path.join(ROOT, paths[st])
    ad = os.path.join(os.path.dirname(mesh), 'ani')
    if not os.path.isdir(ad):
        skipped += 1
        continue
    ani = sorted(os.path.join(ad, f) for f in os.listdir(ad) if f.lower().endswith('.ani'))
    if not ani:
        skipped += 1
        continue
    r = subprocess.run([EXE, '--mesh=' + mesh, '--ani=' + ani[0], '--step=2'],
                       capture_output=True, text=True, errors='replace')
    mx = {'frame0': 0.0, 'bind': 0.0, 'bind_rest': 0.0}
    got = 0
    for ln in r.stdout.splitlines():
        m = row.match(ln)
        if not m:
            continue
        got += 1
        for k, i in (('frame0', 2), ('bind', 5), ('bind_rest', 8)):
            mx[k] = max(mx[k], float(m.group(i)))
    if not got:
        skipped += 1
        continue
    for k in res:
        res[k].append(mx[k])
    out.write('%-46s 帧 %2d · frame0 %8.2f · bind %8.2f · bind+rest %8.2f\n'
              % (st, got, mx['frame0'], mx['bind'], mx['bind_rest']))
out.write('\n跳过 %d 份（没有 ani 目录或解不出表）· 有效 %d 份\n' % (skipped, len(res['frame0'])))
n = len(res['frame0'])
for k in ('frame0', 'bind', 'bind_rest'):
    v = sorted(res[k])
    q = lambda f: v[min(int(len(v) * f), len(v) - 1)]
    out.write('%-10s 中位 %7.2f · p75 %7.2f · p90 %7.2f · <=2 的份数 %d/%d\n'
              % (k, q(0.5), q(0.75), q(0.9), sum(1 for x in v if x <= 2.0), n))
out.close()
print('anchor rerun done, valid=%d skipped=%d' % (n, skipped))
