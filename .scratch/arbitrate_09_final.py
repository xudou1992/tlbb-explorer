"""Final unified-caliber numbers + corroboration of the 'gap is not fixable' verdict."""
import collections
import glob
import os
import re
import sqlite3
import struct
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = r"D:\TLGL\.scratch"
TREE = os.path.join(HERE, "out", "tree")
M = 0xFFFFFFFF


def ph(p):
    h1, h2 = 0x4E67C6A7, 0
    for c in p:
        if 65 <= c <= 90:
            c = (c + 32) & M
        if c == 92:
            c = 47
        h1 = (h1 ^ ((c + (h1 << 5) + (h1 >> 2)) & M)) & M
        h2 = (c + h2 * 65599) & M
    return "%016x" % (h1 | (h2 << 32))


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
cfg_paths = [blob[offs[2 * k + 1]: offs[2 * k + 1] + lens[2 * k + 1]] for k in range(N)]
cfg_low = {p.decode("latin1").lower() for p in cfg_paths}
cfg_base = collections.defaultdict(list)
for p in cfg_low:
    cfg_base[p.rsplit("/", 1)[-1]].append(p)

con = sqlite3.connect("file:D:/TLGL/.scratch/resources.db?mode=ro", uri=True)
dbpath = {p.lower() for (p,) in con.execute("select path from resources where named=1 and path is not null")}
allh = {h: n for h, n in con.execute("select hash,named from resources")}
db_mesh = {p.rsplit("/", 1)[-1].lower() for (p,) in con.execute("select path from resources where ext='.mesh' and named=1")}
db_mtl = {p.rsplit("/", 1)[-1].lower() for (p,) in con.execute("select path from resources where ext='.mtl' and named=1")}
src_ok = set()
for d in os.listdir(os.path.join(TREE, "mobile_maps_source")):
    if d.lower().endswith(".mesh"):
        fp = os.path.join(TREE, "mobile_maps_source", d)
        b = open(fp, "rb").read(0x94)
        if len(b) >= 0x94 and struct.unpack_from("<I", b, 0x90)[0]:
            src_ok.add(d.lower())
NAMEOK = re.compile(rb"^[A-Za-z0-9_\-.]{4,80}$")

# ---------- full archive set: tree files + the 1,126 unnamed grid753 blobs ----------
blobs = {}
for p in glob.glob(os.path.join(HERE, "out", "all", "*", "*")):
    blobs[os.path.basename(p).split(".")[0]] = p
un = [(h,) for (h,) in con.execute("select hash from resources where named=0 and type='scene'")]
tables = [(f, "tree") for f in glob.glob(os.path.join(TREE, "mobile_maps", "*", "*.scene"))]
tables += [(blobs[h[0]], "unnamed-blob") for h in un if h[0] in blobs]
tot = collections.Counter()
gap = collections.Counter()
gap_names = {}
for f, kind in tables:
    b = open(f, "rb").read()
    if len(b) < 12:
        tot[f"{kind}: files<12B"] += 1
        continue
    n, tag, z = struct.unpack_from("<III", b, 0)
    if tag not in (753, 749):
        tot[f"{kind}: files other tag"] += 1
        continue
    tot[f"{kind}: instance tables"] += 1
    st = tag + 8
    for i in range(n):
        o = 12 + st * i
        if o + 64 > len(b):
            break
        tot["declared-and-walked"] += 1
        nb = b[o + 64:o + st].split(b"\x00", 1)[0]
        if not nb or not NAMEOK.match(nb):
            tot["name invalid/empty"] += 1
            continue
        s = nb.decode("latin1").lower()
        tot["NAME-VOTAL records"] += 1
        if s.endswith(".mesh") and s in src_ok and s in db_mesh:
            tot["JOINED real geometry"] += 1
        elif s.endswith(".mesh"):
            gap["names"] = 0
            tot["gap .mesh names"] += 1
            gap_names.setdefault(s, 0)
            gap_names[s] += 1
        else:
            tot["gap non-.mesh name"] += 1
print("=== FULL ARCHIVE SET (tree .scene + the 1,126 unnamed grid753 blobs) ===")
for k, v in tot.most_common():
    print(f"  {k:34s} {v:,}")
nv = tot["NAME-VOTAL records"]
jn = tot["JOINED real geometry"]
print(f"  JOIN RATE (unified)          {100*jn/nv:.2f}%   (tree-only would be different)")
gn = set(gap_names)
in_cfg = {s for s in gn if s in cfg_base}
print(f"\ngap distinct .mesh names={len(gn):,} instances={sum(gap_names.values()):,} "
      f"= {100*sum(gap_names.values())/nv:.2f}% of name-valid records")
print(f"  in cfg as a path: {len(in_cfg):,} names / {sum(gap_names[s] for s in in_cfg):,} instances")
print(f"  NOT in cfg at all: {len(gn)-len(in_cfg):,} names / {sum(v for s,v in gap_names.items() if s not in in_cfg):,} instances")
hit = sum(1 for s in in_cfg if any(ph(p.encode('latin1')) in allh and not allh[ph(p.encode('latin1'))]
                                   for p in cfg_base[s]))
hit_any = sum(1 for s in in_cfg if any(ph(p.encode('latin1')) in allh for p in cfg_base[s]))
print(f"  cfg path hashes to an UNNAMED db blob (=> truly fixable): {hit:,} of {len(in_cfg):,}")
print(f"  cfg path hashes to ANY db row                          : {hit_any:,} of {len(in_cfg):,}")
sib_mtl = sum(1 for s in in_cfg if s[:-5] + ".mtl" in db_mtl)
sib_cfg_mtl = sum(1 for s in in_cfg if (s[:-5] + ".mtl") in cfg_base)
print(f"  sibling .mtl of gap names: named in db {sib_mtl:,} / listed in cfg {sib_cfg_mtl:,}")
print("  examples of gap names:", sorted(gap_names)[:5])

# ---------- global recoverable pool from cfg ----------
rec = collections.Counter()
for p in cfg_low:
    h = ph(p.encode("latin1"))
    if h in allh and not allh[h]:
        rec[p.rsplit(".", 1)[-1]] += 1
print(f"\ncfg paths that name a currently-UNNAMED db blob: {sum(rec.values()):,} "
      f"(by ext {rec.most_common(8)})")
print(f"cfg paths with no db blob at all: {len(cfg_low)-len(dbpath & cfg_low)-sum(rec.values()):,}")
print(f"db named paths not listed in cfg: {len(dbpath - cfg_low):,}")
gr = list(con.execute("select count(*) from resources where named=0 and type='geom' and subtype='raw'"))[0][0]
print(f"db geom/raw unnamed rows: {gr:,}   (none of them reachable from cfg: see ext list above)")
