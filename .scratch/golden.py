"""Emit the Rust decode chain's golden vectors.

Independent reference: this uses python's `cramjam` snappy and the `pakunpack2`
keystream port — a different implementation from crates/core, so agreement is a real
cross-check, not a tautology. Only the five 2025-era paks are used; `data_1.pak` is
appended to at runtime by a running client and would make the vectors drift.
"""
import hashlib
import mmap
import os
import struct
import sys

import cramjam

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pakunpack2 as pu

REC = pu.REC
ROOT = r'D:\TLGL'
STABLE = ['data.pak', 'data1.pak', 'data2.pak', 'data3.pak', 'data4.pak']
OUT = os.path.join(HERE, '..', 'tlbb-explorer', 'crates', 'core', 'tests', 'golden', 'entries.tsv')


def entries(pak):
    f = open(os.path.join(ROOT, pak), 'rb')
    d = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
    off = 16
    while True:
        cap, used, nxt, crc = struct.unpack_from('<IIII', d, off)
        base = off + 16
        for i in range(used):
            yield REC.unpack_from(d, base + i * 36), d
        if nxt == 0:
            break
        off = nxt
    # generator intentionally leaks the map; this is a one-shot script


def decode(rec, d):
    h, o, sz, occ, ofsz, ver, fl, me, fcrc, ucrc = rec
    raw = bytes(d[o:o + sz])
    if sz == 0:
        return b''
    body = pu.decrypt(h, sz, raw) if fl & 4 else raw
    if fl & 1:
        body = body[1 + body[0] + 16:]
    return bytes(cramjam.snappy.decompress_raw(body)) if me == 0x33 else body


def pick():
    """One cheap index pass, then subsample each branch so all rare paths are covered."""
    rare = {'manifest': [], 'plain': []}
    common = {'stored': [], 'tiny': [], 'huge': [], 'snappy': []}
    for pak in STABLE:
        for rec, _d in entries(pak):
            h, o, sz, occ, ofsz, ver, fl, me, fcrc, ucrc = rec
            if not sz:
                continue
            key = (pak, rec)
            if fl & 1:
                rare['manifest'].append(key)
            if not (fl & 4):
                rare['plain'].append(key)
            if sz > 1_000_000:
                common['huge'].append(key)
                continue
            stride_ok = (h % 23) == 0
            if not stride_ok:
                continue
            if me == 0 and not (fl & 1):
                common['stored'].append(key)
            elif sz <= 128:
                common['tiny'].append(key)
            elif me == 0x33:
                common['snappy'].append(key)
    want = {'manifest': 40, 'plain': 40, 'stored': 40, 'tiny': 40, 'huge': 20, 'snappy': 60}
    out, seen = [], set()
    for name, pool in list(rare.items()) + list(common.items()):
        pool.sort(key=lambda k: k[0])
        n = want[name]
        step = max(1, len(pool) // n)
        chosen = pool[::step][:n] if pool else []
        for pak, rec in chosen:
            if (pak, rec[0]) in seen:
                continue
            seen.add((pak, rec[0]))
            out.append((name, pak, rec))
    return out


def main():
    rows = []
    cache = {}
    for name, pak, rec in pick():
        if pak not in cache:
            f = open(os.path.join(ROOT, pak), 'rb')
            cache[pak] = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        data = decode(rec, cache[pak])
        h, o, sz, occ, ofsz, ver, fl, me, fcrc, ucrc = rec
        if len(data) != ofsz:
            print('REFERENCE MISMATCH', pak, '%016x' % h, len(data), ofsz)
            continue
        rows.append('\t'.join(map(str, [
            name, pak, '%016x' % h, o, sz, ofsz, ver, '%02x' % fl, '%02x' % me,
            pu.crc(data), hashlib.sha256(data).hexdigest(),
            data[:64].hex(), data[-64:].hex(),
        ])))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, 'w', newline='\n').write(
        'kind\tpak\thash\toffset\tstored\toriginal\tver\tflags\tmethod\tcrc32\tsha256\thead\ttail\n'
        + '\n'.join(rows) + '\n')
    print('wrote %d vectors to %s' % (len(rows), OUT))
    from collections import Counter
    print(Counter(r.split('\t')[0] for r in rows))


if __name__ == '__main__':
    main()
