"""Arbitration, decisive test on ResourcePath.cfg (JBCF v8, fully decoded):
 layout  [0,16) magic/ver  [16,64) header  [64,64+72764*36) records  then 145528*8B string
 descriptors (u32 len, u32 hash; offsets are cumulative)  then the packed string blob.
 Then: does cfg name geometry that resources.db lost, and do those blobs actually exist?"""
import collections
import glob
import os
import re
import sqlite3
import struct
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = r"D:\TLGL\.scratch"
raw = open(os.path.join(HERE, "out", "tree", "ResourcePath.cfg"), "rb").read()
hdr = struct.unpack_from("<16I", raw, 0)
N = hdr[9]
REC = 64
SD = REC + N * 36
BLOB_S, BLOB_E = 3783792, 10853869
NS = (BLOB_S - SD) // 8
blob = raw[BLOB_S:BLOB_E]
lens = [struct.unpack_from("<I", raw, SD + 8 * i)[0] for i in range(NS)]
print(f"records N={N}  strings={NS}  sum(lens)={sum(lens):,} vs blob len={len(blob):,} -> "
      f"{'EXACT' if sum(lens) == len(blob) else 'MISMATCH'}")
offs = [0] * NS
c = 0
for i, L in enumerate(lens):
    offs[i] = c
    c += L
strings = [blob[offs[i]: offs[i] + lens[i]] for i in range(NS)]
keys = [strings[2 * k] for k in range(N)]
paths = [strings[2 * k + 1] for k in range(N)]
print(f"decoded {len(paths):,} paths, first4={paths[:4]}")
bad = sum(1 for p in paths if b"/" not in p)
print(f"paths without '/': {bad}   key==basename(path) for: "
      f"{sum(1 for k, p in zip(keys, paths) if k == p.rsplit(b'/', 1)[-1]):,}/{N:,}")
low = [p.decode("latin1").lower() for p in paths]
uniq = sorted(set(low))
print(f"DISTINCT cfg paths: {len(uniq):,}  (records {N:,}, dup {N-len(uniq):,})")
ext = collections.Counter(p.rsplit(".", 1)[-1] if "." in p.rsplit("/", 1)[-1] else "(none)" for p in uniq)
print("cfg ext histogram:", ext.most_common(14))

con = sqlite3.connect("file:D:/TLGL/.scratch/resources.db?mode=ro", uri=True)
dbpath = {p.lower() for (p,) in con.execute("select path from resources where named=1 and path is not null")}
print(f"\ndb named paths: {len(dbpath):,}   cfg distinct: {len(uniq):,}   overlap: "
      f"{len(set(dbpath) & set(uniq)):,}   cfg-only: {len(set(uniq) - dbpath):,}   db-only: {len(dbpath - set(uniq)):,}")

# ---- .scene instance names, unified caliber
TREE = os.path.join(HERE, "out", "tree")
NAMEOK = re.compile(rb"^[A-Za-z0-9_\-.]{4,80}$")
db_mesh = {p.rsplit("/", 1)[-1].lower() for (p,) in con.execute("select path from resources where ext='.mesh' and named=1")}
cfg_base = collections.defaultdict(list)
for p in uniq:
    cfg_base[p.rsplit("/", 1)[-1]].append(p)
scene_names = collections.Counter()
scene_names_mesh = collections.Counter()
gap_names = set()
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
        scene_names[s] += 1
        if s.endswith(".mesh"):
            scene_names_mesh[s] += 1
            if s not in db_mesh:
                gap_names.add(s)
tot = sum(scene_names.values())
print(f"\n.scene named records = {tot:,} ; distinct names = {len(scene_names):,} ; "
      f"distinct .mesh names = {len(scene_names_mesh):,}")
ginst = sum(scene_names_mesh[s] for s in gap_names)
print(f"gap: {len(gap_names):,} distinct .mesh names referenced by scenes but NOT named in db, "
      f"carried by {ginst:,} instances = {100*ginst/tot:.2f}% of all named records")
in_cfg = {s for s in gap_names if s in cfg_base}
print(f"  of those, present in cfg by basename: {len(in_cfg):,} / {len(gap_names):,}")
print(f"  instances covered: {sum(scene_names_mesh[s] for s in in_cfg):,} = "
      f"{100*sum(scene_names_mesh[s] for s in in_cfg)/tot:.2f}% of named records")
full_paths = set()
for s in in_cfg:
    for p in cfg_base[s]:
        if p.endswith("/" + s):
            full_paths.add(p)
print(f"  cfg full paths ending in a gap name: {len(full_paths):,}  (dirs: "
      f"{collections.Counter(p.split('/')[0] for p in full_paths).most_common(4)})")

# ---- pure-python port of sub_14059F020 (mine2.batch_hash) and the existence test
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


probe = [(p, h) for h, p in con.execute("select hash,path from resources where named=1 and path is not null limit 300")]
ok = sum(1 for p, h in probe if ph(p.encode("latin1")) == h)
print(f"\nhash port self-test on 300 named db rows: {ok}/300 match")
allh = {h: (n, p) for h, n, p in con.execute("select hash,named,path from resources")}
hit_row = hit_unnamed = 0
recoverable = set()
ex = []
for p in sorted(full_paths):
    h = ph(p.encode("latin1"))
    r = allh.get(h)
    if r:
        hit_row += 1
        if not r[0]:
            hit_unnamed += 1
            recoverable.add(p.rsplit("/", 1)[-1])
            if len(ex) < 8:
                ex.append((h, p))
print(f"cfg gap paths whose HASH EXISTS as a db blob row: {hit_row:,}/{len(full_paths):,}")
print(f"  ... of which the row is currently UNNAMED -> genuinely recoverable names: {hit_unnamed:,}")
for h, p in ex:
    print("   ", h, p)
recov_inst = sum(scene_names_mesh[s] for s in gap_names if s in recoverable)
base = sum(v for s, v in scene_names_mesh.items() if s in db_mesh)
print(f"instances whose .mesh name is in cfg AND whose blob exists unnamed in db: {recov_inst:,} "
      f"= {100*recov_inst/tot:.2f}% -> join rate would go "
      f"{100*base/tot:.2f}% -> {100*(base+recov_inst)/tot:.2f}%")
