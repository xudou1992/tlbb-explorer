import os, io, re, glob, struct, sqlite3, collections
c=sqlite3.connect('file:D:/TLGL/.scratch/resources.db?mode=ro',uri=True)
o=io.open('agent_map_11_join.txt','w',encoding='utf-8')
def W(*a): o.write(' '.join(str(x) for x in a)+'\n')
# build basename -> [hash] index for named resources
byname=collections.defaultdict(list)
for h,p in c.execute("select hash,path from resources where named=1"):
    byname[p.rsplit('/',1)[-1].lower()].append((h,p))
allnames=collections.Counter(byname)
W('named resources:',sum(len(v) for v in byname.values()),'distinct basenames:',len(byname))

PAT=re.compile(rb'[A-Za-z0-9_\-]{3,}\.(?:mesh|pu|scene|tga|dds)\x00')
def parse(f):
    raw=open(f,'rb').read()
    if len(raw)<12: return None
    N,RS,Z=struct.unpack_from('<III',raw,0)
    if RS!=753: return None
    out=[]
    for i in range(N):
        b=12+761*i
        if b+68>len(raw): break
        nm=raw[b+64:].split(b'\0',1)[0].decode('latin1')
        if len(nm)<4: nm=''
        out.append((b,nm))
    return raw,N,out

maps=['w1351_ll_dl_002','w1351_ll_cs_001','w1351_fb_jiehun_001','w1351_ll_yxh_001','w1351_gj_jz_001','w1351_ll_qingyuan_001']
tot=collections.Counter()
for m in maps:
    fs=sorted(glob.glob('out/tree/mobile_maps/%s/*.scene'%m))
    inst=0; named=0; hit=0; miss=set(); hitset=set(); kinds=collections.Counter()
    for f in fs:
        r=parse(f)
        if not r: continue
        raw,N,recs=r
        for b,nm in recs:
            inst+=1
            if not nm: continue
            named+=1
            kinds[os.path.splitext(nm)[1]]+=1
            k=nm.lower()
            if k in byname: hit+=1; hitset.add(k)
            else: miss.add(k)
    W('\n#### %s  files=%d  instances=%d  named=%d  basename-hit=%d (%.1f%% of named)  uniq-hit=%d uniq-miss=%d'
      %(m,len(fs),inst,named,hit,100.0*hit/max(named,1),len(hitset),len(miss)))
    W('   ext kinds:',dict(kinds))
    W('   missed uniq (first 25):',sorted(miss)[:25])
    tot['inst']+=inst; tot['named']+=named; tot['hit']+=hit; tot['missuniq']+=len(miss)
W('\n== TOTAL over %d maps: %s'%(len(maps),dict(tot)))
W('hit rate %.2f%%'%(100.0*tot['hit']/tot['named']))

# how many mobile_maps_source meshes are never referenced by any scene? (sample 20 maps)
ref=set()
W('\n== mobile_maps_source inventory')
rows=list(c.execute("select hash,path from resources where dir='mobile_maps_source' and ext='.mesh'"))
W('source mesh count:',len(rows))
srcnames=collections.Counter(p.rsplit('/',1)[-1].lower() for h,p in rows)
W('distinct source basenames:',len(srcnames))
missing_src=[k for k in srcnames if k not in byname]
W('source basenames absent from resources.path:',len(missing_src))
o.close(); print('ok')
