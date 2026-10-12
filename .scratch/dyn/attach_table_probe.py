#!/usr/bin/env python3
# 撕裂的来源已经钉到「这份网格有 20 根骨没有 96B 绑定记录」（stretch_probe 头部行）。
# 那 20 根的骨位到底在不在同一个文件里？同一份 `.mesh` 末尾还有一张挂点表：
# [u32 挂点数][tx_ 名 char[32] + 骨名 char[32] + 矩阵 f32×16]。
# 这里数三件事：96B 记录覆盖了哪些骨名、挂点表点了哪些骨名、GLB 的 83 个关节名里
# 那 20 根缺的有多少在挂点表里出现——出现的那些，值不值钱要再看矩阵像不像骨位。
import json, re, struct, sys

MESH = sys.argv[1] if len(sys.argv) > 1 else r'.scratch/out/sidecar_tree/data\source\npc\quest\w1351_boss_machao\w1351_boss_machao.mesh'
GLB = sys.argv[2] if len(sys.argv) > 2 else r'.scratch/glb_after_gate/m_f8e9433000036a9c.glb'

raw = open(MESH, 'rb').read()
vc = struct.unpack_from('<I', raw, 0x8C)[0]

def mat_at(off):
    if off + 64 > len(raw):
        return None
    f = struct.unpack_from('<16f', raw, off)
    if f[15] != 1.0:
        return None
    rows = [f[0:4], f[4:8], f[8:12]]
    lens = [sum(x * x for x in r) ** .5 for r in rows]
    if min(lens) < 1e-6:
        return None
    dot = lambda a, b: sum(a[i] * b[i] for i in range(4))
    if any(abs(dot(rows[i], rows[j])) > 0.02 * lens[i] * lens[j]
           for i, j in ((0, 1), (0, 2), (1, 2))):
        return None
    return f

# 1) 带 96B 记录的骨名
recorded = {}
for m in re.finditer(rb'[ -~]{3,31}\x00', raw):
    off = m.start()
    if off and 32 <= raw[off - 1] < 127:
        continue
    if raw[off:off + 3].startswith(b'tx_'):
        continue
    f = mat_at(off + 32)
    if f:
        recorded.setdefault(raw[off:off + 32].split(b'\x00')[0].decode('ascii', 'replace'), f)
print('%s · 顶点 %d · 带 96B 记录的骨名 %d 个' % (MESH.split('\\')[-1], vc, len(recorded)))

# 2) 挂点表：tx_ 名 + 骨名 + 矩阵
attach = []
for m in re.finditer(rb'tx_[ -~]{0,28}\x00', raw):
    off = m.start()
    nm = raw[off:off + 32].split(b'\x00')[0].decode('ascii', 'replace')
    bone_bytes = raw[off + 32:off + 64].split(b'\x00')[0]
    bone = bone_bytes.decode('ascii', 'replace')
    f = mat_at(off + 64)
    attach.append((nm, bone, f is not None))
print('挂点表条目 %d 条，其中第三个字段是合法矩阵的 %d 条' % (len(attach), sum(1 for a in attach if a[2])))
for nm, bone, ok in attach[:12]:
    print('   %-18s → %-22s 矩阵%s' % (nm, bone, '合法' if ok else '读不出'))

# 3) GLB 的关节名 = 这份角色实际用的骨架
with open(GLB, 'rb') as f:
    struct.unpack('<4sII', f.read(12))
    clen, ctype = struct.unpack('<I4s', f.read(8))
    d = json.loads(f.read(clen).decode('utf-8'))
joints = set()
for n in d.get('nodes', []):
    if 'name' in n:
        joints.add(n['name'])
skin = d.get('skins', [{}])[0]
joint_idx = skin.get('joint', [])
skeleton = set(d['nodes'][i].get('name', '') for i in joint_idx)
print('GLB 节点名 %d 个 · skin.joint %d 个（raw "tx_" 子串在这份 .mesh 里出现 %d 次）'
      % (len(joints), len(joint_idx), raw.count(b'tx_')))

names = skeleton or joints
missing = sorted(n for n in names if n not in recorded)
att_bones = set(b for _, b, ok in attach if ok)
hit = [n for n in missing if n in att_bones]
print('\n没有 96B 记录的骨：%d 根' % len(missing))
print('其中在挂点表里出现（且那条带合法矩阵）的：**%d 根**' % len(hit))
print('挂点表点到的骨名共 %d 个，其中本来就有 96B 记录的 %d 个' % (len(att_bones), len([x for x in att_bones if x in recorded])))
print('前 20 根缺的：%s' % ', '.join(missing[:20]))
print('挂点表能给上矩阵的那几根：%s' % (', '.join(hit) or '（一个都没有）'))
