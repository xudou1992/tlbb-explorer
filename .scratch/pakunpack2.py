"""JPAK (data*.pak) unpacker for TLGL / tlbbgl_x64.exe — generation-chain aware.

Container layout
  gen0 : [32B "JPAK" header][N x 36B Index][payloads]
  genK : [16B header: count, count2, pid][N x 36B Index][payloads]   (appended after
         the previous generation's payload end; later gens supersede same uHash)

Index record (36B, little endian)
  +0  u64 uHash        file-name hash; also the stream-cipher key
  +8  u32 uOffset      payload offset in this .pak
  +12 u32 uSize        stored (compressed+encrypted) size
  +16 u32 uOccupied    bytes taken at uOffset (next record offset == off+occ)
  +20 u32 uFileSize    original size
  +24 u16 usVersion
  +26 u8  flags        bit0 manifest prefix, bit1 locked/skip, bit2 encrypted, bit3 +1B pad
  +27 u8  method       0 = stored, 0x33 = raw Snappy block
  +28 u32 uFileCrc     crc32 of stored bytes
  +32 u32 uCrc         crc32 of record[0:32]

Per record:  decrypt(flags&4) -> strip manifest(flags&1) -> uncompress(method)
Read-only on the .pak files; output goes under .scratch/out.
"""
import argparse
import binascii
import json
import mmap
import os
import struct
import zlib
import sys
from array import array

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cramjam
import numpy as np
from snappy import _read_varint

M = 0xFFFFFFFF
CT = []
for _i in range(256):
    _r = _i
    for _ in range(8):
        _r = (_r >> 1) ^ (0xEDB88320 if _r & 1 else 0)
    CT.append(_r & M)

HERE = os.path.dirname(os.path.abspath(__file__))
TAB = struct.unpack('<4096I', open(os.path.join(HERE, 'table.bin'), 'rb').read())
REC = struct.Struct('<QIIIIHBBII')
KNOWN_METH = (0, 0x33)


def crc(b, seed=0):
    return binascii.crc32(b, seed) & M


def crc2(seed, b):
    """sub_1405B0510 (the engine's own crc32 wrapper)."""
    i = (~seed) & M
    for c in b:
        i = CT[(i ^ c) & 0xFF] ^ (i >> 8)
    return (~i) & M


def decrypt(key, size, buf):
    """sub_1405A1CE0 — keystream v_{c+1} = T[(ndw + v_c - c - 1) & 0xFFF] + 0x2E62B201."""
    v = crc2(crc2(0, struct.pack('<Q', key)) ^ 0x8088405, struct.pack('<I', size))
    ndw, nrem = size >> 2, size & 3
    out = bytearray(buf)
    if ndw:
        T = TAB
        ks = array('I', bytes(4 * ndw))
        for c in range(ndw):
            v = (T[(ndw + v - c - 1) & 0xFFF] + 778904513) & M
            ks[c] = v
        out[:4 * ndw] = (np.frombuffer(bytes(buf[:4 * ndw]), dtype='<u4') ^
                         np.asarray(ks)).astype('<u4').tobytes()
    if nrem:
        x = (TAB[nrem] ^ v) & M
        for k in range(nrem):
            out[4 * ndw + k] ^= (x >> (8 * k)) & 0xFF
    return bytes(out)


def rec_ok(data, p):
    r = data[p:p + 36]
    if len(r) < 36:
        return False
    _, off, size, occ, ofsz, ver, fl, me, fcrc, ucrc = REC.unpack(r)
    return ucrc == crc(r[:32]) and me in KNOWN_METH and fl < 64 and ver < 0x10000 and occ >= size


def walk_generations(data):
    """Return [(index_records_start, count, payload_end)] for the whole chain.

    以前这里靠「上一条 payload 的末尾」猜下一个索引数组的位置，读 data.pak 这类
    顺序追加的包碰巧对得上；`data_1.pak` 是更新器写的补丁包，数组之间不连着排，
    于是第一代之后就读不到链了（实测：只拿到 1,000 条，而引擎侧的 Rust 解析器
    顺着 `next` 指针拿到 14 个数组 / 13,684 条）。现在与 Rust `jpak::reader::walk`
    同一口径：数组头是 [cap, used, next, crc]，crc 是头前 12 字节的 zlib crc32，
    下一个数组在 `next` 指的地方，`next == 0` 结束。
    """
    gens = []
    at = 16                                  # 文件头 16B，第一个数组紧跟其后
    while at:
        if at + 16 > len(data):
            break
        cap, used, nxt, crc = struct.unpack_from('<4I', data, at)
        if zlib.crc32(data[at:at + 12]) & 0xFFFFFFFF != crc:
            break
        if used > cap or cap > 65536:
            break
        rp = at + 16
        mx = rp + used * 36
        for i in range(used):
            _h, off, size, occ, _o, _v, _f, _m, _c, _u = REC.unpack_from(data, rp + i * 36)
            if off + occ > mx:
                mx = off + occ
        gens.append((rp, used, mx))
        at = nxt
    return gens


MAGIC_EXT = [(b'JMT1', '.jmt'), (b'\x89PNG\r\n\x1a\n', '.png'), (b'RIFF', '.wav'),
             (b'OggS', '.ogg'), (b'\xff\xd8\xff', '.jpg'), (b'PK\x03\x04', '.zip'),
             (b'MZ\x90\x00', '.exe'), (b'BM', '.bmp'), (b'ID3', '.mp3'),
             (b'\x00\x00\x00\x0cftyp', '.mp4'), (b'\x00\x00\x00\x18ftyp', '.mp4'),
             (b'\x1a\x45\xdf\xa3', '.mkv'), (b'GIF8', '.gif'), (b'\x7fELF', '.elf')]


