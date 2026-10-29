# -*- coding: utf-8 -*-
"""hamigua 取证 · hex 现场：把 [at, EOF) 按 u32/f32/名字 三视图逐行解剖。
用法：python hamigua_hex.py <file> <start_hex>
"""
import re
import struct
import sys

NAME_OK = re.compile(rb"[0-9A-Za-z_\-.]{3,40}")


def name_at(b, off):
    if off < 1 or off + 32 > len(b):
        return None
    if re.match(rb"[0-9A-Za-z_\-.]", b[off - 1:off]):
        return None
    m = NAME_OK.match(b, off)
    if not m:
        return None
    s = m.group()
    if len(s) > 31 or b[off + len(s)] != 0:
        return None
    if any(x != 0 for x in b[off + len(s):off + 32]):
        return None
    return s.decode()


def hexline(b, at, n=16):
    chunk = b[at:at + n]
    hx = " ".join("%02x" % c for c in chunk)
    asc = "".join(chr(c) if 32 <= c < 127 else "." for c in chunk)
    return "%05x  %-47s  |%s|" % (at, hx, asc)


def main():
    path, start = sys.argv[1], int(sys.argv[2], 16)
    b = open(path, "rb").read()
    print("file=%s size=%d(0x%x) from=0x%x" % (path.split("\\")[-1], len(b), len(b), start))
    at = start
    while at < len(b):
        u = struct.unpack_from("<I", b, at)[0] if at + 4 <= len(b) else 0
        f = struct.unpack_from("<f", b, at)[0] if at + 4 <= len(b) else 0.0
        notes = []
        if at % 4 == 0:
            fi = int(f) if abs(f) < 1e7 else None
            if u < 100000 and abs(u - f) < 1e-6:
                notes.append("u32=%d" % u)
            elif fi is not None and 1e-4 < abs(f) < 1e5:
                notes.append("f32=%.5g" % f)
            elif u in (0xFFFFFFFF,):
                notes.append("u32=-1")
            elif u < 100000:
                notes.append("u32=%d" % u)
        nm = name_at(b, at)
        if nm:
            nxt = at + 32
            rec = ""
            if nxt + 64 <= len(b):
                m = struct.unpack_from("<16f", b, nxt)
                rec = " mat15=%.4g" % m[15]
            notes.append("NAME(%d):'%s'%s" % (len(nm), nm, rec))
        print("%s  %s" % (hexline(b, at), "  ".join(notes)))
        at += 16


main()
