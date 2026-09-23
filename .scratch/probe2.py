import struct, sys, math, zlib
sys.path.insert(0, r'D:\TLGL\.scratch')
from pakdec import parse_index, dec, crc

f, recs = parse_index(r'D:\TLGL\data1.pak')
rec = recs[0]
f.seek(rec['off']); raw = f.read(rec['size'])
d = dec(rec['hash'], rec['size'], raw)
print('rec0 flags=%02x meth=%d size=%d osize=%d' % (rec['flags'], rec['meth'], rec['size'], rec['osize']))
print('raw  [0:16] =', raw[:16].hex(), repr(raw[:12]))
print('dec  [0:16] =', d[:16].hex(), repr(d[:12]))
for name, off in (('raw', 0), ('dec', 4)):
    pass
print('u32le raw[0:4] =', struct.unpack('<I', raw[:4])[0], ' u32be =', struct.unpack('>I', raw[:4])[0])
print('u32le dec[0:4] =', struct.unpack('<I', d[:4])[0])

def ent(b):
    h = [0]*256
    for x in b: h[x]+=1
    n=len(b); return -sum((c/n)*math.log2(c/n) for c in h if c)
print('entropy raw=%.3f dec=%.3f decbody=%.3f' % (ent(raw), ent(d), ent(d[4:])))
body = d[4:]
cands = {}
for lbl, wb in (('zlib',15),('raw-deflate',-15),('gzip',31)):
    try:
        out = zlib.decompress(body, wb); cands[lbl]=('OK',len(out))
    except Exception as e: cands[lbl]=('fail',str(e)[:40])
print(cands)
# try whole decrypted
for lbl, wb in (('zlib',15),('raw-deflate',-15)):
    try: print('whole',lbl,zlib.decompress(d,wb)[:20])
    except Exception as e: print('whole',lbl,'fail',str(e)[:50])