def guess_kind(head):
    for magic, ext in MAGIC_EXT:
        if head.startswith(magic):
            return ext
    if head[:1] == b'<' or head[:5].upper() == b'<?XML':
        return '.xml'
    if head[:8] == b'Copyright ' or b'julegame' in head[:64]:
        return '.dat'
    return '.bin'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--paks', nargs='*')
    ap.add_argument('--outdir', default=r'D:\TLGL\.scratch\out')
    ap.add_argument('--list', action='store_true', help='index + paths only, no payload decode')
    ap.add_argument('--max', type=int, default=0)
    ap.add_argument('--gen', type=int, default=-1)
    args = ap.parse_args()

    paks = args.paks or ['data.pak', 'data1.pak', 'data2.pak', 'data3.pak', 'data4.pak', 'data_1.pak']
    st = dict(gens=0, records=0, unique=0, dup=0, locked=0, manifest=0, encrypted=0,
              snappy=0, stored=0, other_meth={}, empty=0, written=0, bytes_out=0,
              stored_crc_ok=0, rec_crc_ok=0, man_crc_ok=0, man_crc_bad=0,
              size_mismatch=0, fails=[])
    merged = {}
    listing = []
    for p in paks:
        path = os.path.join(r'D:\TLGL', p)
        with open(path, 'rb') as f:
            data = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
            gens = walk_generations(data)
            st['gens'] += len(gens)
            stem = os.path.splitext(p)[0]
            for gi, (rp, n, _end) in enumerate(gens):
                if args.gen >= 0 and gi != args.gen:
                    continue
                for i in range(n):
                    r = data[rp + i * 36:rp + i * 36 + 36]
                    h, off, size, occ, ofsz, ver, fl, me, fcrc, ucrc = REC.unpack(r)
                    st['records'] += 1
                    if crc(r[:32]) != ucrc:
                        st['fails'].append((stem, gi, i, 'record crc'))
                        continue
                    st['rec_crc_ok'] += 1
                    key = (stem, h)
                    if key in merged:
                        st['dup'] += 1
                    merged[key] = (stem, gi, off, size, occ, ofsz, ver, fl, me, fcrc)
            data.close()
    st['unique'] = len(merged)
    if args.list:
        json.dump({k: v for k, v in st.items() if k != 'fails'}, sys.stdout, indent=1)
        print('\nfails: %d' % len(st['fails']))
        for k, v in sorted(merged.items()):
            listing.append('%016x\t%s\tgen%d\t%d\t%d\t%d\t%d\t%02x\t%02x' % (k[1], v[0], v[1], v[3], v[4], v[5], v[6], v[7], v[8]))
        open(os.path.join(HERE, 'index.tsv'), 'w').write(
            'hash\tpak\tgen\tsize\tocc\tfilesize\trecver\tflags\tmethod\n' + '\n'.join(listing))
        print('wrote index.tsv with %d entries' % len(listing))
        return

    # full extraction, merged view
    byfile = {}
    for h, v in merged.items():
        byfile.setdefault(v[0], []).append((h, v))
    for p in paks:
        stem = os.path.splitext(p)[0]
        if stem not in byfile:
            continue
        path = os.path.join(r'D:\TLGL', p)
        f = open(path, 'rb')
        for h, (st2, gi, off, size, occ, ofsz, ver, fl, me, fcrc) in sorted(byfile[stem], key=lambda x: (x[1][1], x[1][2])):
            if size == 0:
                st['empty'] += 1
                continue
            f.seek(off)
            raw = f.read(size)
            if len(raw) != size or crc(raw) != fcrc:
                st['fails'].append((stem, gi, h, 'stored crc'))
                continue
            st['stored_crc_ok'] += 1
            body = raw
            if fl & 4:
                st['encrypted'] += 1
                body = decrypt(h[1], size, raw)
            man = None
            if fl & 1:
                st['manifest'] += 1
                pl = body[0]
                raw_path = body[1:1 + pl]
                man = dict(path=(raw_path.split(b'\x00')[0].rstrip(b' ')).decode('mbcs', 'replace'),
                           crc=struct.unpack_from('<I', body, 1 + pl + 12)[0])
                body = body[1 + pl + 16:]
            if me == 0:
                st['stored'] += 1
                out = body
            elif me == 0x33:
                st['snappy'] += 1
                try:
                    out = bytes(cramjam.snappy.decompress_raw(body))
                except Exception as e:
                    st['fails'].append((stem, gi, h, 'snappy %s' % e))
                    continue
            else:
                st['other_meth'][me] = st['other_meth'].get(me, 0) + 1
                continue
            if len(out) != ofsz:
                st['size_mismatch'] += 1
                st['fails'].append((stem, gi, h, 'size %d != %d' % (len(out), ofsz)))
                continue
            if man and crc(out) == man['crc']:
                st['man_crc_ok'] += 1
            elif man:
                st['man_crc_bad'] += 1
            rel = (man['path'] if man and man['path']
                   else '%016x%s' % (h[1], guess_kind(out[:16])))
            dest = os.path.normpath(os.path.join(args.outdir, stem, rel.replace('\\', '/')))
            if not dest.startswith(os.path.abspath(args.outdir)):
                dest = os.path.join(args.outdir, stem, 'unsafe_%016x.bin' % h[1])
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            if os.path.exists(dest):
                dest += '.dup'
            with open(dest, 'wb') as o:
                o.write(out)
            st['written'] += 1
            st['bytes_out'] += len(out)
            if args.max and st['written'] >= args.max:
                break
        f.close()
    json.dump({k: (v if k != 'fails' else len(v)) for k, v in st.items()}, sys.stdout, indent=1)
    print()
    for x in st['fails'][:15]:
        print('  fail:', x)


if __name__ == '__main__':
    main()
