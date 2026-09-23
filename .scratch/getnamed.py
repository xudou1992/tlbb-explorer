import json
import mmap
import os
import struct
import sys

sys.path.insert(0, r'D:\TLGL\.scratch')
import cramjam
from pakunpack2 import REC, crc, decrypt, walk_generations
from jhash import path_hash

OUT = r'D:\TLGL\.scratch\out\named'
os.makedirs(OUT, exist_ok=True)
PAKS = ['data.pak', 'data1.pak', 'data2.pak', 'data3.pak', 'data4.pak', 'data_1.pak']
names = ['version_dx11.collect.pcfg', 'resourcepath.cfg', 'global.jstr', 'ui/modulelist_base.xml',
         'ui/modulelist_game.xml', 'modules/modulelist.xml.gameclient', 'scripts/client_script_list.txt',
         'binary_table_files_align8_64bit.tab', 'version_dx11.collect.pcfg']

want = {path_hash(n): n for n in set(names)}
found = {}
for p in PAKS:
    with open(r'D:\TLGL' + '\\' + p, 'rb') as f:
        data = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        for gi, gen in enumerate(walk_generations(data)):
            rp, cnt = gen[0], gen[1]
            for i in range(cnt):
                r = data[rp + i * 36:rp + i * 36 + 36]
                h, off, size, occ, ofsz, ver, fl, me, fcrc, ucrc = REC.unpack(r)
                if h in want and size:
                    found.setdefault(h, []).append((p, gi, off, size, occ, ofsz, ver, fl, me, fcrc))
        data.close()

for h, hits in found.items():
    name = want[h]
    for (p, gi, off, size, occ, ofsz, ver, fl, me, fcrc) in hits:
        with open(r'D:\TLGL' + '\\' + p, 'rb') as f:
            f.seek(off)
            raw = f.read(size)
        assert crc(raw) == fcrc, 'stored crc'
        body = decrypt(h, size, raw) if fl & 4 else raw
        if fl & 1:
            pl = body[0]
            body = body[1 + pl + 16:]
        out = bytes(cramjam.snappy.decompress_raw(body)) if me == 0x33 else body
        assert len(out) == ofsz, (len(out), ofsz)
        dest = os.path.join(OUT, os.path.splitext(p)[0] + '__' + name.replace('/', '_'))
        open(dest, 'wb').write(out)
        print('%-38s %-10s gen%-3d %9d -> %9d  %s' % (name, p, gi, size, len(out), format(h, '016x')))
        print('    head: %r' % out[:120])
