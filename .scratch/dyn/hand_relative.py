# 手算最小撕裂样本的两块「相对变换」——轨道当局部沿父链复合（现口径），
# 看 ponytail1 与 r_clavicle 这两块在网格自身坐标系里被相对搬/转了多少。
import json, io, math
import numpy as np

d = json.load(io.open(r'.scratch/skel_dump/w1351_monster_guifengzhuangke_lian_001.skel.json', encoding='utf-8'))
o = io.open(r'.scratch/dyn/hand_relative.txt', 'w', encoding='utf-8', newline='')
par = {e['name']: e['parent'] for e in d['parentChain']}
order = list(par)


def ident():
    return np.eye(4)


def trs(q, p, s):
    x, y, z, w = q
    m = np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y + w * z), 2 * (x * z - w * y), 0],
        [2 * (x * y - w * z), 1 - 2 * (x * x + z * z), 2 * (y * z + w * x), 0],
        [2 * (x * z + w * y), 2 * (y * z - w * x), 1 - 2 * (x * x + y * y), 0],
        [0, 0, 0, 1],
    ])
    m[:3, :] *= s
    m[3, :3] = p
    return m


def polar(m):
    a = m[:3, :]
    sv = np.linalg.svd(a, compute_uv=False)
    scale = float(np.prod(sv) ** (1 / 3.0))
    c = (np.trace(a) / scale - 1) / 2 if scale > 0 else 1.0
    ang = math.degrees(math.acos(max(-1.0, min(1.0, c))))
    return ang, scale, float(np.linalg.norm(m[3, :3]))


a = d['animations'][0]
tr = {t['bone']: t for t in a['tracks']}


def world(f):
    W = {}
    for n in order:
        t = tr.get(n)
        L = trs(t['rotations'][f], t['positions'][f], t['scales'][f]) if (t and t['rotations']) else ident()
        p = par.get(n)
        W[n] = L if p is None or p not in W else L @ W[p]
    return W


P, C = 'bip02_ponytail1', 'bip02_r_clavicle'
for nm in (P, C):
    ch, n = [], nm
    while n:
        ch.append(n)
        n = par.get(n)
    o.write('%s 父链: %s\n' % (nm, ' <- '.join(ch)))
W0 = world(0)
o.write('帧 | P 增量(角/缩放/位移) | C 增量(角/缩放/位移) | 相对 R=P·C^-1 (角/缩放/位移)\n')
for f in range(a['frames']):
    Wt = world(f)
    Pp = np.linalg.inv(W0[P]) @ Wt[P]
    Pc = np.linalg.inv(W0[C]) @ Wt[C]
    R = Pp @ np.linalg.inv(Pc)
    a1, s1, t1 = polar(Pp)
    a2, s2, t2 = polar(Pc)
    a3, s3, t3 = polar(R)
    o.write('%2d | %6.1f deg / %.4f / %.4f | %6.1f deg / %.4f / %.4f | %6.1f deg / %.4f / %.4f\n'
            % (f, a1, s1, t1, a2, s2, t2, a3, s3, t3))
rec = {x['name']: x for x in d['nodes']}
for nm in (P, C):
    if nm in rec:
        w = np.linalg.inv(np.array(rec[nm]['bind'], dtype=float).reshape(4, 4))
        o.write('%s · 骨位(bind 逆的平移) %s · 轨道 q0 %s p0 %s s0 %s\n'
                % (nm, [round(float(v), 4) for v in w[3, :3]],
                   [round(float(v), 4) for v in tr[nm]['rotations'][0]],
                   [round(float(v), 4) for v in tr[nm]['positions'][0]],
                   round(float(tr[nm]['scales'][0]), 4)))
    else:
        o.write('%s · 无 96B 记录\n' % nm)
# 两块各自的顶点到底在网格坐标的哪一带（用 bind 位与权重表大小间接看）
for nd in d['nodes']:
    if nd.get('influences'):
        inf = nd['influences']
        o.write('带表 %s · 顶点 %d 个 · 权重去重 %s\n'
                % (nd['name'], len(inf['vertices'] if isinstance(inf, dict) else inf),
                   sorted({round(float(w), 4) for w in (inf['weights'] if isinstance(inf, dict) else [x[1] for x in inf])})))
o.close()
print('ok')
