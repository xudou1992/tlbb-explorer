import struct, sys, binascii
sys.path.insert(0, r'D:\TLGL\.scratch')
from pakdec import parse_index, dec
from snappy import snappy_decode, SnappyError, _read_varint

M = 0xFFFFFFFF
CR = binascii.crc32


def open_record(f, rec):
    f.seek(rec['off'])
    raw = f.read(rec['size'])
    if len(raw) < rec['size']:
        return None
    d = dec(rec['hash'], rec['size'], raw) if (rec['flags'] & 4) else raw
    man = None
    if rec['flags'] & 1:
        pl = d[0]
        path = d[1:1 + pl]
        a, b, c = struct.unpack('<IQI', d[1 + pl:1 + pl + 16])
        man = (path, a, b, c)
        d = d[1 + pl + 16:]
    return d, man, raw


ok = fail = 0
for p in ['data1.pak', 'data.pak', 'data2.pak', 'data3.pak', 'data4.pak', 'data_1.pak']:
    f, recs = parse_index(r'D:\TLGL' + '\\' + p)
    print('===', p, len(recs))
    shown = 0
    for rec in recs:
        if rec['size'] == 0:
            continue
        try:
            d, man, raw = open_record(f, rec)
        except Exception as e:
            print('  rec%-4d READ-FAIL %s' % (rec['i'], e))
            continue
        stored_crc = CR(raw) & M
        try:
            f.seek(rec['off'] + 8)  # nothing
        except Exception:
            pass
        if man:
            print('  man path=%r f1=%08x ft=%x crc=%08x' % (man[0][:40], man[1], man[2], man[3]))
        if rec['meth'] == 0:
            tag = 'stored'
            outlen = len(d)
        elif rec['meth'] == 51:
            try:
                out, consumed = snappy_decode(d, rec['osize'])
                tag = 'SNAPPY-OK (%d/%d bytes consumed of %d)' % (consumed, len(d), len(d))
                outlen = len(out)
                ok += 1
            except SnappyError as e:
                tag = 'SNAPPY-FAIL %s' % e
                fail += 1
        else:
            tag = 'meth=%d ???' % rec['meth']
            outlen = -1
        if shown < 6:
            head = (d[:20] if rec['meth'] == 51 else b'')
            print('  rec%-4d flg=%02x met=%-3d size=%8d osize=%10d occ=%9d | %s | %r' % (
                rec['i'], rec['flags'], rec['meth'], rec['size'], rec['osize'], rec['occ'], tag, head))
            shown += 1
print('snappy ok=%d fail=%d' % (ok, fail))
