import numpy as np, struct, io, os, glob, re, sqlite3, collections, json
o=io.open('agent_map_22_global.txt','w',encoding='utf-8')
def W(*a): o.write(' '.join(str(x) for x in a)+'\n')
NAMEOK=re.compile(rb'^[A-Za-z0-9_\-\.]{4,80}$')
c=sqlite3.connect('file:D:/TLGL/.scratch/resources.db?mode=ro',uri=True)
meshfc={}
for h,p,orig in c.execute("select hash,path,original from resources where ext='.mesh' and named=1"):
    meshfc.setdefault(p.rsplit('/',1)[-1].lower(),None)
SRC='out/tree/mobile_maps_source'
for k in list(meshfc):
    p=os.path.join(SRC,k)
    if os.path.exists(p):
        with open(p,'rb') as fh: hd=fh.read(0x94)
        if len(hd)>=0x94: meshfc[k]=struct.unpack_from('<I',hd,0x90)[0]
W('map-adjacent named .mesh with fc read: %d/%d'%(sum(1 for v in meshfc.values() if v),len(meshfc)))
named=set(k for k,v in meshfc.items())
rows=collections.defaultdict(lambda:[0,0,set(),set(),0,0])  # inst, ok, uniq, uniqres, tris, tress
for f in glob.glob('out/tree/mobile_maps/*/*.scene'):
    m=os.path.basename(os.path.dirname(f))
    try: raw=open(f,'rb').read()
    except Exception: continue
    if len(raw)<12: continue
    N,RS,Z=struct.unpack_from('<III',raw,0)
    if RS not in (753,749): continue
    st=RS+8
    for i in range(N):
        b=12+st*i
        if b+65>len(raw): break
        nm=raw[b+64:b+64+st-64].split(b'\0',1)[0]
        if not NAMEOK.match(nm): continue
        s=nm.decode('latin1').lower()
        r=rows[m]; r[0]+=1
        if s.endswith('.mesh'):
            r[2].add(s)
            fc=meshfc.get(s)
            if fc: r[1]+=1; r[3].add(s); r[4]+=fc
W('\n== per-map aggregate over %d maps'%len(rows))
tot_inst=sum(r[0] for r in rows.values()); tot_ok=sum(r[1] for r in rows.values())
W('  instances: %d  with resolvable named mesh: %d = %.2f%%'%(tot_inst,tot_ok,100.0*tot_ok/tot_inst))
buck=collections.Counter()
for m,r in rows.items():
    q=r[1]/max(1,r[0])
    buck['>=99%' if q>=0.99 else '>=95%' if q>=0.95 else '>=80%' if q>=0.8 else '>=50%' if q>=0.5 else '>0%' if q>0 else '0%']+=1
W('  maps by instance-resolve bucket:',dict(buck))
W('  maps with 0 resolvable instances:',sum(1 for r in rows.values() if r[1]==0))
med=np.median([r[1]/max(1,r[0]) for r in rows.values()]); W('  median per-map instance resolve rate: %.3f'%med)
uq=np.median([len(r[3])/max(1,len(r[2])) for r in rows.values()]); W('  median per-map UNIQUE-mesh resolve rate: %.3f'%uq)
tr=sorted((r[4],m) for m,r in rows.items())
W('  per-map unique-mesh triangles: p50=%d p90=%d max=%d (%s)'%(tr[len(tr)//2][0],tr[int(len(tr)*0.9)][0],tr[-1][0],tr[-1][1]))
W('  total unique map meshes referenced: %d ; total triangles (dedup) %d'%(len(set().union(*[r[3] for r in rows.values()]) if rows else set()), sum(r[4] for r in rows.values())))
best=sorted(rows.items(), key=lambda kv:-kv[1][1])[:10]
W('\n  top-10 maps by resolvable instances:')
for m,r in best: W('    %-32s inst=%-6d res=%-6d (%.1f%%) uniqMesh=%d tri=%d'%(m,r[0],r[1],100.0*r[1]/r[0],len(r[3]),r[4]))
worst=[(m,r) for m,r in rows.items() if r[0]>500]
worst=sorted(worst,key=lambda kv:kv[1][1]/kv[1][0])[:8]
W('  worst >500-inst maps:')
for m,r in worst: W('    %-32s inst=%-6d res=%-6d (%.1f%%)'%(m,r[0],r[1],100.0*r[1]/r[0]))
json.dump({m:[r[0],r[1],len(r[2]),len(r[3]),r[4]] for m,r in rows.items()},io.open('agent_map_22_maps.json','w',encoding='utf-8'))
o.close(); print('ok')
