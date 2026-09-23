import numpy as np, struct, io, os, glob, collections
o=io.open('agent_map_17_map2.txt','w',encoding='utf-8')
def W(*a): o.write(' '.join(str(x) for x in a)+'\n')
f='out/tree/mobile_maps/w1351_ll_cs_001/w1351_ll_cs_001.map'
raw=open(f,'rb').read()
v,A,B,off=struct.unpack_from('<4I',raw,0); n=A*B; end=off+n*4160
W('%s size=%d v=%d A=%d B=%d tab=%d n=%d end=%d tail=%d'%(os.path.basename(f),len(raw),v,A,B,off,n,end,len(raw)-end))
W('header u32[0:38]:', struct.unpack_from('<38I',raw,0))
W('header f32 as pairs:')
for i in range(0,152,4):
    b=raw[i:i+4]
    W('  0x%04x u32=%-12d f32=%-16g'%(i,struct.unpack('<I',b)[0],struct.unpack('<f',b)[0]))
rec=np.frombuffer(raw[off:off+4160*3],dtype=np.uint8).reshape(3,4160)
W('\nchunk0 first 128 bytes:',rec[0,:128].tolist())
W('chunk0 bytes 128..256:',rec[0,128:256].tolist())
W('at chunk boundary: last 32 of c0',rec[0,-32:].tolist(),' first 32 of c1',rec[1,:32].tolist())
# per-column distinct within one chunk (across chunks)
arr=np.frombuffer(raw[off:off+n*4160],dtype=np.uint8).reshape(n,4160)
var=[len(np.unique(arr[:,cc])) for cc in range(4160)]
W('\ncolumns always-0:',sum(1 for x in var if x==1))
runs=[];s=None
for i,x in enumerate(var):
    if x==1 and s is None: s=i
    if x>1 and s is not None:
        if i-s>4: runs.append((s,i-1))
        s=None
W('constant-column runs (start,end,len):',[(a,b,b-a+1) for a,b in runs][:25])
# treat as 1040 x u32; print as u32
u=np.frombuffer(raw[off:off+n*4160],dtype='<u4').reshape(n,1040)
W('\nu32 view: col0 always0=%s ; sample chunk0 u32[0:20]=%s'%(bool((u[:,0]==0).all()),u[0,:20].tolist()))
W('  u32 max %d ; how many cols vary:'%u.max(),sum(1 for cc in range(1040) if len(np.unique(u[:,cc]))>1))
lo=(u&0xff); hi=(u>>8)&0xff; top=(u>>16)&0xff; q=(u>>24)&0xff
for nm,x in (('b0',lo),('b1',hi),('b2',top),('b3',q)):
    W('  byte %s: min %d max %d uniq %d hist %s'%(nm,x.min(),x.max(),len(np.unique(x)),collections.Counter(x.ravel().tolist()).most_common(5)))
W('\n== tail sections hex (first 256B)')
t=raw[end:]
for i in range(0,min(256,len(t)),16):
    W('  %06x %s |%s|'%(i,t[i:i+16].hex(' '),''.join(chr(c) if 32<=c<127 else '.' for c in t[i:i+16])))
W('tail len',len(t))
# ptr census whole file
a=np.frombuffer(raw[:len(raw)//8*8],dtype='<u8')
m=(((a>>32)>=0x7f00)&((a>>32)<=0x7fff))
idx=np.nonzero(m)[0]*8
W('\nwhole-file 0x7f.. u64: n=%d density %.2f/KB ; offsets<1024: %d ; in chunk table: %d ; in tail: %d'
  %(len(idx),len(idx)*1024.0/len(raw),int((idx<1024).sum()),int(((idx>=off)&(idx<end)).sum()),int((idx>=end).sum())))
W('first 12 ptr offsets:',idx[:12].tolist())
o.close();print('ok')
