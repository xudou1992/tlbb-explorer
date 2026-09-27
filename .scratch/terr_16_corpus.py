import struct, collections, glob, os, sys

paths = sorted(glob.glob('out/tree/mobile_maps/*/*.map'))
print('maps', len(paths))
nb_tot = 0; nz_tail = 0; tailvals = collections.Counter(); tpos = collections.Counter()
blkset = collections.Counter(); hdrset = collections.Counter(); single = collections.Counter()
uniform = 0; nrec_c = collections.Counter(); recmul = collections.Counter()
comb = collections.Counter()
for p in paths:
    d = open(p, 'rb').read()
    magic, A, B, hdr = struct.unpack('<4I', d[:16]); nb = A*B
    end, nrec, fsz = struct.unpack('<3I', d[16:28])
    blk = (end-hdr)//nb
    blkset[blk] += 1; hdrset[hdr] += 1
    nb_tot += nb
    tail = d[end:]
    recmul[round(len(tail)/nrec) if nrec else 0] += 1
    nrec_c[nrec > 0] += 1
    v = d[hdr:end]
    for bi in range(nb):
        o = bi*blk
        b = v[o:o+4096]
        if b == b[:4]*1024:
            uniform += 1
            single[(b[1], b[2])] += 1
        t = v[o+4096:o+blk]
        if any(t):
            nz_tail += 1
            tailvals[t[:4].hex()] += 1
            for k in range(len(t)):
                if t[k]: tpos[k] += 1
print('block size set', blkset.most_common(), 'header size set', hdrset.most_common())
print('trailer record byte-size (len/nrec) distribution:', recmul.most_common(6))
print('maps total %d, maps with nrec>0: %d' % (len(paths), nrec_c[True]))
print('blocks total', nb_tot, 'with nonzero 64B tail:', nz_tail, '(%.4f%%)' % (100.0*nz_tail/nb_tot))
print('nonzero byte positions inside the 64B tail:', sorted(tpos.items())[:14])
print('tail word values:', tailvals.most_common(6))
print('  as f32:', [round(struct.unpack('<f', bytes.fromhex(h))[0], 6) for h, _ in tailvals.most_common(6)])
print('uniform (single-valued) blocks: %d / %d = %.2f%%' % (uniform, nb_tot, 100.0*uniform/nb_tot))
print('uniform block value histogram:', single.most_common(10))
print('4160 div: /4=%d /16=%d /32=%d /64=%d(=65) /128=32.5 /256=16.25 /512=8.125 /1024=4.0625')
print('ceil((4096+4)/64)*64 =', -(-4100//64)*64, ' ; 4160-4096 =', 4160-4096)
