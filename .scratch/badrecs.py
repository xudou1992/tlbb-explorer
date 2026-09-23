import os, struct, sys, zlib
sys.path.insert(0, r'D:\TLGL\.scratch')
REC = struct.Struct('<QIIIIHBBII')
from pakunpack2 import walk_generations, crc
import mmap

for p in ['data.pak', 'data1.pak', 'data2.pak', 'data3.pak', 'data4.pak', 'data_1.pak']:
    path = r'D:\TLGL' + '\\' + p
    with open(path, 'rb') as f:
        data = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        bad = []
        for gi, (rp, n, end) in enumerate(walk_generations(data)):
            for i in range(n):
                r = data[rp + i * 36:rp + i * 36 + 36]
                h, off, size, occ, ofsz, ver, fl, me, fcrc, ucrc = REC.unpack(r)
                if crc(r[:32]) != ucrc:
                    bad.append((gi, i, h, off, size, occ, ofsz, ver, fl, me, fcrc, ucrc))
        print('===', p, 'bad records:', len(bad))
        for b in bad[:10]:
            print('   gen%-3d rec%-4d h=%016x off=0x%-8x size=%-8d occ=%-8d ofsz=%-9d ver=%d fl=%02x me=%02x ucrc=%08x' %
                  (b[0], b[1], b[2], b[3], b[4], b[5], b[6], b[7], b[8], b[9], b[11]))
        # distribution by generation
        d = {}
        for b in bad:
            d[b[0]] = d.get(b[0], 0) + 1
        print('   by gen:', dict(sorted(d.items())))
