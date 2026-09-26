import sqlite3, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
def sdbm(b):
    h = 0
    for x in b: h = (x + (h<<6) + (h<<16) - h) & 0xffffffff
    return h
c = sqlite3.connect('file:D:/TLGL/.scratch/resources.db?mode=ro', uri=True)
hiby = set()
anon_tex = set()
for h, named, typ in c.execute("select hash, named, type from resources"):
    hi = int(h,16) >> 32
    hiby.add(hi)
    if typ == 'texture' and not named: anon_tex.add(hi)
tgapaths = [l.rstrip('\n') for l in open('D:/TLGL/.scratch/cfg_paths.txt', encoding='utf-8') if l.rstrip('\n').lower().endswith('.tga')]
print('tga paths:', len(tgapaths), 'anon tex blobs:', len(anon_tex))
def variants(p):
    f = p.lower()
    base = f.rsplit('/',1)[-1]; stem = base.rsplit('.',1)[0]
    dirp = f.rsplit('/',1)[0]
    out = {
      'as_is': f,
      'dds': f[:-4]+'.dds', 'png': f[:-4]+'.png', 'jpg': f[:-4]+'.jpg',
      'no_data': f[5:], 'lead': '/'+f,
      'back': p.lower().replace('/', chr(92)),
      'base': base, 'stem': stem,
      'base_dds': stem+'.dds', 'base_png': stem+'.png',
      'tex1': f.replace('/textures/','/texture/'),
      'nodir': 'data/texture/'+base, 'nodir2': 'texture/'+base,
      'nodir3': 'data/textures/'+base, 'nodir4': 'data/effect/'+base,
      'runtime': 'data/runtime/'+f[5:], 'cache': 'data/texturecache/'+base,
      'upper': f.upper(), 'mix': p.replace('/', chr(92)).lower(),
    }
    return out
tally = {k:0 for k in variants('x')}
tally_anon = {k:0 for k in variants('x')}
for p in tgapaths:
    for k, s in variants(p).items():
        hi = sdbm(s.encode())
        if hi in hiby:
            tally[k]+=1
            if hi in anon_tex: tally_anon[k]+=1
for k,v in sorted(tally.items(), key=lambda x:-x[1]):
    if v: print(f'{k:10s} hit_all={v:6d} hit_anon_tex={tally_anon[k]}')
print('scan done')
