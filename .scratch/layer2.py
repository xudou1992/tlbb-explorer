"""Probe JBCF / JRPC / .pcfg bodies for a second compression layer (LZMA-alone, raw deflate, snappy)."""
import lzma
import os
import sys
import zlib

import cramjam

D = r'D:\TLGL\.scratch\out\named'


def probe(name, b):
    print('=== %s (%d bytes) head=%s' % (name, len(b), b[:16].hex()))
    for tag, fn in (('lzma-alone', try_lzma), ('raw-deflate', try_deflate),
                    ('snappy', try_snappy), ('zlib', try_zlib)):
        r = fn(b)
        if r:
            print('   %-12s @%d -> %d bytes, head %r' % (tag, r[0], len(r[1]), r[1][:60]))
            return r[1]
    print('   no second layer detected')
    return None


def try_lzma(b):
    for off in range(0, 4096):
        if b[off] not in (0x5d, 0x5e, 0x40, 0x80, 0x20, 0xe0):
            continue
        try:
            d = lzma.LZMADecompressor(format=lzma.FORMAT_ALONE)
            out = d.decompress(b[off:off + 4 * 1024 * 1024])
            if len(out) > 4096:
                return (off, out)
        except Exception:
            continue
    return None


def try_zlib(b):
    for off in range(0, 4096):
        if b[off] != 0x78:
            continue
        try:
            out = zlib.decompressobj().decompress(b[off:])
            if len(out) > 4096:
                return (off, out)
        except Exception:
            continue
    return None


def try_deflate(b):
    for off in range(0, 8192):
        try:
            out = zlib.decompressobj(-15).decompress(b[off:])
            if len(out) > 4096:
                return (off, out)
        except Exception:
            continue
    return None


def try_snappy(b):
    for off in range(0, 256):
        try:
            out = bytes(cramjam.snappy.decompress_raw(b[off:off + 512 * 1024]))
            if len(out) > 4096:
                return (off, out)
        except Exception:
            continue
    return None


for fn in sorted(os.listdir(D)):
    if any(k in fn for k in ('resourcepath', 'collect.pcfg', 'modulelist.xml', 'script_list')):
        b = open(os.path.join(D, fn), 'rb').read()
        out = probe(fn, b)
        if out:
            open(os.path.join(D, fn + '.layer2'), 'wb').write(out)
            sys.path.insert(0, r'D:\TLGL\.scratch')
            import re
            from jhash import path_hash
            ts = set(re.findall(rb'[\x21-\x7e\x81-\xfe]{4,160}\.(?:png|tga|dds|lua|xml|tab|wav|ogg|mesh|jpg|ini|cfg|json)', out))
            print('   path-ish tokens in layer2: %d' % len(ts))
