"""Identify the path -> u64 hash used by JPAK Index.uHash, from the 154 known (path, hash) pairs."""
import json
import sys

rows = json.load(open(r'D:\TLGL\.scratch\out\loose_index.json', encoding='utf-8'))
pairs = [(r['path'], int(r['hash'], 16)) for r in rows]
print('pairs:', len(pairs), pairs[0], pairs[-1])

M64 = (1 << 64) - 1


def fnv1a64(b):
    h = 0xCBF29CE484222325
    for c in b:
        h = ((h ^ c) * 0x100000001B3) & M64
    return h


def fnv1_64(b):
    h = 0xCBF29CE484222325
    for c in b:
        h = (h * 0x100000001B3) & M64
        h ^= c
    return h


def fnv1a32(b):
    h = 0x811C9DC5
    for c in b:
        h = ((h ^ c) * 0x01000193) & 0xFFFFFFFF
    return h


def djb2(b):
    h = 5381
    for c in b:
        h = ((h * 33) + c) & M64
    return h


def djb2_xor(b):
    h = 5381
    for c in b:
        h = ((h * 33) ^ c) & M64
    return h


def sdbm(b):
    h = 0
    for c in b:
        h = (c + (h << 6) + (h << 16) - h) & M64
    return h


def k16(b):  # common 2-way 16-bit hash used by Chinese engines (ELFHash variants)
    h = 0
    for c in b:
        h = (h << 4) + c
        g = h & 0xF0000000
        if g:
            h ^= g >> 24
        h &= ~g & M64
    return h


def crc64_ecma(b):
    poly = 0xC96C5795D7870F42
    crc = 0
    for c in b:
        crc ^= c << 56
        for _ in range(8):
            crc = ((crc << 1) ^ poly) & M64 if crc >> 63 else (crc << 1) & M64
    return crc


def crc64_iso(b):
    poly = 0x42F0E1EBA9EA3693
    crc = 0xFFFFFFFFFFFFFFFF
    for c in b:
        crc ^= c << 56
        for _ in range(8):
            crc = ((crc << 1) ^ poly) & M64 if crc >> 63 else (crc << 1) & M64
    return ~crc & M64


def variants(p):
    yield 'raw', p
    yield 'lower', p.lower()
    yield 'upper', p.upper()
    yield 'bs', p.replace('/', '\\')
    yield 'bs_lower', p.replace('/', '\\').lower()
    yield 'slash_lower', p.replace('\\', '/').lower()


fns = dict(fnv1a64=fnv1a64, fnv1_64=fnv1_64, fnv1a32=fnv1a32, djb2=djb2, djb2_xor=djb2_xor,
           sdbm=sdbm, k16=k16, crc64_ecma=crc64_ecma, crc64_iso=crc64_iso)

for name, fn in fns.items():
    for vname, mk in variants.__name__ and [('raw', lambda p: p), ('lower', lambda p: p.lower()),
                                            ('upper', lambda p: p.upper()),
                                            ('bs', lambda p: p.replace('/', '\\')),
                                            ('bs_lower', lambda p: p.replace('/', '\\').lower()),
                                            ('fwd_lower', lambda p: p.replace('\\', '/').lower())]:
        s = bytes(pairs[0][0], 'utf-8')
        got = fn(mk(pairs[0][0]).encode('utf-8'))
        match = got == pairs[0][1]
        print('%-11s %-10s first: %016x want %016x %s' % (name, vname, got, pairs[0][1], 'MATCH' if match else ''))
