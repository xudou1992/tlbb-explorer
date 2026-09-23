import re,io,sqlite3,os
o=io.open('agent_map_29_names.txt','w',encoding='utf-8')
def W(*a): o.write(' '.join(str(x) for x in a)+'\n')
raw=open('out/tree/ResourcePath.cfg','rb').read()
c=sqlite3.connect('file:D:/TLGL/.scratch/resources.db?mode=ro',uri=True)
dbb={}
for p in [r[0] for r in c.execute("select path from resources where named=1")]:
    dbb.setdefault(p.rsplit('/',1)[-1].lower(),0)
    dbb[p.rsplit('/',1)[-1].lower()]+=1
# scene names referenced by our instance tables
import glob,struct,collections
NAMEOK=re.compile(rb'^[A-Za-z0-9_\-\.]{4,80}$')
ref=collections.Counter()
for f in glob.glob('out/tree/mobile_maps/*/*.scene'):
    raw2=open(f,'rb').read()
    if len(raw2)<12: continue
    N,RS,Z=struct.unpack_from('<III',raw2,0)
    if RS not in (753,749): continue
    st=RS+8
    for i in range(N):
        b=12+st*i
        if b+65>len(raw2): break
        nm=raw2[b+64:b+64+st-64].split(b'\0',1)[0]
        if NAMEOK.match(nm): ref[nm.decode('latin1').lower()]+=1
W('distinct names referenced by scene instance tables: %d ; instances %d'%(len(ref),sum(ref.values())))
for ext in ('.mesh','.tga','.pu','.mdl'):
    pat=re.compile(b'[a-z0-9_]+' + re.escape(ext.encode()) + b'(?=[a-z0-9_/.]|$)')
    cfg=set(m.group().decode('latin1') for m in pat.finditer(raw))
    indb=set(k for k in dbb if k.endswith(ext))
    refx={k:v for k,v in ref.items() if k.endswith(ext)}
    W('\n%s  cfg-distinct=%d  db-named=%d  referenced-by-scenes=%d (instances %d)'%(ext,len(cfg),len(indb),len(refx),sum(refx.values())))
    W('   referenced & in cfg: %d ; referenced & in db: %d ; referenced & cfg-but-NOT-db: %d ; referenced & not-in-cfg: %d'
      %(sum(1 for k in refx if k in cfg),sum(1 for k in refx if k in indb),sum(1 for k in refx if k in cfg and k not in indb),sum(1 for k in refx if k not in cfg)))
    ci=sum(refx[k] for k in refx if k in cfg and k not in indb); ni=sum(refx[k] for k in refx if k not in cfg and k not in indb)
    W('   INSTANCE-weighted: recoverable-via-cfg-only=%d (%.2f%%) ; absent-even-from-cfg=%d (%.2f%%)'%(ci,100.0*ci/sum(ref.values()),ni,100.0*ni/sum(ref.values())))
o.close();print('ok')
