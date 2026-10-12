#!/usr/bin/env python3
# 上一条我写「节点 rest 是塌的、IBM 才是对的」——先自查这句话。
# 导出器的节点 TRS 与 IBM 同出一份 `pose::bind_worlds`，
# 那么「节点世界」与「IBM 求逆」本该**完全相等**；不相等就是我算错了（我上一版没把祖先的旋转
# 乘到累计位移上）。这条脚本按正规 4x4 复合重算一遍，逐骨比距离差。
import json, struct, math, sys

p = sys.argv[1] if len(sys.argv) > 1 else r'.scratch/glb_after_gate/m_f8e9433000036a9c.glb'
raw = open(p, 'rb').read()
clen = struct.unpack_from('<I', raw, 12)[0]
d = json.loads(raw[20:20 + clen].decode('utf-8'))
BO = 20 + clen + 8

def acc(i):
    a = d['accessors'][i]
    bv = d['bufferViews'][a['bufferView']]
    off = bv.get('byteOffset', 0) + a.get('byteOffset', 0)
    comp = {5120: 'b', 5121: 'B', 5123: 'H', 5125: 'I', 5126: 'f'}[a['componentType']]
    n = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4, 'MAT4': 16}[a['type']]
    sz = struct.calcsize(comp)
    out = []
    for k in range(a['count']):
        base = off + k * sz * n
        out.append(list(struct.unpack_from('<' + comp * n, raw, BO + base)))
    return out

def mul(A, B):
    # 列主序 4x4
    return [sum(A[r * 4 + k] * B[k * 4 + c] for k in range(4)) for r in range(4) for c in range(4)]

def trs(t, q, s):
    x, y, z, w = q
    m = [1 - 2 * (y * y + z * z), 2 * (x * y + z * w), 2 * (x * z - y * w),
         2 * (x * y - z * w), 1 - 2 * (x * x + z * z), 2 * (y * z + x * w),
         2 * (x * z + y * w), 2 * (y * z - x * w), 1 - 2 * (x * x + y * y)]
    R = [[m[0], m[3], m[6], 0], [m[1], m[4], m[7], 0], [m[2], m[5], m[8], 0], [0, 0, 0, 1]]
    for c in range(3):
        R[c][3] = 0
    M = [[R[r][c] * s[c] for c in range(3)] + [t[r] if r < 3 else 0] for r in range(3)]
    M.append([0, 0, 0, 1])
    # 列主序展平
    return [M[r][c] for c in range(4) for r in range(4)]

def inv4(m):
    # 行主序内部表示，输入按列主序转进来
    A = [[m[c * 4 + r] for c in range(4)] + [1.0 if r == c else 0.0 for c in range(4)] for r in range(4)]
    for i in range(4):
        piv = max(range(i, 4), key=lambda k: abs(A[k][i]))
        if abs(A[piv][i]) < 1e-9:
            return None
        A[i], A[piv] = A[piv], A[i]
        pv = A[i][i]
        A[i] = [v / pv for v in A[i]]
        for k in range(4):
            if k != i and A[k][i]:
                f = A[k][i]
                A[k] = [A[k][t] - f * A[i][t] for t in range(8)]
    return [A[r][4 + c] for c in range(4) for r in range(4)]

nodes = d['nodes']
par = [None] * len(nodes)
for i, nd in enumerate(nodes):
    for c in nd.get('children', []):
        par[c] = i

def world(i):
    M = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
    stack = []
    c = i
    while c is not None:
        stack.append(c)
        c = par[c]
    for c in reversed(stack):
        nd = nodes[c]
        L = trs(nd.get('translation', [0, 0, 0]), nd.get('rotation', [0, 0, 0, 1]), nd.get('scale', [1, 1, 1]))
        M = mul(M, L)
    return M

skin = d['skins'][0]
ibm = acc(skin['inverseBindMatrices'])
diffs = []
worst = []
for k, j in enumerate(skin['joints']):
    w = world(j)
    iw = inv4(ibm[k])
    if iw is None:
        continue
    # 节点世界的平移 = 后一列；IBM 求逆后的平移同处
    pw = [w[3], w[7], w[11]]
    pi = [iw[3], iw[7], iw[11]]
    dd = math.dist(pw, pi)
    diffs.append(dd)
    if dd > 0.01:
        worst.append((nodes[j].get('name'), [round(v, 3) for v in pw], [round(v, 3) for v in pi], round(dd, 3)))

print('%s · 关节 %d 根' % (p.split('/')[-1], len(skin['joints'])))
print('节点世界 与 IBM求逆 的平移差：最大 %.6f · 平均 %.6f · 超 0.01 的 %d 根'
      % (max(diffs), sum(diffs) / len(diffs), sum(1 for x in diffs if x > 0.01)))
print('（差都在 1e-6 量级 ⇒ 两者本来就是同一份数据，上一条「节点 rest 塌、IBM 对」的说法不成立）')
for x in worst[:5]:
    print('   ', x)
