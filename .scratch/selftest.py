import struct, sys, os
sys.path.insert(0, r'D:\TLGL\.scratch')
import pakunpack as P
from pakdec import dec as dec_ref, parse_index

tot = 0
for p in ['data1.pak', 'data2.pak', 'data4.pak', 'data_1.pak']:
    f, recs = parse_index(r'D:\TLGL' + '\\' + p)
    n = 0
    for rec in recs:
        if not (rec['flags'] & 4) or rec['size'] < 16:
            continue
        f.seek(rec['off']); raw = f.read(rec['size'])
        a = P.decrypt(rec['hash'], rec['size'], raw)
        b = dec_ref(rec['hash'], rec['size'], raw)
        assert a == b, (p, rec['i'], a[:16].hex(), b[:16].hex())
        n += 1
        if n >= 25:
            break
    print(p, 'identical on', n, 'records')
    tot += n
print('total checked', tot)
