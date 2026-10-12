#!/usr/bin/env python3
# 数一数「救回来的 271 份 GLB」里有多少其实整张网格不吃骨架，并分清原因：
# 是 .mesh 里没有影响表，还是表有、骨名对不上骨架被整条跳过。
# 数据不猜：导出器把对账数字写进了每份 GLB 的 asset.extras（gltf.rs::rig_stats_json）。
import json, struct, os, glob, sys

SRC = sys.argv[1] if len(sys.argv) > 1 else '.scratch/glb_sidecar'
OUT = '.scratch/glb_sidecar_coverage.json'
RPT = '.scratch/glb覆盖度普查_20261012.txt'

def glb_json(path):
    with open(path, 'rb') as f:
        magic, ver, length = struct.unpack('<4sII', f.read(12))
        assert magic == b'glTF', path
        clen, ctype = struct.unpack('<I4s', f.read(8))
        assert ctype == b'JSON', path
        return json.loads(f.read(clen).decode('utf-8'))

rows = []
for p in sorted(glob.glob(SRC + '/*.glb')):
    d = glb_json(p)
    ex = (d.get('asset') or {}).get('extras') or {}
    rig = ex.get('rig') or {}
    vc = 0
    for mesh in d.get('meshes', []):
        for prim in mesh.get('primitives', []):
            a = prim.get('attributes', {})
            if 'POSITION' in a:
                vc = max(vc, d['accessors'][a['POSITION']]['count'])
    rows.append({
        'file': os.path.basename(p), 'mesh': ex.get('mesh') or '',
        'hasRig': bool(rig), 'joints': rig.get('joints'), 'verts': vc,
        'covered': rig.get('coveredVertices'), 'uncovered': rig.get('uncoveredVertices'),
        'rootFill': rig.get('rootFillVertices'),
        'infNotInHier': len(rig.get('influenceNodesNotInHierarchy') or []),
        'bonesWithoutBind': len(rig.get('bonesWithoutBind') or []) if isinstance(rig.get('bonesWithoutBind'), list) else rig.get('bonesWithoutBind'),
        'anims': len(rig.get('animations') or []),
        'tracks': sum((a.get('exportedTracks') or 0) for a in (rig.get('animations') or [])),
    })

L = []
def w(s):
    L.append(s)

rigid = [r for r in rows if r['hasRig'] and (r['covered'] or 0) == 0]
part = [r for r in rows if r['hasRig'] and (r['covered'] or 0) > 0 and (r['uncovered'] or 0) > 0]
full = [r for r in rows if r['hasRig'] and (r['covered'] or 0) > 0 and (r['uncovered'] or 0) == 0]
norig = [r for r in rows if not r['hasRig']]

w('GLB 总数 %d' % len(rows))
w('  带 rig 对账: %d | extras 里没有 rig: %d' % (len(rows) - len(norig), len(norig)))
w('  覆盖 0 个顶点（整张挂根骨，播放时网格一动不动）: %d' % len(rigid))
w('  部分覆盖: %d | 全覆盖: %d' % (len(part), len(full)))
w('')

# 原因分清：0 覆盖到底是「没有影响表」还是「表有但骨名对不上被跳过」
a_no_table = [r for r in rigid if r['infNotInHier'] == 0]
a_skip = [r for r in rigid if r['infNotInHier'] > 0]
w('0 覆盖的 %d 份按原因分：' % len(rigid))
w('  影响表整条因骨名不在骨架里被跳过（influenceNodesNotInHierarchy>0）: %d' % len(a_skip))
w('  连被跳过的影响表都没有（.mesh 里就没有权重表 或 名字全对但表空）: %d' % len(a_no_table))
w('')

# 覆盖率分布（只看有覆盖的）
ratios = sorted([r['covered'] / r['verts'] for r in rows if r['hasRig'] and r['verts'] and r['covered']])
if ratios:
    import statistics
    w('有覆盖的那些，顶点被骨架真正带动的比例：')
    for q in (0.1, 0.25, 0.5, 0.75, 0.9):
        i = min(len(ratios) - 1, int(q * len(ratios)))
        w('  P%02d = %.3f' % (int(q * 100), ratios[i]))
    w('  均值 = %.3f · ≥90%% 的有 %d 份' % (statistics.fmean(ratios), sum(1 for x in ratios if x >= .9)))
w('')
w('0 覆盖 且 带动画（导出后骨头乱飘、网格不跟）的：')
for r in sorted([x for x in rigid if x['anims'] > 0], key=lambda x: -x['verts']):
    w('  %-44s 顶点 %6d 关节 %3d 动作 %2d 导出轨道 %5d 跳过的影响节点 %d' % (
        r['mesh'] or r['file'], r['verts'] or 0, r['joints'] or 0, r['anims'], r['tracks'], r['infNotInHier']))
w('')
w('0 覆盖 且 没带动画的：%d 份（列前 20）' % len([x for x in rigid if x['anims'] == 0]))
for r in sorted([x for x in rigid if x['anims'] == 0], key=lambda x: -x['verts'])[:20]:
    w('  %-44s 顶点 %6d 关节 %3d' % (r['mesh'] or r['file'], r['verts'] or 0, r['joints'] or 0))

open(RPT, 'w', encoding='utf-8').write('\n'.join(L) + '\n')
json.dump(rows, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('wrote %s (%d lines) and %s' % (RPT, len(L), OUT))
