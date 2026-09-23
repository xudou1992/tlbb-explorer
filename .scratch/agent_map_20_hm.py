import numpy as np, struct, io, os, glob, collections
o=io.open('agent_map_20_hm.txt','w',encoding='utf-8')
def W(*a): o.write(' '.join(str(x) for x in a)+'\n')
f='out/tree/mobile_maps/w1351_ll_cs_001/w1351_ll_cs_001.map'
raw=open(f,'rb').read()
v,A,B,off=struct.unpack_from('<4I',raw,0); n=A*B; end=off+n*4160
arr=np.frombuffer(raw[off:end],dtype=np.uint8).reshape(n,4160,1)[:,:,0]
b1=arr[:,1::4].ravel(); b2=arr[:,2::4].ravel()
j=collections.Counter(zip(b1.tolist(),b2.tolist()))
W('== joint (b1,b2) pair census over %d cells (%s)'%(n*1040,os.path.basename(f)))
for k,c2 in j.most_common(14): W('   %-10s %9d  %.4f%%'%(str(k),c2,100.0*c2/(n*1040)))
W('   distinct pairs: %d'%len(j))
# also check b1,b2 across all maps quickly
W('\n== per-map byte-lane census (12 maps)')
for g in sorted(glob.glob('out/tree/mobile_maps/*/*.map'), key=lambda p:-os.path.getsize(p))[:12]+ \
    sorted(glob.glob('out/tree/mobile_maps/*/*.map'), key=lambda p:os.path.getsize(p))[:3]:
    raw=open(g,'rb').read(); v,A,B,off=struct.unpack_from('<4I',raw,0); n=A*B; e=off+n*4160
    a=np.frombuffer(raw[off:e],dtype=np.uint8).reshape(n,4160)
    X=a[:,1::4]; Y=a[:,2::4]
    # 2D reshape guess: treat as (n, 1040); find largest square-ish grid
    W('  %-30s nchunk=%-4d b1 uniq=%-3d max=%-4d  b2 uniq=%-3d max=%-4d  frac(0,0)=%.3f'%(
      os.path.basename(g),n,len(np.unique(X)),X.max(),len(np.unique(Y)),Y.max(),
      float(((X==0)&(Y==0)).mean())))
# f32 heightmap search
W('\n== f32-array search over whole .map (window 4096B, all values in [-200,300], smooth)')
def search(raw,name):
    a=np.frombuffer(raw[:len(raw)//4*4],dtype='<f4')
    ok=(np.abs(a)<300)&(a!=-0)
    good=(a>-200)&(a<300)&np.isfinite(a)
    # runs
    idx=np.nonzero(~good)[0]
    best=[]
    prev=0
    for i in idx:
        if i-prev>=300: best.append((prev,i-prev))
        prev=i+1
    if len(a)-prev>=300: best.append((prev,len(a)-prev))
    best.sort(key=lambda t:-t[1])
    W('  %-32s n=%d  longest f32-runs(in [-200,300]): %s'%(name,len(a),[(int(p),int(l)) for p,l in best[:6]]))
    for p,l in best[:3]:
        seg=a[p:p+l]
        d=np.abs(np.diff(seg))
        W('       run @0x%x len=%d  mean %.2f std %.2f  meandiff %.3f'%(p*4,l,seg.mean(),seg.std(),d.mean()))
for g in sorted(glob.glob('out/tree/mobile_maps/*/*.map'), key=lambda p:-os.path.getsize(p))[:4]:
    search(open(g,'rb').read(), os.path.basename(g))
o.close();print('ok')
