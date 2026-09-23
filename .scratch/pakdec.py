import struct, binascii, os, sys
T = struct.unpack('<4096I', open(r'D:\TLGL\.scratch\table.bin','rb').read())
M = 0xFFFFFFFF
def crc(b): return binascii.crc32(bytes(b)) & M

def keystream_init(key, size):
    v6 = crc(struct.pack('<Q', key))
    return crc(struct.pack('<I', size) , ) if False else (~crc2(v6 ^ 0x8088405, struct.pack('<I', size))) & M

def crc2(seed, b):
    # emulate sub_1405B0510(a1=seed, buf, len): i = ~seed; byte loop; return ~i
    i = (~seed) & M
    for c in b:
        i = CT[(i ^ c) & 0xFF] ^ (i >> 8)
    return (~i) & M

# verify crc2(seed=0, data) == binascii.crc32
CT = [binascii.crc32(bytes([i])) & M ^ 0 for i in range(256)]
# rebuild proper reflected table
CT = []
for i in range(256):
    r = i
    for _ in range(8):
        r = (r >> 1) ^ (0xEDB88320 if r & 1 else 0)
    CT.append(r & M)
assert crc2(0, b'123456789') == 0xCBF43926, hex(crc2(0,b'123456789'))

def dec(key, size, buf):
    """sub_1405A1CE0: in-place decrypt of buf (len==size) keyed by u64 hash."""
    out = bytearray(buf)
    v = crc2(crc2(0, struct.pack('<Q', key)) ^ 0x8088405, struct.pack('<I', size))
    ndw = size >> 2
    nrem = size & 3
    c = 0
    while c < ndw:
        v12 = (v - c - 1) & 0xFFFF
        if v12 >= 0x8000: v12 -= 0x10000
        idx = ((ndw & 0xFFFF) + v12) & 0xFFF
        v = (T[idx] + 778904513) & M
        struct.pack_into('<I', out, 4*c, struct.unpack_from('<I', out, 4*c)[0] ^ v)
        c += 1
    if nrem:
        x = T[nrem] ^ v
        p = 4*ndw
        for k in range(nrem):
            out[p+k] ^= (x >> (8*k)) & 0xFF
    return bytes(out)

def parse_index(path):
    f = open(path, 'rb')
    hdr = f.read(0x20)
    assert hdr[:4] == b'JPAK'
    ver, fsz, ucrc, n, n2 = struct.unpack('<IIIII', hdr[4:24])
    f.seek(0x20); tab = f.read(n*36)
    recs = []
    for i in range(n):
        r = tab[i*36:(i+1)*36]
        h, off, size, occ, ofsz = struct.unpack('<QIIII', r[:24])
        rv, = struct.unpack('<H', r[24:26])
        recs.append(dict(i=i, hash=h, off=off, size=size, occ=occ, osize=ofsz,
                         ver=rv, flags=r[26], meth=r[27]))
    return f, recs

if __name__ == '__main__':
    path = r'D:\TLGL\data.pak'
    f, recs = parse_index(path)
    for rec in recs[:6] + recs[-4:]:
        f.seek(rec['off']); raw = f.read(rec['size'])
        enc = rec['flags'] & 4
        d = dec(rec['hash'], rec['size'], raw) if enc else raw
        print('%4d flg=%02x met=%02d size=%8d enc=%d -> %s' % (
            rec['i'], rec['flags'], rec['meth'], rec['size'], enc, d[:32].hex()))
        print('      ascii: %r' % d[:48])
