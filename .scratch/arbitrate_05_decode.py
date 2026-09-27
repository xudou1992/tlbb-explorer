"""Definitive decode of ResourcePath.cfg (JBCF v8):
   [0..16) magic/version, [16..64) header u32s,
   [64 .. 64+72764*36) record array, 36B/record,
   then 145,528 x 8B string descriptors, then the packed string blob.
"""
import collections
import os
import sqlite3
import struct
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = r"D:\TLGL\.scratch"
raw = open(os.path.join(HERE, "out", "tree", "ResourcePath.cfg"), "rb").read()
hdr = struct.unpack_from("<16I", raw, 0)
N = hdr[9]
REC_OFF = 64
STRTAB_OFF = REC_OFF + N * 36
NS = (3783792 - STRTAB_OFF) // 8
print(f"N(records)={N}  record array @{REC_OFF}..{STRTAB_OFF}  string descriptors={NS} @{STRTAB_OFF} "
      f"(leftover {(3783792-STRTAB_OFF) % 8})")
print("first descriptor:", struct.unpack_from("<8I", raw, STRTAB_OFF))

BLOB = 3783792
strings = []
for i in range(NS):
    a, b = struct.unpack_from("<II", raw, STRTAB_OFF + 8 * i)
    strings.append(raw[BLOB + a: BLOB + a + b])
print("sample strings[0:6]:", strings[:6])
print("sample strings[2:8]:", strings[2:8])

# record fields -> which pair indexes are the strings
r0 = struct.unpack_from("<9I", raw, REC_OFF)
r1 = struct.unpack_from("<9I", raw, REC_OFF + 36)
print("rec0:", r0, "rec1:", r1)
pairs = []
for k in range(N):
    f = struct.unpack_from("<9I", raw, REC_OFF + 36 * k)
    a, b = f[1], f[3]
    if a < NS and b < NS:
        pairs.append((strings[a], strings[b]))
print(f"resolved (idx_a, idx_b) pairs: {len(pairs)} / {N}")
print("first 5 resolved:", pairs[:5])
# decide orientation: which element carries the '/' -> that is the path
slash_a = sum(1 for x, y in pairs if b"/" in x)
slash_b = sum(1 for x, y in pairs if b"/" in y)
print(f"'/' present in field a: {slash_a}, in field b: {slash_b}")
keys = [x for x, y in pairs if b"/" not in x]
paths = [y for x, y in pairs if b"/" in x] or [x for x, y in pairs if b"/" in y]
print(f"keys={len(keys)} paths={len(paths)}")
low = [p.decode("latin1").lower() for p in paths if p]
print(f"distinct paths: {len(set(low)):,}  empty paths: {sum(1 for p in paths if not p):,}")
ext = collections.Counter(p.rsplit(".", 1)[-1] if "." in p.rsplit("/", 1)[-1] else "(none)" for p in low)
print("path extension histogram (top 18):", ext.most_common(18))
top = collections.Counter(p.split("/")[0] for p in low)
print("top-level dir histogram:", top.most_common(12))

con = sqlite3.connect("file:D:/TLGL/.scratch/resources.db?mode=ro", uri=True)
dbpath = {p.lower() for (p,) in con.execute("select path from resources where named=1 and path is not null")}
rows = {h: (n, p) for h, n, p in con.execute("select hash,named,path from resources")}
hit = sum(1 for p in low if p in dbpath)
print(f"\ndb named paths={len(dbpath):,}  cfg paths verbatim in db: {hit:,} = {100*hit/len(low):.2f}%")
miss = sorted(p for p in set(low) if p not in dbpath)
print(f"cfg paths NOT in db (distinct): {len(miss):,}")
me = collections.Counter(p.rsplit(".", 1)[-1] if "." in p.rsplit("/", 1)[-1] else "(none)" for p in miss)
print("  missing-by-ext top:", me.most_common(12))
open(os.path.join(HERE, "arbitrate_05_paths.txt"), "w", encoding="utf-8").write("\n".join(miss))

mesh = set(p for p in low if p.endswith(".mesh"))
mesh_db = set(p for p in dbpath if p.endswith(".mesh"))
print(f"\nmesh: cfg={len(mesh):,} db={len(mesh_db):,} cfg-only={len(mesh-mesh_db):,} db-only={len(mesh_db-mesh):,}")
