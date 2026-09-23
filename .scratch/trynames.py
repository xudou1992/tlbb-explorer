import os
import sys
import struct
import mmap

sys.path.insert(0, r'D:\TLGL\.scratch')
from pakunpack2 import REC, crc, walk_generations
from jhash import path_hash

# collect all hashes
allh = {}
for p in ['data.pak', 'data1.pak', 'data2.pak', 'data3.pak', 'data4.pak', 'data_1.pak']:
    with open(r'D:\TLGL' + '\\' + p, 'rb') as f:
        data = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        for gi, gen in enumerate(walk_generations(data)):
            rp, cnt = gen[0], gen[1]
            for i in range(cnt):
                r = data[rp + i * 36:rp + i * 36 + 36]
                h, off, size, occ, ofsz, ver, fl, me, fcrc, ucrc = REC.unpack(r)
                if crc(r[:32]) == ucrc and size:
                    allh.setdefault(h, []).append((p, gi, off, size, ofsz, fl, me))
        data.close()
print('unique hashes:', len(allh))

cands = ['version_dx11.collect.pcfg', 'resourcepath.cfg', 'global.jstr', 'ui/modulelist_base.xml',
         'ui/modulelist_game.xml', 'modules/modulelist.xml.gameclient', 'scripts/client_script_list.txt',
         'binary_table_files_align8_64bit.tab', 'NEP2_64.dll', 'KernelDumpAnalyzer.exe',
         'data/tani/boss_sss_jmz_skill01_show.lgc', 'scene/1001/1001.scene', 'model/player/a/a001.mesh',
         'texture/ui/main_ui.png', 'ui/login/login.xml', 'sound/amb/amb_01.ogg', 'config/game.cfg',
         'global.jstr', 'scripts/main.lua', 'data/global.jstr', 'version_dx11.collect.pcfg',
         'convert_dxt_ui', 'logic', '3d', 'tmg_x64', 'modules/modulelist.xml.gameclient']
for c in cands:
    h = path_hash(c)
    hit = allh.get(h)
    print('%-40s %016x  %s' % (c, h, ('HIT ' + str(hit[:1])) if hit else '-'))
open(r'D:\TLGL\.scratch\hashes.txt', 'w').write('\n'.join(format(h, '016x') for h in allh))
print('wrote hashes.txt')
