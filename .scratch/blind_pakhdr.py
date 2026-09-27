import struct, os, sys
G = 'D:/TLGL/'
PAKS = ['data.pak','data1.pak','data2.pak','data3.pak','data4.pak','data_1.pak']
for p in PAKS:
    path = G + p
    sz = os.path.getsize(path)
    f = open(path, 'rb')
    head = f.read(64)
    print('==', p, 'size', sz)
    print('   head4', head[:4], 'hex', head[:40].hex(' '))
    print('   as u32le[0..16]:', struct.unpack('<16I', head))
    f.seek(max(0, sz - 256))
    tail = f.read()
    print('   tail hex', tail[:64].hex(' '))
    # scan whole file for JPAK magic positions (sample by 4KiB alignment)
    f.seek(0)
    hits = []
    off = 0
    step = 1 << 20
    prev = b''
    while off < sz and len(hits) < 40:
        f.seek(off)
        chunk = f.read(step + 8)
        i = chunk.find(b'JPAK')
        while i >= 0:
            hits.append(off + i)
            i = chunk.find(b'JPAK', i + 1)
        off += step
    print('   JPAK hits(first40):', hits[:40])
    f.close()
