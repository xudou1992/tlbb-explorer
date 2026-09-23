import io,re,sqlite3,collections
o=io.open('agent_map_27_cfgcount.txt','w',encoding='utf-8')
def W(*a): o.write(' '.join(str(x) for x in a)+'\n')
raw=open('out/tree/ResourcePath.cfg','rb').read()
PREF=(b'mobile_maps_source/',b'mobile_maps/',b'data/',b'ui/',b'scripts/',b'settings/',b'engine/')
idx=[]
for p in PREF:
    s=0
    while True:
        i=raw.find(p,s)
        if i<0: break
        idx.append(i); s=i+1
idx.sort()
W('prefix occurrences:',len(idx))
PAT=re.compile(rb'^(?:mobile_maps_source|mobile_maps|data|ui|scripts|settings|engine)/[0-9A-Za-z_\-\./]*?\.[0-9A-Za-z]{2,12}')
paths=[]
for k,i in enumerate(idx):
    end = idx[k+1] if k+1<len(idx) else len(raw)
    seg=raw[i:end]
    m=PAT.match(seg)
    if m: paths.append(m.group().decode('latin1'))
W('parsed full paths:',len(paths),' distinct:',len(set(p.lower() for p in paths)))
c=sqlite3.connect('file:D:/TLGL/.scratch/resources.db?mode=ro',uri=True)
db=set(p.lower() for (p,) in c.execute("select path from resources where named=1"))
low=[p.lower() for p in paths]
miss=[p for p in low if p not in db]
W('in db: %d ; NOT in db: %d (%.1f%% of cfg)'%(len(low)-len(miss),len(miss),100.0*len(miss)/len(low)))
def ext(s):
    t=s.rsplit('/',1)[-1]
    return t.rsplit('.',1)[-1] if '.' in t else '(none)'
W('\nmissing-by-ext top:',dict(collections.Counter(ext(s) for s in miss).most_common(20)))
W('all-cfg ext top:',dict(collections.Counter(ext(s) for s in low).most_common(20)))
W('\nterrain-ish paths in cfg:',[s for s in low if 'terrain' in s][:6],' count:',sum(1 for s in low if 'terrain' in s))
W('map/scene paths in cfg: .scene=%d .map=%d .nav=%d .sfl=%d'%tuple(sum(1 for s in low if s.endswith(e)) for e in ('.scene','.map','.nav','.sfl')))
mm=[s for s in low if s.startswith('mobile_maps/')]
W('mobile_maps/* paths in cfg: %d ; of these missing from db: %d'%(len(mm),sum(1 for s in mm if s not in db)))
src=[s for s in low if s.startswith('mobile_maps_source/')]
W('mobile_maps_source/* in cfg: %d ; missing from db: %d'%(len(src),sum(1 for s in src if s not in db)))
W('missing mobile_maps_source examples:',[s for s in src if s not in db][:8])
o.close();print('ok')
