import mmap, sys

paks = ['data.pak', 'data4.pak', 'data_1.pak']
pats = [b'scripts/', b'data/', b'ui/', b'.xml', b'.png', b'.mdl', b'.acts', b'.tab', b'.cfg', b'.jstr',
        b'.collect', b'webview', b'.dll', b'.exe', b'.lua', b'.ogg', b'.wav']
for p in paks:
    with open(r'D:\TLGL' + '\\' + p, 'rb') as f:
        m = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        print('===', p)
        for pat in pats:
            offs = []
            pos = 0
            while len(offs) < 6:
                i = m.find(pat, pos)
                if i < 0:
                    break
                offs.append(i)
                pos = i + 1
            tot = 0
            pos = 0
            while True:
                i = m.find(pat, pos)
                if i < 0:
                    break
                tot += 1
                pos = i + 1
                if tot > 200000:
                    break
            if tot:
                print('  %-10s count=%-7d first=%s' % (pat.decode(), tot, ['0x%x' % o for o in offs[:4]]))
        m.close()
