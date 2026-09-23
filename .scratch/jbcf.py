"""BinaryConfigFile (JBCF) reader: container walk + string table.

Grammar recovered from the client itself (sub_1409C6A10 / BinaryConfigFile::vftable):

    [0]  'JBCF'   [4] 0   [8] 8   [12] bodyLen (file size - 16)
    [16] root chunk, u32 id == 86, u32 size at +4
    string table chunk at round8(root.size) + 24:
        [u32 id == 85][u32 size][u32 flag][u32 count][count*(u32 len, u32 hash)][chars]

The string table is what matters for archaeology: .mtl bodies name their parent
material, their shader class and their textures in the clear, so the dependency
graph can come from the files instead of from filename guessing.

usage: python jbcf.py            # census over every JBCF resource
       python jbcf.py --hashes   # also test what the per-string u32 is
"""
import collections
import os
import sqlite3
import struct
import sys

HERE = r'D:\TLGL\.scratch'
ROOT_ID, STR_ID, HDR = 86, 85, 16


def r8(n):
    return n if not n & 7 else n + 8 - (n & 7)


def sdecode(b):
    """Bytes -> text. The client writes names as UTF-8 *or* GBK depending on era, so
    Latin-1 alone turns recent Chinese names into mojibake that then poisons search,
    tags and exports.  Only fall back to Latin-1 when neither decoding works.
    """
    for enc in ('utf-8', 'gbk'):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            pass
    return b.decode('latin1', 'replace')


def _strtab(raw):
    """Locate the id-85 string chunk. Formula first, then a bounded backward scan."""
    n = len(raw)
    cands = [r8(struct.unpack_from('<I', raw, 20)[0]) + 24]
    # The string table is the last chunk; its size must land within 8 bytes of EOF.
    lo = max(16, n - 200000)
    cands.extend(range(n - 16, lo, -4))
    for off in cands:
        if off < 16 or off + 16 > n:
            continue
        try:
            return off, _read_strtab(raw, off)
        except (ValueError, struct.error):
            continue
    raise ValueError('no strtab')


def _read_strtab(raw, off):
    sid, ssize, flag, cnt = struct.unpack_from('<4I', raw, off)
    if sid != STR_ID:
        raise ValueError('strtab id %d' % sid)
    if cnt > 8192 or off + 16 + 8 * cnt > len(raw):
        raise ValueError('strtab count %d' % cnt)
    lens = struct.unpack_from('<%dI' % (2 * cnt), raw, off + 16) if cnt else ()
    pairs = [(lens[i], lens[i + 1]) for i in range(0, 2 * cnt, 2)]
    total = sum(l for l, _ in pairs)
    area = ssize - 8 - 8 * cnt
    if area < total or off + 8 + ssize > len(raw) + 8:
        raise ValueError('strtab size %d area %d total %d' % (ssize, area, total))
    if len(raw) - (off + 16 + 8 * cnt + area) > 7:
        raise ValueError('strtab tail')
    out, p = [], off + 16 + 8 * cnt
    for ln, hv in pairs:
        s = raw[p:p + ln]
        if any(c < 9 or 14 <= c < 32 for c in s):
            raise ValueError('strtab chars')
        out.append((sdecode(s), hv))
        p += ln
    return flag, out


def parse(raw):
    """(header, flag, [(string, str_hash)]) or raises ValueError."""
    if len(raw) < 24 or raw[:4] != b'JBCF':
        raise ValueError('not jbcf')
    a = struct.unpack_from('<6I', raw, 0)
    if a[3] + HDR != len(raw):
        raise ValueError('bodyLen')
    if a[4] != ROOT_ID:
        raise ValueError('root id %d' % a[4])
    off, (flag, out) = _strtab(raw)
    return a, off, flag, out


def payload_index():
    idx = {}
    for pak in os.listdir(os.path.join(HERE, 'out', 'all')):
        d = os.path.join(HERE, 'out', 'all', pak)
        if os.path.isdir(d):
            for fn in os.listdir(d):
                idx[fn[:16]] = os.path.join(d, fn)
    return idx


def main():
    test_hash = '--hashes' in sys.argv
    con = sqlite3.connect('file:resources.db?mode=ro', uri=True)
    idx = payload_index()
    rows = con.execute("select hash, ext, path from resources where type='JBCF'").fetchall()
    err = collections.Counter()
    kinds = collections.Counter()
    withstr = 0
    predict_hits = flagN = 0
    tga = set()
    mtls = set()
    shaders = collections.Counter()
    allstr = collections.Counter()
    cands = []
    for h, ext, path in rows:
        f = idx.get(h)
        if not f:
            err['no payload'] += 1
            continue
        try:
            hdr, soff, flag, strs = parse(open(f, 'rb').read())
            predict = r8(hdr[5]) + 24
            predict_hits += 1 if soff == predict else 0
        except ValueError as e:
            err[' '.join(str(e).split()[:2])] += 1
            continue
        withstr += 1
        flagN += 1 if flag else 0
        kinds[len(strs)] += 1
        for s, hv in strs:
            allstr[s] += 1
            low = s.lower()
            if low.endswith('.tga') or low.endswith('.dds') or low.endswith('.png'):
                tga.add(s)
            elif low.endswith('.mtl'):
                mtls.add(s)
            elif 'shader' in low:
                shaders[s] += 1
            if test_hash and len(cands) < 4000:
                cands.append((s, hv))
    log = open(os.path.join(HERE, 'jbcf_census.txt'), 'w', encoding='utf-8')

    def p(*a):
        print(*a, file=log)

    p('JBCF rows=%d parsed=%d (round8 formula hit %d)  errors=%s' %
      (len(rows), withstr, predict_hits, dict(err)))
    p('flag!=0 files: %d' % flagN)
    p('strings per file: %s' % sorted(kinds.items())[:20])
    p('distinct texture names: %d   distinct parent mtl: %d' % (len(tga), len(mtls)))
    p('shaders: %s' % shaders.most_common(12))
    p('top strings: %s' % allstr.most_common(15))
    extok = collections.Counter()
    for h, ext, path in rows:
        extok[ext] += 1
    p('by ext: %s' % extok.most_common())
    log.close()
    print(open(os.path.join(HERE, 'jbcf_census.txt'), encoding='utf-8').read())
    if test_hash:
        import jhash
        import zlib
        fns = {'path_hash_low': lambda s: jhash.path_hash(s) & 0xffffffff,
               'path_hash_hi': lambda s: jhash.path_hash(s) >> 32,
               'path_hash_low_lc': lambda s: jhash.path_hash(s.lower()) & 0xffffffff,
               'crc32': lambda s: zlib.crc32(s.encode('latin1')) & 0xffffffff,
               'crc32_lc': lambda s: zlib.crc32(s.lower().encode('latin1')) & 0xffffffff,
               'fnv': lambda s: (lambda a: a)(
                   __import__('functools').reduce(
                       lambda x, c: ((x * 16777619) ^ c) & 0xffffffff, s.encode('latin1'), 2166136261)),
               }
        hits = collections.Counter()
        for s, hv in cands:
            for k, fn in fns.items():
                try:
                    if fn(s) == hv:
                        hits[k] += 1
                except Exception:
                    pass
        print('hash-field hits out of %d: %s' % (len(cands), hits.most_common()))


if __name__ == '__main__':
    main()
