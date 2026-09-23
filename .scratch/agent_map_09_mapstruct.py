import numpy as np, re, io, os, struct, collections, glob
o=io.open('agent_map_09_mapstruct.txt','w',encoding='utf-8')
def W(*a): o.write(' '.join(str(x) for x in a)+'\n')
files=sorted(glob.glob('out/tree/mobile_maps/*/*.map'), key=lambda p:-os.path.getsize(p))
W('.map files: %d ; biggest 6: %s'%(len(files),[os.path.basename(x) for x in files[:6]]))
W('\n== header u32[0:24] for 6 largest')
for f in files[:6]:
    raw=open(f,'rb').read()
    W('%-40s size=%d hdr=%s'%(os.path.basename(f),len(raw),struct.unpack_from('<24I',raw,0)))

f=files[0]; raw=open(f,'rb').read()
W('\n#### deep look %s'%f)
W('u32[0:32] ', struct.unpack_from('<32I',raw,0))
W('f32[2:20] ', [round(x,5) for x in struct.unpack_from('<18f',raw,8)])
W('f64[1:8]  ', struct.unpack_from('<7d',raw,8))
S=[(m.start(),m.group().decode('latin1')) for m in re.finditer(rb'[\x20-\x7e]{5,}',raw)]
W('n printable-runs>=5:',len(S))
ext=collections.Counter()
for p,s in S:
    mm=re.search(r'\.([A-Za-z]{2,5})$',s); ext[mm.group(1) if mm else '(noext)']+=1
W('ext hist',dict(ext.most_common(12)))
W('first 25 strings:',S[:25])
# 8-byte periodic autocorrelation of byte array to find block structure
a=np.frombuffer(raw,dtype=np.uint8)
# entropy in 64KB blocks
nb=len(raw)//65536
W('\nper-64KB block: uniqByteCount, meanOfAbsDiff, nPtr')
for i in range(min(nb,40)):
    blk=a[i*65536:(i+1)*65536]
    d=np.abs(np.diff(blk.astype(np.int16))).mean()
    u64=np.frombuffer(blk[:len(blk)//8*8],dtype='<u8')
    nptr=int((((u64>>32)>=0x7f00)&((u64>>32)<=0x7fff)).sum())
    W('  %2d uniq=%3d meandiff=%6.2f ptr=%d'%(i,len(np.unique(blk)),d,nptr))
# zero runs
z=(a==0)
runs=[]; s=None
for i,v in enumerate(z):
    if v and s is None: s=i
    if not v and s is not None:
        if i-s>=256: runs.append((s,i-s))
        s=None
W('\nzero runs >=256: %d'%len(runs), runs[:20])
# value histogram of bytes 0x90..0x90000
W('\nhist 0x90..0x40000:', collections.Counter(a[0x90:0x40000].tolist()).most_common(10))
i16=np.frombuffer(raw[0x90:0x90+ (len(raw)-0x90)//2*2],dtype='<i2')
W('i16 view @0x90: n=%d min=%d max=%d mean=%.1f uniq=%d'%(len(i16),i16.min(),i16.max(),i16.mean(),len(np.unique(i16))))
o.close(); print('ok')
