import struct, sys, zlib, mmap
sys.path.insert(0, r'D:\TLGL\.scratch')
from pakunpack2 import walk_generations, crc

REC = struct.Struct('<QIIIIHBBII')
PAKS = ['data.pak', 'data1.pak', 'data2.pak', 'data3.pak', 'data4.pak', 'data_1.pak']

for p in PAKS:
    with open(r'D:\TLGL' + '\\' + p, 'rb') as f:
        data = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        bad = []
        for gi, gen in enumerate(walk_generations(data)):
            rp, n = gen[0], gen[1]
            for i in range(n):
                r = data[rp + i * 36:rp + i * 36 + 36]
                h, off, size, occ, ofsz, ver, fl, me, fcrc, ucrc = REC.unpack(r)
                if crc(r[:32]) != ucrc:
                    bad.append((gi, i, h, off, size, occ, ofsz, ver, fl, me, fcrc, ucrc))
        bygen = {}
        for b in bad:
            bygen[b[0]] = bygen.get(b[0], 0) + 1
        print('=== ' + p + ' bad=' + str(len(bad)) + ' bygen=' + str(dict(sorted(bygen.items()))))
        for b in bad[:6]:
            print('   gen', b[0], 'rec', b[1], 'hash', format(b[2], '016x'), 'off', hex(b[3]),
                  'size', b[4], 'occ', b[5], 'osize', b[6], 'ver', b[7], 'fl', hex(b[8]),
                  'me', b[9], 'ucrc', format(b[11], '08x'))
        data.close()
