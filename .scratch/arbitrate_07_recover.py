"""Does cfg actually NAME blobs that resources.db lost?  Hash every cfg path with the engine's
own path hash and look it up in resources; also test path spellings that could differ."""
import collections
import os
import sqlite3
import struct
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = r"D:\TLGL\.scratch"
raw = open(os.path.join(HERE, "out", "tree", "ResourcePath.cfg"), "rb").read()
N = struct.unpack_from("<16I", raw, 0)[9]
SD = 64 + N * 36
BLOB_S, BLOB_E = 3783792, 10853869
NS = (BLOB_S - SD) // 8
blob = raw[BLOB_S:BLOB_E]
lens = [struct.unpack_from("<I", raw, SD + 8 * i)[0] for i in range(NS)]
offs, c = [0] * NS, 0
for i, L in enumerate(lens):
    offs[i] = c
    c += L
paths = [blob[offs[2 * k + 1]: offs[2 * k + 1] + lens[2 * k + 1]] for k in range(N)]
M = 0xFFFFFFFF


def ph(p):
    h1, h2 = 0x4E67C6A7, 0
    for ch in p:
        if 65 <= ch <= 90:
            ch = (ch + 32) & M
        if ch == 92:
            ch = 47
        h1 = (h1 ^ ((ch + (h1 << 5) + (h1 >> 2)) & M)) & M
        h2 = (ch + h2 * 65599) & M
    return "%016x" % (h1 | (h2 << 32))


con = sqlite3.connect("file:D:/TLGL/.scratch/resources.db?mode=ro", uri=True)
info = {h: (n, p, t, s) for h, n, p, t, s in con.execute("select hash,named,path,type,subtype from resources")}
print(f"db rows={len(info):,}  named={sum(1 for v in info.values() if v[0]):,}")
h_cfg = {ph(p): p for p in paths}
hit_named = sum(1 for h in h_cfg if h in info and info[h][0])
hit_un = [h for h in h_cfg if h in info and not info[h][0]]
print(f"\nall {len(h_cfg):,} distinct cfg paths hashed:")
print(f"  hit a NAMED db row          : {hit_named:,}")
print(f"  hit an UNNAMED db row       : {len(hit_un):,}   <-- this is the 'fixable' pool")
print(f"  hit nothing (blob absent)   : {len(h_cfg) - hit_named - len(hit_un):,}")
c2 = collections.Counter(info[h][2] + "/" + str(info[h][3]) for h in hit_un)
print("  unnamed-hit row types:", c2.most_common(8))
for h in hit_un[:5]:
    print("   ", h, h_cfg[h].decode("latin1"))

# how many unnamed rows are there at all, and what types
un = collections.Counter(f"{t}/{s}" for h, (n, p, t, s) in info.items() if not n)
print("\nunnamed db rows by type/subtype:", un.most_common(10))

# spelling variants for the 1163 scene-gap names
gapfile = os.path.join(HERE, "arbitrate_05_paths.txt")
cands = [
    "mobile_maps_source/{n}", "data/mobile_maps_source/{n}", "Mobile_Maps_Source/{n}",
    "mobile_maps_source\\{n}", "/mobile_maps_source/{n}", "{n}", "data/{n}", "mobile_maps/{n}",
]
import re
import glob
import json
TREE = os.path.join(HERE, "out", "tree")
NAMEOK = re.compile(rb"^[A-Za-z0-9_\-.]{4,80}$")
dbmesh = {p.rsplit("/", 1)[-1].lower() for (p,) in con.execute("select path from resources where ext='.mesh' and named=1")}
cfgbase = {p.rsplit(b"/", 1)[-1].decode("latin1").lower() for p in paths}
gn = set()
tot = 0
cnt = collections.Counter()
for f in glob.glob(os.path.join(TREE, "mobile_maps", "*", "*.scene")):
    b = open(f, "rb").read()
    if len(b) < 12:
        continue
    n, tag, _z = struct.unpack_from("<III", b, 0)
    if tag not in (753, 749):
        continue
    st = tag + 8
    for i in range(n):
        o = 12 + st * i
        if o + 64 > len(b):
            break
        nb = b[o + 64:o + st].split(b"\x00", 1)[0]
        if not nb or not NAMEOK.match(nb):
            continue
        s = nb.decode("latin1").lower()
        tot += 1
        if s.endswith(".mesh") and s not in dbmesh:
            cnt[s] += 1
print(f"\ngap names={len(cnt):,} instances={sum(cnt.values()):,}/{tot:,}")
tries = collections.Counter()
for s in cnt:
    for tpl in cands:
        p = tpl.format(n=s)
        h = ph(p.encode("latin1"))
        if h in info and not info[h][0]:
            tries["hit via " + tpl.split("{")[0]] += 1
            break
    else:
        h2 = ph(s.encode("latin1"))
        tries["no hit (bare-name hash %s)" % ("in-db" if h2 in info else "absent")] += 1
print("hash-recovery attempts for gap names:", tries.most_common())

# do the currently-named .mesh blobs under mobile_maps_source match cfg at all?
src = {f.lower() for f in os.listdir(os.path.join(TREE, "mobile_maps_source"))}
inn = sum(1 for s in cnt if s in src)
print(f"\ngap names physically present in out/tree/mobile_maps_source/: {inn} / {len(cnt)}")
print(f"cfg names physically present there: {sum(1 for s in cfgbase if s in src)} / {len(cfgbase)}")
