import numpy as np, struct, io, re, os, glob, collections
o=io.open('agent_map_07_stride.txt','w',encoding='utf-8')
def W(*a): o.write(' '.join(str(x) for x in a)+'\n')
PAT=re.compile(rb'[A-Za-z0-9_\-]{6,}\.(mesh|pu|scene|tga|dds)\0')

def report(path):
    raw=open(path,'rb').read()
    N,RS,Z=struct.unpack_from('<III',raw,0)
    ms=[m.start() for m in PAT.finditer(raw)]
    d=[b-a for a,b in zip(ms,ms[1:])]
    dd=collections.Counter(d)
    pred=12+761*N
    W('%-46s size=%-8d N=%-5d RS=%-4d nstr=%-5d 12+761N=%-8d diff=%-7d stridediffs=%s'
      % (os.path.basename(os.path.dirname(path))+'/'+os.path.basename(path), len(raw), N, RS, len(ms), pred, len(raw)-pred, dd.most_common(4)))

for f in sorted(glob.glob('out/tree/mobile_maps/w1351_ll_dl_002/*.scene'))[:12]: report(f)
W('')
for f in ['out/tree/mobile_maps/w1351_fb_jiehun_001/1_3_-5.scene','out/tree/mobile_maps/w1351_ll_yxh_001/1_4_-8.scene']:
    if os.path.exists(f): report(f)

W('\n== GLOBAL: does 12+761*N >= size always? sample 900 grid753 scenes')
bad=collections.Counter(); nn=0
sizes=[]
for f in glob.glob('out/tree/mobile_maps/*/*.scene'):
    st=os.stat(f)
    if not (500 < st.st_size < 400000): continue
    with open(f,'rb') as fh: hdr=fh.read(12)
    if len(hdr)<12: continue
    N,RS,Z=struct.unpack('<III',hdr)
    if RS!=753 or N==0 or N>5000: continue
    nn+=1
    d=st.st_size-(12+761*N)
    sizes.append(d)
    if d>=0: bad['size_ge_pred']+=1
    elif d<-1600: bad['deficit_gt1600']+=1
    else: bad['deficit_le1600']+=1
    if (Z!=0): bad['Znonzero']+=1
W('n=%d'%nn, dict(bad))
a=np.array(sizes); W('deficit percentiles p0/p1/p50/p95/p99:', np.percentile(a,[0,1,50,95,99]))
W('RS values seen:', 'only 753' if nn else '')
o.close(); print('ok')
