import io,re,sqlite3,collections,sys
sys.path.insert(0,'.')
o=io.open('agent_map_26_cfgcount.txt','w',encoding='utf-8')
def W(*a): o.write(' '.join(str(x) for x in a)+'\n')
raw=open('out/tree/ResourcePath.cfg','rb').read()
try:
    import jbcf
    hdr,off,flag,pairs=jbcf.parse(raw)
    W('jbcf.parse -> %d strings'%len(pairs))
    names=[s for s,h in pairs]
except Exception as e:
    W('jbcf.parse failed:',repr(e))
    names=[]
if names:
    full=[s for s in names if '/' in s]
    W('  strings with / :',len(full),' without:',len(names)-len(full))
    c=sqlite3.connect('file:D:/TLGL/.scratch/resources.db?mode=ro',uri=True)
    db=set(p.lower() for (p,) in c.execute("select path from resources where named=1"))
    W('  db named paths:',len(db))
    fl=[s.lower() for s in full]
    miss=[s for s in fl if s not in db]
    W('  cfg full-paths absent from db: %d / %d = %.1f%%'%(len(miss),len(fl),100.0*len(miss)/max(1,len(fl))))
    ext=collections.Counter(s.rsplit('.',1)[-1] if '.' in s.rsplit('/',1)[-1] else '(none)' for s in miss)
    W('  missing by ext:',dict(ext.most_common(15)))
    W('  missing examples:',miss[:10])
    ext2=collections.Counter(s.rsplit('.',1)[-1] if '.' in s.rsplit('/',1)[-1] else '(none)' for s in fl)
    W('  ALL cfg paths by ext:',dict(ext2.most_common(18)))
    W('  TerrainInfo in cfg:',sum(1 for s in fl if 'terraininfo' in s), ' present in db:',sum(1 for s in fl if 'terraininfo' in s and s in db))
    W('  mobile_maps_source in cfg:',sum(1 for s in fl if s.startswith('mobile_maps_source')))
o.close();print('ok')
