import numpy as np, struct, io, re
o=io.open('agent_map_05_rec.txt','w',encoding='utf-8')
def W(*a): o.write(' '.join(str(x) for x in a)+'\n')
f='out/tree/mobile_maps/w1351_ll_dl_002/1_0_-6.scene'
raw=open(f,'rb').read()
N,RS=struct.unpack_from('<II',raw,0)
W('file',f,'size',len(raw),'N',N,'RS',RS,'8+N*RS=',8+N*RS)
# print records assuming base=8 stride=RS
for i in range(N+2):
    b=8+i*RS
    if b>=len(raw): W('record',i,'beyond EOF at',b); break
    mat=struct.unpack_from('<16f',raw,b)
    sc=struct.unpack_from('<f',raw,b+64)[0]
    nm=raw[b+68:b+68+700].split(b'\0')[0]
    W('rec%02d @%d mat='%(i,b),[round(x,4) for x in mat],'scale',round(sc,4),'name',nm.decode('latin1')[:50])
    tail=raw[b+68: b+RS+68]
W('\n-- tail scan: u32 columns of record 0 --')
b=8
for off in range(68, 753, 16):
    seg=raw[b+off:b+off+16]
    W('%4d %s  f32=%s u32=%s'%(off,seg.hex(' '),[round(x,4) if abs(x)<1e10 else x for x in struct.unpack('<4f',seg.ljust(4,b'\0'))],struct.unpack('<4I',seg.ljust(4,b'\0'))))
o.close();print('ok')
