import struct, sys
sys.path.insert(0, r'D:\TLGL\.scratch')
from pakdec import parse_index, dec, crc

for pk in ['data.pak', 'data1.pak']:
    f, recs = parse_index(r'D:\TLGL' + '\\' + pk)
    for rec in recs:
        if rec['meth'] and (rec['flags'] & 4):
            f.seek(rec['off']); raw = f.read(rec['size'])
            d = dec(rec['hash'], rec['size'], raw)
            print('%s rec%-4d flg=%02x met=%d size=%d osize=%d' % (pk, rec['i'], rec['flags'], rec['meth'], rec['size'], rec['osize']))
            print('   head:', d[:64].hex())
            print('   repr:', repr(d[:72]))
            # manifest parse if flags&1
            if rec['flags'] & 1:
                L = d[0]
                print('   L=%d name=%r u32=%s time=%x' % (L, d[1:1+L], d[1+L:5+L].hex(), struct.unpack('<Q', d[5+L:13+L])[0]))
            break
    # also a flags=0 (plaintext) record
    for rec in recs:
        if not (rec['flags'] & 4):
            f.seek(rec['off']); raw = f.read(rec['size'])
            print('%s rec%-4d UNENCRYPTED flg=%02x met=%d size=%d: %r' % (pk, rec['i'], rec['flags'], rec['meth'], rec['size'], raw[:60]))
