import struct, sys, mmap, os
sys.path.insert(0, r'D:\TLGL\.scratch')
from pakunpack2 import walk_generations, crc

REC = struct.Struct('<QIIIIHBBII')
PAKS = ['data.pak', 'data1.pak', 'data2.pak', 'data3.pak', 'data4.pak', 'data_1.pak']
gt = gs = 0
gn = 0
meth = {}
flg = {}
for p in PAKS:
    with open(r'D:\TLGL' + '\\' + p, 'rb') as f:
        data = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        gens = walk_generations(data)
        s = o = n = 0
        for gi, gen in enumerate(gens):
            rp, cnt = gen[0], gen[1]
            for i in range(cnt):
                r = data[rp + i * 36:rp + i * 36 + 36]
                h, off, size, occ, ofsz, ver, fl, me, fcrc, ucrc = REC.unpack(r)
                if crc(r[:32]) != ucrc:
                    continue
                n += 1
                s += size
                o += ofsz
                meth[me] = meth.get(me, 0) + 1
                flg[fl] = flg.get(fl, 0) + 1
        print('%-10s gens=%-3d entries=%-7d stored=%7.1fMB original=%8.1fMB  fileused=%dMB' % (
            p, len(gens), n, s / 1e6, o / 1e6, os.path.getsize(r'D:\TLGL' + '\\' + p) // 1048576))
        gt += o
        gs += s
        gn += n
        data.close()
print('TOTAL entries=%d stored=%.2fGB original=%.2fGB' % (gn, gs / 1e9, gt / 1e9))
print('method histogram:', meth)
print('flags histogram:', dict(sorted(flg.items())))
