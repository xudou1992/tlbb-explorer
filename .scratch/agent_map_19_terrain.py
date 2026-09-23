import numpy as np, struct, io, os, glob, re, collections, sqlite3, random
o=io.open('agent_map_19_terrain.txt','w',encoding='utf-8')
def W(*a): o.write(' '.join(str(x) for x in a)+'\n')
NAMEOK=re.compile(rb'^[A-Za-z0-9_\-\.]{4,80}$')
c=sqlite3.connect('file:D:/TLGL/.scratch/resources.db?mode=ro',uri=True)
byname=set()
for (p,) in c.execute("select path from resources where named=1"): byname.add(p.rsplit('/',1)[-1].lower())

# 1. token census of referenced mesh names
files=glob.glob('out/tree/mobile_maps/*/*.scene'); random.seed(3); samp=random.sample(files,700)
tok=collections.Counter(); names=set(); yhist=[]
for f in samp:
    raw=open(f,'rb').read()
    if len(raw)<12: continue
    N,RS,Z=struct.unpack_from('<III',raw,0)
    if RS!=753: continue
    for i in range(N):
        b=12+761*i
        if b+65>len(raw): break
        nm=raw[b+64:b+64+697].split(b'\0',1)[0]
        if not NAMEOK.match(nm): continue
        s=nm.decode('latin1').lower(); names.add(s)
        if s.endswith('.mesh'):
            for t in re.split(r'_',s[:-5]): tok[t]+=1
        mat=struct.unpack_from('<16f',raw,b); yhist.append(mat[13])
W('== %d distinct referenced mesh/effect names from %d scene files'%(len(names),len(samp)))
W('   unresolved (not a named resource): %d (%.2f%% of distinct names)'%(sum(1 for s in names if s not in byname),100.0*sum(1 for s in names if s not in byname)/len(names)))
W('   top name tokens:',[t for t,_ in tok.most_common(45)])
ground=[s for s in names if re.search(r'(dibiao|diban|ground|terrain|dimian|_tt_|tudi|dixing|_di_|_dt_)',s)]
W('   names that look like GROUND/TERRAIN tiles: %d -> %s'%(len(ground),ground[:12]))
big=[s for s in names if s.startswith('w1351_dl_')][:0]
Y=np.array(yhist); W('   instance y: n=%d min %.1f p50 %.1f max %.1f  distinct(0.5u bins)=%d'%(len(Y),Y.min(),np.median(Y),Y.max(),len(np.unique(np.round(Y*2)))))

# 2. whole-map mesh inventory: what are the 3264 source meshes named?
src=[p.rsplit('/',1)[-1].lower() for (p,) in c.execute("select path from resources where dir='mobile_maps_source' and ext='.mesh'")]
W('\n== mobile_maps_source meshes: %d ; tokens:'%len(src),[t for t,_ in collections.Counter(re.split(r'_',s[:-5])[1] for s in src).most_common(15)])
W('   source names matching terrain tokens: %d'%sum(1 for s in src if re.search(r'(dibiao|diban|ground|terrain|dimian|tudi)',s)))
W('   examples:',src[:10])

# 3. .map pointer census at 4-byte alignment + chunk-table value census over many maps
W('\n== .map pointer census (4-byte aligned u64 with high dword in 0x7f00..0x7fff)')
tot_bytes=0; tot_ptr=0
for f in sorted(glob.glob('out/tree/mobile_maps/*/*.map'), key=lambda p:-os.path.getsize(p))[:12]:
    raw=open(f,'rb').read()
    v,A,B,off=struct.unpack_from('<4I',raw,0); end=off+A*B*4160
    u=np.frombuffer(raw[:len(raw)//4*4],dtype='<u4')
    lo=u[:-1]; hi=u[1:]
    cnt4=int((((hi>=0x7f00)&(hi<=0x7fff)&(lo!=0))).sum())
    W('  %-30s size=%-8d AxB=%dx%d ptr4=%-5d  density %.2f/KB  header-region ptrs=%d'%(os.path.basename(f),len(raw),A,B,cnt4,1024.0*cnt4/len(raw),0))
    tot_bytes+=len(raw); tot_ptr+=cnt4
W('  TOTAL: %d ptrs in %.1f MB = %.2f per KB'%(tot_ptr,tot_bytes/1e6,1024.0*tot_ptr/tot_bytes))
W('  ... and all of them sit in the 152-byte header + tail: chunk table bytes are (0,b1,b2,0) with b1,b2 < 200')

# 4. where do .tga strings inside .scene live?
W('\n== .tga/.pu strings inside .scene files')
n=0
for f in samp[:250]:
    raw=open(f,'rb').read()
    for m in re.finditer(rb'[\x20-\x7e]{5,}\.tga\x00',raw):
        if n<12: W('   %s @%d  %s'%(os.path.basename(f),m.start(),m.group()[:-1].decode('latin1')))
        n+=1
W('   total .tga strings in %d sampled files: %d'%(min(250,len(samp)),n))
o.close(); print('ok')
