import numpy as np, struct, io, os, glob, re, collections, random
o=io.open('agent_map_31_axes.txt','w',encoding='utf-8')
def W(*a): o.write(' '.join(str(x) for x in a)+'\n')
NAMEOK=re.compile(rb'^[A-Za-z0-9_\-\.]{4,80}$')
fs=glob.glob('out/tree/mobile_maps/*/*.scene'); random.seed(5); fs=random.sample(fs,600)
M=[]; n=0
for f in fs:
    raw=open(f,'rb').read()
    if len(raw)<12: continue
    N,RS,Z=struct.unpack_from('<III',raw,0)
    if RS not in (753,749): continue
    st=RS+8
    for i in range(N):
        b=12+st*i
        if b+65>len(raw): break
        nm=raw[b+64:b+64+st-64].split(b'\0',1)[0]
        if not NAMEOK.match(nm): continue
        m=np.array(struct.unpack_from('<16f',raw,b))
        if np.abs(m[12:15]).max()>4000: continue
        M.append(m); n+=1
A=np.stack(M)
W('records with sane matrix: %d'%n)
W('mean |m[4],m[6],m[7]| (row1 off-diagonal + w) = %.5f, %.5f, %.5f ; |m[5]| median %.4f'%
  (np.abs(A[:,4]).mean(),np.abs(A[:,6]).mean(),np.abs(A[:,7]).mean(),np.median(np.abs(A[:,5]))))
W('mean |m[1],m[2],m[3]| (row0) = %.5f %.5f %.5f ; |m[0]|,|m[8]|,|m[10]| vs |m[5]| equal? frac(|r0norm-r1norm|<1e-3)=%.4f'
  %(np.abs(A[:,1]).mean(),np.abs(A[:,2]).mean(),np.abs(A[:,3]).mean(), np.mean(np.abs(np.linalg.norm(A[:,0:4],axis=1)-np.abs(A[:,5]))<1e-3)))
r0=np.linalg.norm(A[:,0:3],axis=1); r1=np.abs(A[:,5]); r2=np.linalg.norm(A[:,8:11],axis=1)
W('row norms: |r0-r1|<1e-3 frac %.4f ; |r2-r1|<1e-3 frac %.4f  => uniform-scale, Y axis = row1'%(
  np.mean(np.abs(r0-r1)<1e-3), np.mean(np.abs(r2-r1)<1e-3)))
W('m[3],m[7],m[11] (4th col) mean abs: %.5f %.5f %.5f ; m[15] values %s'%(np.abs(A[:,3]).mean(),np.abs(A[:,7]).mean(),np.abs(A[:,11]).mean(),collections.Counter(A[:,15].round(3).tolist()).most_common(3)))
W('XZ rotation only? mean |m[1]|(row0.y)=%.5f mean |m[9]|(row2.y)=%.5f'%(np.abs(A[:,1]).mean(),np.abs(A[:,9]).mean()))
# cross-check: dot(row0,row2) ~ 0
W('orthogonality row0.row2/(|r0||r2|) mean abs %.5f'%np.mean(np.abs((A[:,0:3]*A[:,8:11]).sum(1)/(r0*r2+1e-9))))
o.close(); print('ok')
