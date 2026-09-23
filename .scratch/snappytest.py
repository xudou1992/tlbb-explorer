import struct, sys
sys.path.insert(0, r'D:\TLGL\.scratch')
from pakdec import parse_index, dec

def snappy_decode(src, out_len_max=64*1024*1024):
    """Strict raw-snappy block decoder. Returns (data, consumed) or raises."""
    n = len(src); p = 0
    # varint uncompressed length
    length = 0; shift = 0
    while True:
        b = src[p]; p += 1
        length |= (b & 0x7F) << shift
        if not (b & 0x80): break
        shift += 7
        if shift > 35: raise ValueError('bad varint')
    out = bytearray()
    while p < n:
        tag = src[p]; p += 1
        t = tag & 3
        if t == 0:                      # literal
            ln = tag >> 2
            if ln < 60:
                ln += 1
            else:
                nb = ln - 59
                if p + nb > n: raise ValueError('trunc len')
                ln = int.from_bytes(src[p:p+nb], 'little') + 1
                p += nb
            if p + ln > n: raise ValueError('trunc literal at %d need %d have %d' % (p, ln, n-p))
            out += src[p:p+ln]; p += ln
        else:
            if t == 1:
                ln = 4 + ((tag >> 2) & 7); off = ((tag >> 5) << 8) | src[p]; p += 1
            elif t == 2:
                ln = tag >> 2; off = int.from_bytes(src[p:p+2], 'little'); p += 2
            else:
                ln = tag >> 2; off = int.from_bytes(src[p:p+4], 'little'); p += 4
            if off == 0 or off > len(out): raise ValueError('bad copy offset at %d' % p)
            if ln == 0: raise ValueError('ln0')
            if len(out) + ln > out_len_max: raise ValueError('too big')
            s = len(out) - off
            for i in range(ln):
                out.append(out[s+i])
            if len(out) > length: raise ValueError('overflow declared len')
    if len(out) != length: raise ValueError('produced %d != declared %d' % (len(out), length))
    return bytes(out), p

f, recs = parse_index(r'D:\TLGL\data1.pak')
for idx in (0, 1, 2):
    rec = recs[idx]
    f.seek(rec['off']); raw = f.read(rec['size'])
    d = dec(rec['hash'], rec['size'], raw)
    print('rec%d meth=%d size=%d osize=%d' % (idx, rec['meth'], rec['size'], rec['osize']))
    for skip in (0, 4):
        try:
            out, consumed = snappy_decode(d[skip:])
            print('   snappy@%d OK -> %d bytes, consumed %d/%d  head=%r' % (skip, len(out), consumed, len(d)-skip, out[:24]))
        except Exception as e:
            print('   snappy@%d fail: %s' % (skip, str(e)[:90]))
