#!/usr/bin/env python3
"""按骨架签名聚类，替掉「剥文件名数族」。
`stretch_census` 现在每份吐两个指纹：skel_sig（这份网格声明的骨名集）、
skin_sig（真的带影响表的那批骨名集）。同一族变体形态共用一副骨架，
所以独立证据要按签名数，而不是按 `_bN` / 部件后缀剥出来的名字。
"""
import collections

rows = []
for line in open('.scratch/census_signatures.tsv', encoding='utf-8').read().splitlines()[1:]:
    p = line.split('|')
    if len(p) < 8:
        continue
    rows.append({'file': p[0], 'verts': int(p[1]), 'skinned': int(p[2]), 'bones': int(p[3]),
                 'peak': float(p[4]), 'world': float(p[5]), 'skel': p[6], 'skin': p[7]})

print('量到的份数：%d' % len(rows))
for key, label in [('skel', '骨架名集指纹'), ('skin', '带表的骨名集指纹'),
                   ('both', '两者组合')]:
    if key == 'both':
        g = collections.Counter((r['skel'], r['skin']) for r in rows)
    else:
        g = collections.Counter(r[key] for r in rows)
    once = sum(1 for v in g.values() if v == 1)
    sizes = collections.Counter(g.values())
    print('%-18s → %4d 组 · 最大组 %3d 份 · 只 1 份的组 %3d 个 · 组大小分布 %s'
          % (label, len(g), max(g.values()), once, dict(sorted(sizes.items()))))

# 组合口径下最大的几组，看成员是不是真的同一角色
g = {}
for r in rows:
    g.setdefault((r['skel'], r['skin']), []).append(r)
print('\n最大的 5 组（组内份数 · 峰值范围 · 成员）：')
for k, v in sorted(g.items(), key=lambda x: -len(x[1]))[:5]:
    peaks = [r['peak'] for r in v]
    print('  %2d 份 · 峰值 %.1f~%.1f× · %s' % (len(v), min(peaks), max(peaks),
                                                ', '.join(r['file'] for r in v[:8]) + (' …' if len(v) > 8 else '')))
