import sys
sys.path.insert(0, r'D:\TLGL\.scratch')
from pakunpack import read_index

for p in ['data.pak', 'data1.pak', 'data2.pak', 'data3.pak', 'data4.pak', 'data_1.pak']:
    k = read_index(r'D:\TLGL' + '\\' + p)
    rs = k['recs']
    mn = min(r['off'] for r in rs)
    mx = max(r['off'] + r['occ'] for r in rs)
    contig = all(rs[i + 1]['off'] == rs[i]['off'] + rs[i]['occ'] for i in range(len(rs) - 1))
    spans = sorted((r['off'], r['off'] + r['occ']) for r in rs)
    print('%-11s n=%d  off range 0x%x..0x%x  contiguous=%s  cover=%.1fMB' % (
        p, k['n'], mn, mx, contig, (mx - mn) / 1e6))
    if not contig:
        gaps = []
        prev = None
        for a, b in spans:
            if prev is not None and a != prev:
                gaps.append((prev, a, a - prev))
            prev = max(prev or 0, b)
        print('   gaps:', len(gaps), gaps[:6])
