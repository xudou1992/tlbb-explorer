import sys
sys.path.insert(0, r'D:\TLGL\.scratch')
from pakunpack import read_index

tot = cnt = 0
for p in ['data.pak', 'data1.pak', 'data2.pak', 'data3.pak', 'data4.pak', 'data_1.pak']:
    k = read_index(r'D:\TLGL' + '\\' + p)
    s = sum(r['osize'] for r in k['recs'])
    c = sum(r['size'] for r in k['recs'])
    nz = sum(1 for r in k['recs'] if r['size'])
    print('%-11s recs=%4d nonempty=%4d stored=%7.1fMB original=%8.1fMB' % (p, k['n'], nz, c / 1e6, s / 1e6))
    tot += s
    cnt += nz
print('TOTAL nonempty=%d original=%.2f GB' % (cnt, tot / 1e9))
