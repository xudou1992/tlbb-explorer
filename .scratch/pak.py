import struct,binascii,sys
def crc(b): return binascii.crc32(b)&0xFFFFFFFF
def parse(path,show=6):
    f=open(path,'rb'); hdr=f.read(0x20)
    sig,ver,usz,ucrc=struct.unpack('<IIII',hdr[:16])
    assert hdr[:4]==b'JPAK', path
    n,unk=struct.unpack('<II',hdr[16:24])
    print('%s: ver=%d fileSize=%d count=%d (@0x14=%d) hdrGuid=%s'%(path,ver,usz,n,unk,hdr[24:40].hex()))
    f.seek(0x20); tab=f.read(n*36)
    okc=0;okf=0;met={};flg={}
    recs=[]
    for i in range(n):
        r=tab[i*36:(i+1)*36]
        h,off,size,occ,fsz=struct.unpack('<QIIII',r[:24])
        v2,=struct.unpack('<H',r[24:26]); flags=r[26]; method=r[27]; fcrc,ucrc2=struct.unpack('<II',r[28:36])
        recs.append((h,off,size,occ,fsz,v2,flags,method,fcrc))
        if crc(r[:32])==ucrc2: okc+=1
        met[method]=met.get(method,0)+1; flg[flags]=flg.get(flags,0)+1
    for i in list(range(show))+list(range(n-2,n)):
        h,off,size,occ,fsz,v2,flags,method,fcrc=recs[i]
        f.seek(off); b=f.read(size)
        g=crc(b)==fcrc; okf+=g
        print('  %4d h=%016x off=%08x size=%9d occ=%9d fsz=%9d ver=%d flg=%02x met=%02x storedCrc=%s head=%s'%(i,h,off,size,occ,fsz,v2,flags,method,g,b[:12].hex()))
    print('  recordCrc %d/%d ; methods %s ; flags %s'%(okc,n,met,flg))
    return recs
for p in ['data.pak','data1.pak','data2.pak','data3.pak','data4.pak','data_1.pak']:
    try: parse(p)
    except Exception as e: print(p,'ERR',e)
