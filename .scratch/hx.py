"""Full hex+ASCII dump of one resource payload, for pinning down container grammar."""
import os
import sqlite3
import struct
import sys

HERE = r'D:\TLGL\.scratch'


def find(h):
    for pak in os.listdir(os.path.join(HERE, 'out', 'all')):
        d = os.path.join(HERE, 'out', 'all', pak)
        if not os.path.isdir(d):
            continue
        for fn in os.listdir(d):
            if fn.startswith(h):
                return os.path.join(d, fn)


def dump(raw, base=0, n=None):
    out = []
    for i in range(0, len(raw), 16):
        chunk = raw[i:i + 16]
        u32 = ' '.join('%10d' % struct.unpack_from('<I', c.ljust(4, b'\0'), 0)
                       if len(c) >= 4 else '' for c in
                       (raw[i + j:i + j + 4] for j in range(0, min(len(chunk), 16), 4)))
        out.append('%08x  %-47s  |%-16s|  %s' % (
            base + i, chunk.hex(' '),
            ''.join(chr(c) if 32 <= c < 127 else '.' for c in chunk), u32))
    return '\n'.join(out)


def main():
    arg = sys.argv[1]
    if len(arg) == 16:
        h = arg
        f = find(h)
    else:
        f, h = arg, os.path.basename(arg)[:16]
    raw = open(f, 'rb').read()
    print('file=%s hash=%s size=%d' % (f, h, len(raw)))
    lo, hi = (int(sys.argv[2]), int(sys.argv[3])) if len(sys.argv) > 4 else (0, len(raw))
    print(dump(raw[lo:hi], lo))


if __name__ == '__main__':
    main()
