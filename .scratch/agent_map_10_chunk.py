import numpy as np, struct, io, os, glob, collections
o=io.open('agent_map_10_chunk.txt','w',encoding='utf-8')
def W(*a): o.write(' '.join(str(x) for x in a)+'\n')
def load(f):
    raw=open(f,'rb').read()
    v,A,B,off=struct.unpack_from('<4I',raw,0)
    return raw,v,A,B,off
for f in sorted(glob.glob('out/tree/mobile_maps/*/*.map'), key=lambda p:-os.path.getsize(p))[:5]+ \
         ['out/tree/mobile_maps/w1351_ll_cs_001/w1351_ll_cs_001.map','out/tree/mobile_maps/w1351_gj_jz_001/w1351_gj_jz_001.map']:
    raw,v,A,B,off=load(f)
    n=A*B; total=off+n*4160
    W('\n#### %s size=%d v=%d A=%d B=%d tabOff=%d nChunk=%d chunkBytes=4160 end=%d rest=%d'%(
      os.path.basename(f),len(raw),v,A,B,off,n,total,len(raw)-total))
    arr=np.frombuffer(raw[off:off+n*4160],dtype=np.uint8).reshape(n,4160)
    # column-wise: how many distinct values per byte-column
    uniq=[len(np.unique(arr[:,c])) for c in range(0,4160,1)]
    nz=[c for c in range(4160) if uniq[c]>1]
    W('  columns with >1 distinct value: %d of 4160'%len(nz))
    W('  first 40 such cols:',nz[:40])
    if nz:
        c=nz[0]; col=arr[:,c]
        W('   col %d: min %d max %d mean %.1f sample %s'%(c,col.min(),col.max(),col.mean(),col[:14].tolist()))
    W('  global byte hist top:', collections.Counter(arr.ravel().tolist()).most_common(8))
    # per-record: what varies
    v1=np.frombuffer(raw[off:off+n*4160],dtype='<u2').reshape(n,2080)
    W('  u16 cols with >1 distinct:', sum(1 for c in range(2080) if len(np.unique(v1[:,c]))>1))
    i16=np.frombuffer(raw[off:off+n*4160],dtype='<i2').reshape(n,2080)
    W('  u16 min=%d max=%d'%(i16.min(),i16.max()))
    # tail sections
    tail=raw[total:]
    W('  tail len',len(tail),'u32[0:12]',struct.unpack_from('<12I',tail,0) if len(tail)>=48 else tail[:40].hex())
o.close(); print('ok')
