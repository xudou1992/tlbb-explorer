import numpy as np, struct, io, re, glob, os
o=io.open('agent_map_06_rec2.txt','w',encoding='utf-8')
def W(*a): o.write(' '.join(str(x) for x in a)+'\n')
NAME=re.compile(rb'[\x20-\x7e]{6,}\0')

def parse(path, stride=None, base=None):
    raw=open(path,'rb').read()
    N,RS,Z=struct.unpack_from('<III',raw,0)
    if stride is None: stride=RS+8
    if base is None: base=12
    W('\n#### %s size=%d N=%d RS=%d zero=%d stride=%d' % (os.path.basename(path), len(raw), N, RS, Z, stride))
    recs=[]
    for i in range(N):
        b=base+stride*i
        if b+64>len(raw): W('  rec%d beyond'%i); break
        m=struct.unpack_from('<16f',raw,b)
        sc=struct.unpack_from('<f',raw,b+64)[0]
        j=raw.find(b'\0', b+68)
        nm=raw[b+68:j].decode('latin1')
        if j==-1 or j-(b+68)>700: W('  BAD rec%d name at %d'%(i,b+68)); break
        recs.append((b,m,sc,nm))
    W('  parsed %d records; last ends at %d (file %d) leftover=%d'%(len(recs), base+stride*len(recs), len(raw), len(raw)-(base+stride*len(recs))))
    for i,(b,m,sc,nm) in enumerate(recs[:4]):
        W('  rec%02d @%-6d m=%s scale=%.4f  name=%s'%(i,b,[round(x,4) for x in m],sc,nm))
    # validate: row norms
    ok=0
    for b,m,sc,nm in recs:
        r=[np.linalg.norm(m[0:4]),np.linalg.norm(m[4:8]),np.linalg.norm(m[8:12])]
        if max(abs(x) for x in m)>2000: continue
        ok+=1
    W('  records with |matrix|<2000: %d/%d'%(ok,len(recs)))
    uniq=set(x[3] for x in recs)
    W('  names unique=%d ; ext: %s'%(len(uniq), sorted(set(os.path.splitext(x)[1] for x in uniq))))
    W('  name sample:', sorted(uniq)[:6])
    return raw, N, RS, stride, base, recs

d='out/tree/mobile_maps/w1351_ll_dl_002/'
for f in ['1_0_-6.scene','1_0_-10.scene','1_2_-1.scene']:
    if os.path.exists(d+f): parse(d+f)
parse('out/tree/mobile_maps/w1351_fb_jiehun_001/1_3_-5.scene')
o.close();print('ok')
