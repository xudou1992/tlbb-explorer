import os, io, re, glob, struct, collections, random, sqlite3, numpy as np
o=io.open('agent_map_13_verify.txt','w',encoding='utf-8')
def W(*a): o.write(' '.join(str(x) for x in a)+'\n')
NAMEOK=re.compile(rb'^[A-Za-z0-9_\-\.]{4,80}$')
c=sqlite3.connect('file:D:/TLGL/.scratch/resources.db?mode=ro',uri=True)
byname={}
for h,p in c.execute("select hash,path from resources where named=1"):
    byname.setdefault(p.rsplit('/',1)[-1].lower(),(h,p))
suffix=collections.defaultdict(list)
for k in byname:
    for L in (10,14):
        if len(k)>L: suffix[k[-L:]].append(k)

files=glob.glob('out/tree/mobile_maps/*/*.scene')
random.seed(7); sample=random.sample(files,900)
grid_ok=0; grid_tot=0; grid_bad=[]
ptrloc=collections.Counter(); rec_with_ptr=0; rec_tot=0; nptr=0; nrec=0
bytes_ptr=0
hit=0; miss=0; miss_artifact=0; miss_real=collections.Counter(); miss_real_ex=[]
for f in sample:
    raw=open(f,'rb').read()
    if len(raw)<12: continue
    N,RS,Z=struct.unpack_from('<III',raw,0)
    if RS!=753: continue
    stem=os.path.basename(f)[:-6]
    gi=[int(x) for x in stem.split('_')]
    for i in range(N):
        b=12+761*i
        if b+65>len(raw): break
        nm=raw[b+64:b+64+697].split(b'\0',1)[0]
        rec_tot+=1; nrec+=1
        if len(nm)==0: continue
        if not NAMEOK.match(nm): continue
        mat=struct.unpack_from('<16f',raw,b)
        x,y,z=mat[12],mat[13],mat[14]
        if abs(x)<4000 and abs(z)<4000:
            grid_tot+=1
            cx,cz=np.floor(x/32.0).astype(int), np.floor(z/32.0).astype(int)
            if cx==gi[1] and cz==gi[2]: grid_ok+=1
            elif len(grid_bad)<8: grid_bad.append((stem,x,y,z))
        k=nm.decode('latin1').lower()
        if k in byname: hit+=1
        else:
            miss+=1
            cand=[v for L in (10,14) for v in suffix.get(k[-L:],[])] if len(k)>=10 else []
            if any(v.endswith(k) for v in cand): miss_artifact+=1
            else:
                miss_real[k]+=1
                if len(miss_real_ex)<40: miss_real_ex.append(k)
        # pointers within record
        seg=raw[b:b+761-((b+761)-len(raw)) if b+761>len(raw) else b+761]
        u64=np.frombuffer(seg[:len(seg)//8*8],dtype='<u8')
        mask=(((u64>>32)>=0x7f00)&((u64>>32)<=0x7fff)&((u64&0xffffffff)!=0))
        pk=np.nonzero(mask)[0]*8
        if len(pk): rec_with_ptr+=1; nptr+=len(pk)
        for q in pk:
            ptrloc[int(q)//64*64]+=1; bytes_ptr+=8
W('== EVIDENCE: filename grid index vs baked position (floor(x/32), floor(z/32))')
W('  matched %d/%d = %.3f%%   mismatches sample %s'%(grid_ok,grid_tot,100.0*grid_ok/grid_tot,grid_bad[:4]))
W('\n== JOIN (clean-name records only)')
W('  hit=%d miss=%d rate %.3f%%'%(hit,miss,100.0*hit/(hit+miss)))
W('  of misses: %d are truncation artifacts (suffix of a real asset name), %d genuinely absent (%.3f%% of all)'
  %(miss_artifact,sum(miss_real.values()),100.0*sum(miss_real.values())/(hit+miss)))
W('  distinct genuinely-missing names: %d ; examples: %s'%(len(miss_real),miss_real_ex[:20]))
W('\n== POINTER POLLUTION (record-relative buckets of 64B)')
W('  records containing >=1 0x7f.. u64: %d/%d = %.1f%%'%(rec_with_ptr,rec_tot,100.0*rec_with_ptr/rec_tot))
W('  total such u64: %d over %d records ; %.2f per record ; bytes %d = %.2f B/record (%.2f%% of record bytes)'
  %(nptr,rec_tot,nptr/max(1,rec_tot),bytes_ptr,bytes_ptr/max(1,rec_tot),100.0*bytes_ptr/max(1,rec_tot)/761))
for kk in sorted(ptrloc)[:12]: W('    rec+%4d : %6d hits'%(kk,ptrloc[kk]))
W('  => polluted byte range inside a record: see buckets; matrix@0..63 and name@64.. are clean iff no bucket <361')
o.close(); print('ok')
