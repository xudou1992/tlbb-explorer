"""Are the 467 discarded 'other tag' .scene files also instance tables (tag = record bytes - 8)?"""
import collections
import glob
import os
import re
import struct
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = r"D:\TLGL\.scratch"
TREE = os.path.join(HERE, "out", "tree")
NAMEOK = re.compile(rb"^[A-Za-z0-9_\-.]{4,80}$")
bytag = collections.Counter()
recs = collections.Counter()
samples = collections.defaultdict(list)
for f in glob.glob(os.path.join(TREE, "mobile_maps", "*", "*.scene")):
    b = open(f, "rb").read()
    if len(b) < 12:
        continue
    n, tag, z = struct.unpack_from("<III", b, 0)
    if tag in (753, 749):
        continue
    st = tag + 8
    ok = 0
    named = 0
    if 0 < st < 4096 and n:
        for i in range(n):
            o = 12 + st * i
            if o + 64 > len(b):
                break
            m = struct.unpack_from("<16f", b, o)
            col = (m[3], m[7], m[11], m[15])
            if abs(col[0]) < 1e-5 and abs(col[1]) < 1e-5 and abs(col[2]) < 1e-5 and abs(col[3] - 1) < 1e-4:
                ok += 1
            nb = b[o + 64:o + st].split(b"\x00", 1)[0]
            if nb and NAMEOK.match(nb):
                named += 1
                if len(samples[tag]) < 3:
                    samples[tag].append((os.path.basename(f), nb.decode("latin1")[:40]))
    sizefit = abs(len(b) - (12 + st * n)) <= 8 if 0 < st < 4096 else False
    bytag[(tag, struct.pack("<I", tag).decode("latin1", "replace"), n, len(b), sizefit, ok, named)] += 1
print("tag(ascii) | N | size | size~law | matrix-ok | named | files")
for (tag, asc, n, sz, fit, ok, named), c in bytag.most_common(12):
    print(f"  tag={tag:<12} {asc!r} N={n:<6} size={sz:<8} law={fit!s:<6} matok={ok:<6} named={named:<6} files={c}")
    recs["named"] += named * 1 if c <= 400 else 0
    recs["rec"] += ok * 1 if c <= 400 else 0
print("\ncolumn-sum for the small tag families (<=400 files):", dict(recs))
for t, s in list(samples.items())[:6]:
    print(f"  tag {t} sample names: {s[:3]}")
