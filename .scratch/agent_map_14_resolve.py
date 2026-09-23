import os, io, re, glob, struct, collections, random, sqlite3, numpy as np
o=io.open('agent_map_14_resolve.txt','w',encoding='utf-8')
def W(*a): o.write(' '.join(str(x) for x in a)+'\n')
c=sqlite3.connect('file:D:/TLGL/.scratch/resources.db?mode=ro',uri=True)
byname={}
for h,p in c.execute("select hash,path from resources where named=1"):
    byname.setdefault(p.rsplit('/',1)[-1].lower(),(h,p))
ag=collections.defaultdict(set)
for n,g in c.execute("select lower(name),gid from agroup_names"): ag[n].add(g)
mem={}
for g,h,r in c.execute("select gid,hash,role from amembers"): mem.setdefault((g,r),[]).append(h)
W('agroup_names distinct:',len(ag),' amembers rows:',len(mem))
dang={n:(e,nr,ns,cls) for n,e,nr,ns,cls in c.execute("select lower(name),ext,n_refs,n_src,cls from dangling")}
W('dangling rows:',len(dang))
refs_names=collections.Counter(n for (n,) in c.execute("select lower(name) from refs"))
W('refs distinct names:',len(refs_names))

NAMEOK=re.compile(rb'^[A-Za-z0-9_\-\.]{4,80}$')
files=glob.glob('out/tree/mobile_maps/*/*.scene')
random.seed(11); sample=random.sample(files,1200)
miss=collections.Counter(); hit=0; tot=0
for f in sample:
    raw=open(f,'rb').read()
    if len(raw)<12: continue
    N,RS,Z=struct.unpack_from('<III',raw,0)
    if RS!=753: continue
    for i in range(N):
        b=12+761*i
        if b+65>len(raw): break
        nm=raw[b+64:b+64+697].split(b'\0',1)[0].decode('latin1').lower()
        if not NAMEOK.match(nm.encode('latin1')): continue
        tot+=1
        if nm in byname: hit+=1
        else: miss[nm]+=1
W('\n== sample of %d scene files: %d records, direct join %d (%.2f%%), missing %d distinct'%(len(sample),tot,hit,100.0*hit/tot,len(miss)))
res_paths=0; res_any=0; unresolved=[]
for nm,n in miss.items():
    if nm.endswith('.mesh'):
        stem=nm[:-5]
        gids=ag.get(stem,set())|ag.get(nm,set())
        got=None
        for g in gids:
            for r in ('mesh','mdl','model'):
                if (g,r) in mem: got=mem[(g,r)][0]; break
            if got: break
        if got: res_any+=n; continue
        # any member whose resource basename == stem.*
        cand=[h for h,p in c.execute("select hash,path from resources where named=0 limit 0")]
    unresolved.append((nm,n))
    res_paths+=n
W('  via agroup_names(mesh stem) resolved instance-count: %d / %d missing'%(res_any,sum(miss.values())))
un=collections.Counter(k for k,_ in unresolved)
W('  still unresolved distinct: %d  (instances %d, %.2f%% of records)'%(len(un),sum(miss.values())-res_any,100.0*(sum(miss.values())-res_any)/tot))
W('  examples:',list(un)[:25])
W('\n== do those unresolved appear in refs.name / dangling?')
inrefs=sum(1 for k in un if k in refs_names); indang=sum(1 for k in un if k in dang)
W('  unresolved in refs: %d/%d ; in dangling: %d/%d'%(inrefs,len(un),indang,len(un)))
W('  dangling examples:',[(k,dang[k]) for k in list(un) if k in dang][:6])
W('\n== extension split of unresolved:',collections.Counter(os.path.splitext(k)[1] for k in un))
o.close(); print('ok')
