"""Walk the generation chain inside a JPAK container.

Layout discovered:
  gen0: [32B header "JPAK"][N*36 Index records][payloads]
  genK: [16B header count,count2,pid][N*36 Index records][payloads]
Each generation is appended after the previous one's payload area; later
generations supersede earlier entries with the same uHash.
"""
import struct, sys, zlib


def crc(b):
    return zlib.crc32(b) & 0xFFFFFFFF


def rec_ok(buf, p):
    if p + 36 > len(buf):
        return False
    r = buf[p:p + 36]
    h, off, size, occ, ofsz, ver, fl, me, fcrc, ucrc = struct.unpack('<QIIIIHBBII', r)
    return ucrc == crc(r[:32]) and me in (0, 51) and fl < 64 and ver < 0x10000


def walk(path, verbose=True):
    data = open(path, 'rb').read()
    assert data[:4] == b'JPAK'
    gens = []
    p = 0
    while True:
        if p == 0:
            ver, fsize, hcrc, n, n2 = struct.unpack('<IIIII', data[4:24])
            pid = data[24:32]
            hdr = 32
        else:
            n, n2 = struct.unpack('<II', data[p:p + 8])
            pid = data[p + 8:p + 16]
            hdr = 16
            ver = fsize = 0
        if n == 0 or n > 200000:
            break
        rp = p + hdr
        if not rec_ok(data, rp):
            break
        pend = rp + n * 36
        first = struct.unpack('<QIIIIHBBII', data[rp:rp + 36])
        gens.append(dict(base=p, hdr=hdr, n=n, rp=rp, rend=pend, pid=pid.hex(),
                         payload0=pend, last_off_end=first[1] + first[2]))
        if verbose:
            print('gen%-3d @0x%09x hdr=%2d n=%-6d index 0x%09x..0x%09x  rec0.off=0x%x size=%d' % (
                len(gens) - 1, p, hdr, n, rp, pend, first[1], first[2]))
        # payload end for this generation = max(off+occ) over records
        mx = 0
        for i in range(n):
            r = data[rp + i * 36:rp + i * 36 + 36]
            h, off, size, occ, ofsz, v2, fl, me, fcrc, ucrc = struct.unpack('<QIIIIHBBII', r)
            if off + occ > mx:
                mx = off + occ
        if mx <= pend:
            break
        p = mx
        if p >= len(data):
            break
    return data, gens


if __name__ == '__main__':
    for p in sys.argv[1:] or ['data.pak', 'data1.pak', 'data2.pak', 'data3.pak', 'data4.pak', 'data_1.pak']:
        path = r'D:\TLGL' + '\\' + p
        print('=====', p, hex(len(open(path, 'rb').read())))
        data, gens = walk(path)
        tot = sum(g['n'] for g in gens)
        print('  -> %d generations, %d records total' % (len(gens), tot))
