import struct, sys
sys.path.insert(0, r'D:\TLGL\.scratch')
from pakdec import parse_index, dec, crc

for p in ['data1.pak', 'data.pak', 'data2.pak']:
    f, recs = parse_index(r'D:\TLGL' + '\\' + p)
    print('===', p)
    shown = 0
    for rec in recs:
        if shown >= 8:
            break
        f.seek(rec['off']); raw = f.read(rec['size'])
        d = dec(rec['hash'], rec['size'], raw) if (rec['flags'] & 4) else raw
        raw0, = struct.unpack('<I', raw[:4])
        d0, = struct.unpack('<I', d[:4])
        if rec['meth'] != 0:
            print('rec%-4d flg=%02x met=%d size=%8d osize=%9d raw0=%08x dec0=%08x occ=%8d ver=%d' % (
                rec['i'], rec['flags'], rec['meth'], rec['size'], rec['osize'], raw0, d0, rec['occ'], rec['ver']))
            print('    raw[0:16] = %s' % raw[:16].hex())
            print('    dec[4:24] = %r' % d[4:24])
            shown += 1
