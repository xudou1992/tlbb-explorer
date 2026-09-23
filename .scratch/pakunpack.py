"""JPAK (data*.pak) unpacker for TLGL / tlbbgl_x64.exe.

Pipeline per Index record (36 B, at pak offset 0x20):
  raw = file[off : off+uSize]
  if flags & 4 : decrypt(raw, key=u64 hash, len=uSize)        -> sub_1405A1CE0
  if flags & 1 : strip manifest u8 len|path|u32|u64|u32 crc   -> +len+17 bytes
  method 0 -> stored, 0x33 -> raw snappy block                -> sub_1405B4C50
Read-only on the .pak files; everything is written under .scratch/out.
"""
import argparse
import binascii
import json
import os
import struct
import sys
from array import array

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cramjam
from snappy import _read_varint

M = 0xFFFFFFFF
CT = []
for _i in range(256):
    _r = _i
    for _ in range(8):
        _r = (_r >> 1) ^ (0xEDB88320 if _r & 1 else 0)
    CT.append(_r & M)

TAB = struct.unpack('<4096I', open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                'table.bin'), 'rb').read())


def crc(b, seed=0):
    return binascii.crc32(b, seed) & M


def crc2(seed, b):
    """sub_1405B0510: reflected crc32 with a non-standard initial/final fold."""
    i = (~seed) & M
    for c in b:
        i = CT[(i ^ c) & 0xFF] ^ (i >> 8)
    return (~i) & M


def decrypt(key, size, buf):
    import numpy as np
    v = crc2(crc2(0, struct.pack('<Q', key)) ^ 0x8088405, struct.pack('<I', size))
    ndw, nrem = size >> 2, size & 3
    out = bytearray(buf)
    if ndw:
        T = TAB
        ks = array('I', bytes(4 * ndw))
        for c in range(ndw):
            v = (T[(ndw + v - c - 1) & 0xFFF] + 778904513) & M
            ks[c] = v
        out[0:4 * ndw] = (np.frombuffer(buf[:4 * ndw], dtype='<u4') ^
                          np.asarray(ks)).astype('<u4').tobytes()
    if nrem:
        x = (TAB[nrem] ^ v) & M
        p = 4 * ndw
        for k in range(nrem):
            out[p + k] ^= (x >> (8 * k)) & 0xFF
    return bytes(out)


REC = struct.Struct('<QIIIIHBBII')


def read_index(path):
    with open(path, 'rb') as f:
        hdr = f.read(0x20)
        if hdr[:4] != b'JPAK':
            raise SystemExit('%s: not a JPAK' % path)
        ver, fsize, hcrc, n, n2 = struct.unpack('<IIIII', hdr[4:24])
        pid = hdr[24:32]
        assert crc(hdr[0:12]) == hcrc, '%s: header crc' % path
        f.seek(0x20)
        tab = f.read(n * 36)
    recs = []
    for i in range(n):
        r = tab[i * 36:(i + 1) * 36]
        h, off, size, occ, ofsz, rver, flags, meth, fcrc, ucrc = REC.unpack(r)
        recs.append(dict(i=i, hash=h, off=off, size=size, occ=occ, osize=ofsz,
                         ver=rver, flags=flags, meth=meth, fcrc=fcrc, ucrc=ucrc,
                         rrec=r))
    return dict(path=path, ver=ver, fsize=fsize, n=n, pid=pid, recs=recs)


MAGIC_EXT = [
    (b'JMT1', '.jmt'), (b'\x89PNG', '.png'), (b'RIFF', '.wav'),
    (b'BM', '.bmp'), (b'\x00\x00\x00\x0cftyp', '.mp4'), (b'OggS', '.ogg'),
    (b'\xff\xd8\xff', '.jpg'), (b'PK\x03\x04', '.zip'), (b'MZ', '.exe'),
    (b'\x7fELF', '.elf'), (b'<Mesh', '.mesh'), (b'[System', '.ini'),
]


