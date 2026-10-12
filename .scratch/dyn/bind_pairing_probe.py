#!/usr/bin/env python3
# 名字↔表配错了会是什么样？纯同骨的三角形照样刚体不撕（今天的检验排不掉它），
# 但混合顶点的次权重会落在**身体另一头**的骨上——边被拉到 50 倍正是这个形状。
# 这里做一件很笨但很硬的事：拿 GLB 的节点树算出每根骨的 bind 世界位置，
# 再看「把某个顶点主要带住的那根骨」在距离排名上排第几。
# 蒙皮合理的话，一根骨影响到的顶点应当就长在它附近。
import json, struct, sys, math

p = sys.argv[1] if len(sys.argv) > 1 else r'.scratch/glb_after_gate/m_f8e9433000036a9c.glb'
raw = open(p, 'rb').read()
clen = struct.unpack_from('<I', raw, 12)[0]
d = json.loads(raw[20:20 + clen].decode('utf-8'))
bin_off = 20 + clen + 8
BIN = raw[bin_off:]

def acc(i):
    a = d['accessors'][i]
    bv = d['bufferViews'][a['bufferView']]
    off = bv.get('byteOffset', 0) + a.get('byteOffset', 0)
    n = a['count']
    comp = {5120: 'b', 5121: 'B', 5123: 'H', 5125: 'I', 5126: 'f'}[a['componentType']]
    ncomp = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4, 'MAT4': 16}[a['type']]
    size = struct.calcsize(comp)
    rows = []
    for k in range(n):
        base = off + k * size * ncomp
        rows.append(list(struct.unpack_from('<' + comp * ncomp, BIN, base)))
    return a['componentType'], rows

def q_to_m(x, y, z, w):
    return [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w),
            2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w),
            2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]

def world_pos(idx, parents):
    # 从根往下走一遍，只取平移
    path = []
    c = idx
    while c is not None:
        path.append(c)
        c = parents[c]
    pos = [0.0, 0.0, 0.0]
    for c in reversed(path):
        nd = d['nodes'][c]
        t = nd.get('translation', [0, 0, 0])
        r = nd.get('rotation', [0, 0, 0, 1])
        s = nd.get('scale', [1, 1, 1])
        m = q_to_m(*r)
        v = [t[0] * s[0], t[1] * s[1], t[2] * s[2]]
        np_ = [sum(m[row * 3 + col] * v[col] for col in range(3)) for row in range(3)]
        pos = [pos[k] + np_[k] for k in range(3)]
    return pos

nodes = d['nodes']
parents = [None] * len(nodes)
for i, nd in enumerate(nodes):
    for c in nd.get('children', []):
        parents[c] = i

def inv4(m):
    # 一般 4x4 求逆（列主序 16 元），高斯-约当
    a = [[m[c * 4 + r] if False else m[r * 4 + c] for c in range(4)] + [1.0 if r == c else 0.0 for c in range(4)] for r in range(4)]
    for i in range(4):
        p_ = max(range(i, 4), key=lambda k: abs(a[k][i]))
        if abs(a[p_][i]) < 1e-9:
            return None
        a[i], a[p_] = a[p_], a[i]
        pv = a[i][i]
        a[i] = [v / pv for v in a[i]]
        for k in range(4):
            if k == i:
                continue
            f = a[k][i]
            if f:
                a[k] = [a[k][t] - f * a[i][t] for t in range(8)]
    return [a[r][4 + c] for r in range(4) for c in range(4)]

skin = d['skins'][0]
joint_nodes = skin.get('joints') or skin.get('joint', [])
# **骨位要从 inverseBindMatrices 求逆拿**，不是从节点 TRS：
# 实测这份 GLB 的节点 rest 是塌的（000/bip01/pelvis/spine/spine1 全在 [0,0,0]），
# 蒙皮真正用的是 IBM——节点 TRS 塌掉也正是「SkeletonHelper 骨线乱飘」那桩旧案。
_, ibm = acc(skin['inverseBindMatrices'])
binds = []
for row in ibm:
    m = row[:16] if len(row) == 16 else None
    iv = inv4(m) if m else None
    binds.append([iv[12], iv[13], iv[14]] if iv else [0.0, 0.0, 0.0])
names = [nodes[j].get('name', str(j)) for j in joint_nodes]
print('%s · 关节 %d 根 · skin 数 %d' % (p.split('/')[-1], len(joint_nodes), len(d['skins'])))

rank_hist = {}
own_d, best_d = [], []
worst = []
for mi, m in enumerate(d['meshes']):
    for pr in m['primitives']:
        at = pr['attributes']
        if 'JOINTS_0' not in at or 'POSITION' not in at:
            continue
        _, pos = acc(at['POSITION'])
        _, ji = acc(at['JOINTS_0'])
        _, we = acc(at['WEIGHTS_0'])
        for v in range(len(pos)):
            js = ji[v] if len(ji[v]) == 4 else [ji[v][0], ji[v][0], ji[v][0], ji[v][0]]
            ws = we[v]
            k = max(range(4), key=lambda x: ws[x])
            if ws[k] < 0.99:
                continue
            dom = js[k]
            px, py, pz = pos[v][0], pos[v][1], pos[v][2]
            ds = [(math.dist([px, py, pz], binds[i]), i) for i in range(len(binds))]
            ds.sort()
            rank = next((r + 1 for r, (_, i) in enumerate(ds) if i == dom), 0)
            rank_hist[rank] = rank_hist.get(rank, 0) + 1
            own = math.dist([px, py, pz], binds[dom])
            own_d.append(own)
            best_d.append(ds[0][0])
            if rank >= 4:
                worst.append((names[dom], rank, round(own, 2), names[ds[0][1]], round(ds[0][0], 2)))

n = sum(rank_hist.values())
print('纯同骨顶点（主权重≥0.99）%d 个' % n)
for r in sorted(rank_hist):
    print('  主权重骨按 bind 距离排名 第 %d 名：%d 个（%.1f%%）' % (r, rank_hist[r], 100.0 * rank_hist[r] / max(1, n)))
print('到「自己那根骨」的平均距离 %.3f · 到最近那根骨的平均距离 %.3f' % (sum(own_d) / n, sum(best_d) / n))
print('排到第 4 名开外的例子（前 6）：')
for x in worst[:6]:
    print('   ', x)
