import os, io, re, glob, struct, collections, numpy as np, sqlite3, json
o=io.open('agent_map_12_valid.txt','w',encoding='utf-8')
def W(*a): o.write(' '.join(str(x) for x in a)+'\n')
NAMEOK=re.compile(rb'^[A-Za-z0-9_\-\.]{4,80}$')
c=sqlite3.connect('file:D:/TLGL/.scratch/resources.db?mode=ro',uri=True)
byname={}
for h,p in c.execute("select hash,path from resources where named=1"):
    byname.setdefault(p.rsplit('/',1)[-1].lower(),(h,p))

files=glob.glob('out/tree/mobile_maps/*/*.scene')
stat=collections.Counter()
clean_by_map=collections.defaultdict(collections.Counter)
allpos=[]; ptr_in_rec=0; ptr_total=0; rec_total=0; miss=[]
ext_hist=collections.Counter(); hit=0; named_inst=0; empty=0
coord_by_map=collections.defaultdict(list)
scale_hist=[]
bad_examples=[]
for f in files:
    raw=open(f,'rb').read()
    if len(raw)<12: stat['too_small']+=1; continue
    N,RS,Z=struct.unpack_from('<III',raw,0)
    if RS!=753: stat['rs_%d'%min(RS,9999)]+=1; continue
    stat['grid753_files']+=1
    m=os.path.basename(os.path.dirname(f))
    ok=0
    for i in range(N):
        b=12+761*i
        if b+65>len(raw): break
        nm=raw[b+64:b+64+697].split(b'\0',1)[0]
        rec_total+=1
        if len(nm)==0: empty+=1; ok+=1; continue
        if not NAMEOK.match(nm) or b'\x01' in nm or max(nm)<0x20:
            stat['badname']+=1
            if len(bad_examples)<6: bad_examples.append((f,i,nm[:40]))
            continue
        e=os.path.splitext(nm.decode('latin1'))[1]
        ext_hist[e]+=1
        k=nm.decode('latin1').lower()
        if k in byname: hit+=1
        else:
            named_inst+=1
            if len(miss)<4000: miss.append(k)
        ok+=1
        mat=struct.unpack_from('<16f',raw,b)
        x,y,z=mat[12],mat[13],mat[14]
        if abs(x)<6000 and abs(y)<6000 and abs(z)<6000 and (x or y or z):
            allpos.append((x,y,z)); coord_by_map[m].append((x,y,z))
        scale_hist.append(round(np.linalg.norm(mat[0:4]),3))
    clean_by_map[m]['N']+=N; clean_by_map[m]['ok']+=ok
W('files grid753:',stat['grid753_files'],' other:',dict(k for k in stat.items() if k[0]!='grid753_files'))
W('records walked:',rec_total,' clean-name:',hit+named_inst,' empty:',empty)
W('join hit:',hit,'miss:',named_inst,' rate %.4f%%'%(100.0*hit/max(1,hit+named_inst)))
W('ext hist:',dict(ext_hist.most_common(8)))
W('bad-name examples:',bad_examples)
P=np.array(allpos); W('\ncoords n=%d'%len(P))
for j,nm in enumerate('xyz'):
    W('  %s: min %.2f p1 %.2f p50 %.2f p99 %.2f max %.2f'%(nm,P[:,j].min(),*np.percentile(P[:,j],[1,50,99]),P[:,j].max()))
S=np.array(scale_hist); W('  scale: min %.3f p50 %.3f max %.3f  |  distinct top: %s'%(S.min(),np.median(S),S.max(),collections.Counter(S.tolist()).most_common(6)))
W('\nper-map coordinate bbox (12 maps):')
for m,v in sorted(coord_by_map.items(), key=lambda kv:-len(kv[1]))[:12]:
    a=np.array(v); W('  %-34s n=%-6d x[%8.1f,%8.1f] y[%7.1f,%7.1f] z[%8.1f,%8.1f]'%(m,len(a),a[:,0].min(),a[:,0].max(),a[:,1].min(),a[:,1].max(),a[:,2].min(),a[:,2].max()))
W('\ntop miss examples (first 30):',sorted(set(miss))[:30])
tot=sum(v['N'] for v in clean_by_map.values()); oko=sum(v['ok'] for v in clean_by_map.values())
W('\nrecords addressable within file bounds: %d/%d = %.2f%%'%(oko,tot,100.0*oko/tot))
json.dump({m:[np.array(v).min(0).tolist(),np.array(v).max(0).tolist(),len(v)] for m,v in coord_by_map.items()}, io.open('agent_map_12_bbox.json','w',encoding='utf-8'))
o.close(); print('ok')