def guess_ext(data):
    for magic, ext in MAGIC_EXT:
        if data.startswith(magic):
            return ext
    return '.bin'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--paks', nargs='*', default=None)
    ap.add_argument('--outdir', default=r'D:\TLGL\.scratch\out')
    ap.add_argument('--dry', action='store_true', help='verify only, do not write/decompress')
    ap.add_argument('--max', type=int, default=0)
    ap.add_argument('--every', type=int, default=1)
    args = ap.parse_args()

    paks = args.paks or ['data.pak', 'data1.pak', 'data2.pak', 'data3.pak', 'data4.pak', 'data_1.pak']
    stats = dict(recs=0, encrypted=0, manifest=0, stored_crc_ok=0, rec_crc_ok=0, skipped=0,
                 snappy=0, none=0, other={}, empty=0, written=0, bytes_out=0,
                 meth_crc_ok=0, meth_crc_bad=0, fails=[])
    seen_paths = {}
    for p in paks:
        path = os.path.join(r'D:\TLGL', p)
        pkg = read_index(path)
        stem = os.path.splitext(p)[0]
        f = open(path, 'rb')
        for rec in pkg['recs']:
            stats['recs'] += 1
            if crc(rec['rrec'][:32]) != rec['ucrc']:
                stats['fails'].append((p, rec['i'], 'record crc'))
                continue
            stats['rec_crc_ok'] += 1
            if rec['i'] % args.every:
                stats['skipped'] += 1
                continue
            f.seek(rec['off'])
            raw = f.read(rec['size'])
            if len(raw) != rec['size']:
                stats['fails'].append((p, rec['i'], 'short read'))
                continue
            if crc(raw) == rec['fcrc']:
                stats['stored_crc_ok'] += 1
            else:
                stats['fails'].append((p, rec['i'], 'stored crc'))
                continue
            if rec['size'] == 0:
                stats['empty'] += 1
                continue
            body = raw
            if rec['flags'] & 4:
                stats['encrypted'] += 1
                body = decrypt(rec['hash'], rec['size'], raw)
            man = None
            if rec['flags'] & 1:
                stats['manifest'] += 1
                pl = body[0]
                man = dict(path=(body[1:1 + pl].split(b'\x00')[0].split(b' ')[0]).decode('mbcs', 'replace'),
                           f1=struct.unpack('<I', body[1 + pl:5 + pl])[0],
                           ft=struct.unpack('<Q', body[5 + pl:13 + pl])[0],
                           crc=struct.unpack('<I', body[13 + pl:17 + pl])[0])
                body = body[1 + pl + 16:]
            if rec['meth'] == 0:
                stats['none'] += 1
                out = body
            elif rec['meth'] == 0x33:
                stats['snappy'] += 1
                if args.dry:
                    ln, _ = _read_varint(body, 0)
                    if ln != rec['osize']:
                        stats['fails'].append((p, rec['i'], 'varint %d != osize %d' % (ln, rec['osize'])))
                    out = body[:0]
                else:
                    try:
                        out = bytes(cramjam.snappy.decompress_raw(body))
                    except Exception as e:
                        stats['fails'].append((p, rec['i'], 'snappy %s' % e))
                        continue
            else:
                stats['other'][rec['meth']] = stats['other'].get(rec['meth'], 0) + 1
                continue
            if not args.dry and len(out) != rec['osize']:
                stats['fails'].append((p, rec['i'], 'size %d != %d' % (len(out), rec['osize'])))
                continue
            if man:
                if crc(out) == man['crc']:
                    stats['meth_crc_ok'] += 1
                else:
                    stats['meth_crc_bad'] += 1
            if args.dry:
                continue
            rel = man['path'] if man and man['path'] else 'hash_%016x%s' % (rec['hash'], guess_ext(out))
            dest = os.path.join(args.outdir, stem, rel.replace('\\', '/').lstrip('/'))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            if os.path.exists(dest):
                seen_paths[dest] = seen_paths.get(dest, 0) + 1
                dest += '.dup%d' % seen_paths[dest]
            with open(dest, 'wb') as o:
                o.write(out)
            stats['written'] += 1
            stats['bytes_out'] += len(out)
            if args.max and stats['written'] >= args.max:
                break
        f.close()
    json.dump({k: v for k, v in stats.items() if k != 'fails'}, sys.stdout, indent=1)
    print()
    print('fails: %d' % len(stats['fails']))
    for x in stats['fails'][:20]:
        print('  ', x)


if __name__ == '__main__':
    main()
