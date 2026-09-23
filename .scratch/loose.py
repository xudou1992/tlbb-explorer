"""Extract every JPAK entry that carries a manifest path (Index.flags bit0)."""
import json
import mmap
import os
import struct
import sys

sys.path.insert(0, r'D:\TLGL\.scratch')
import cramjam
from pakunpack2 import REC, crc, decrypt, walk_generations

OUT = r'D:\TLGL\.scratch\out'
PAKS = ['data.pak', 'data1.pak', 'data2.pak', 'data3.pak', 'data4.pak', 'data_1.pak']
rows = []
done = bad = 0
for p in PAKS:
    path = r'D:\TLGL' + '\\' + p
    stem = os.path.splitext(p)[0]
    with open(path, 'rb') as f:
        data = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        for gi, gen in enumerate(walk_generations(data)):
            rp, cnt = gen[0], gen[1]
            for i in range(cnt):
                r = data[rp + i * 36:rp + i * 36 + 36]
                h, off, size, occ, ofsz, ver, fl, me, fcrc, ucrc = REC.unpack(r)
                if not (fl & 1) or size == 0:
                    continue
                raw = data[off:off + size]
                if crc(raw) != fcrc:
                    bad += 1
                    continue
                body = decrypt(h, size, raw) if fl & 4 else bytes(raw)
                pl = body[0]
                pth = body[1:1 + pl].split(b'\x00')[0].rstrip(b' ').decode('mbcs', 'replace')
                mver, mft, mcrc = struct.unpack_from('<IQI', body, 1 + pl)
                body = body[1 + pl + 16:]
                if me == 0:
                    out = body
                elif me == 0x33:
                    out = bytes(cramjam.snappy.decompress_raw(body))
                else:
                    print('meth', me, pth)
                    continue
                okcrc = crc(out) == mcrc
                done += 1
                dest = os.path.join(OUT, 'loose', pth.replace('\\', '/'))
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with open(dest, 'wb') as o:
                    o.write(out)
                rows.append(dict(hash=format(h, '016x'), pak=stem, gen=gi, path=pth, size=size,
                                 osize=ofsz, written=len(out), flags=fl, meth=me, crc_ok=okcrc,
                                 mver=mver, filetime=struct.unpack('<q', struct.pack('<Q', mft))[0]))
        data.close()

with open(os.path.join(OUT, 'loose_index.json'), 'w', encoding='utf-8') as f:
    json.dump(rows, f, indent=1, ensure_ascii=False)
print('extracted %d named files, crc ok %d/%d, bad %d' % (
    done, sum(1 for r in rows if r['crc_ok']), done, bad))
for r in rows:
    print('  %-58s %9d -> %9d  %s' % (r['path'], r['size'], r['osize'], 'CRC-OK' if r['crc_ok'] else 'CRC-BAD'))
