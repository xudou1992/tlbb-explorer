# 第 12 条「表挂错骨 off-by-one」重跑：与 .scratch/dyn/pairing_batch.py 同一套抽样
# （读现有的 mixcensus.tsv 选可量文件 + census_signatures.tsv 的 peak 分撕/不撕），
# 只是把 stretch_probe 换成绝对路径、明细写到 verify13，不覆盖 .scratch/dyn 里的原档。
import io, os, subprocess, statistics

EXE = r'D:/TLGL/tlbb-explorer/target/debug/stretch_probe.exe'
ROOT = r'D:/TLGL/.scratch/out/tree'
OUT = r'D:/TLGL/.scratch/dyn/verify13/pairing_batch_re.txt'

# mixcensus.tsv: relpath|nodes|withSkin|covered|verts|hard|multi|frac
paths = {}
for line in io.open(r'D:/TLGL/.scratch/dyn/mixcensus.tsv', encoding='utf-8'):
    p = line.rstrip('\n').split('|')
    if len(p) < 8 or p[0] == 'file':
        continue
    stem = os.path.splitext(os.path.basename(p[0]))[0]
    if int(p[2]) >= 2 and stem not in paths:
        paths[stem] = p[0].replace('\\', '/')

torn, calm, picked = [], [], []
for line in io.open(r'D:/TLGL/.scratch/census_signatures.tsv', encoding='utf-8'):
    q = line.rstrip('\n').split('|')
    if len(q) < 6 or q[0] == 'file':
        continue
    st, pk = q[0], float(q[4])
    if st not in paths:
        continue
    (torn if pk > 2.0 else calm).append(st)
picked = torn[:60] + calm[:20]

out = io.open(OUT, 'w', encoding='utf-8', newline='')
out.write('抽样 %d 份（撕的 %d + 不撕的 %d，全库带 >=2 张表的可量文件共 %d）\n'
          % (len(picked), len(torn), len(calm), len(paths)))
res = {'self': [], 'prev': [], 'next': []}
win = {'self': 0, 'prev': 0, 'next': 0}
bad = 0
for st in picked:
    mesh = os.path.join(ROOT, paths[st])
    ad = os.path.join(os.path.dirname(mesh), 'ani')
    if not os.path.isdir(ad):
        continue
    ani = sorted(os.path.join(ad, f) for f in os.listdir(ad) if f.lower().endswith('.ani'))
    if not ani:
        continue
    r = subprocess.run([EXE, '--mesh=' + mesh, '--ani=' + ani[0], '--pairing'],
                       capture_output=True, text=True, errors='replace')
    ln = next((l for l in r.stdout.splitlines() if l.startswith('PAIR|')), None)
    if not ln:
        bad += 1
        continue
    _, _, n, m0, m1, m2, scale = ln.split('|')
    v = [float(m0), float(m1), float(m2)]
    if any(x != x for x in v):
        bad += 1
        continue
    res['self'].append(v[0]); res['prev'].append(v[1]); res['next'].append(v[2])
    k = min(range(3), key=lambda i: v[i])
    win[['self', 'prev', 'next'][k]] += 1
    out.write('%-46s 表 %2s 原配 %.4f 挪前 %.4f 挪后 %.4f 骨长 %.4f\n'
              % (st, n, v[0], v[1], v[2], float(scale)))
n = len(res['self'])
out.write('\n判读（%d 份有效、%d 份没跑出数）：\n' % (n, bad))
for k in ('self', 'prev', 'next'):
    out.write('  %-5s 中位 %.4f · p90 %.4f · 最小占 %d/%d\n'
              % (k, statistics.median(res[k]), sorted(res[k])[int(n * 0.9) % n], win[k], n))
out.close()
print('pairs done, valid=%d bad=%d' % (n, bad))
