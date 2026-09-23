"""Verify two load-bearing claims before building on them.

C1 (subagent claim): ResourcePath.cfg lists ~20,315 .tga paths, and 99.1% of the
    .mesh names referenced by .scene files are named in cfg but missing from the db.
    Frozen project memory says the opposite: cfg holds exactly 2,271 image paths and
    naming is saturated at 57,274 hashes. Measure it directly.

C2 (subagent claim): .scene instance table = 12B header (u32 N | u32 753 | u32 0)
    + N * 761B records, record = f32[16] row-major affine + char name[697], Y-up,
    floor(x/32) == filename's second index. Decode one file byte by byte.
"""
import re
import sqlite3
import struct
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, r"D:\TLGL\.scratch")
import jhash  # path_hash reference port

SCRATCH = Path(r"D:\TLGL\.scratch")
OUT = SCRATCH / "agent_map_verify.txt"
L = []


def log(*a):
    L.append(" ".join(str(x) for x in a))


con = sqlite3.connect("file:resources.db?mode=ro", uri=True)


def load_pak_hashes():
    return {r[0] for r in con.execute("SELECT hash FROM resources")}


def drain_rpc_blob(raw):
    """newest JRPC generation: [u32 magic][u32 size-16][u32 count][u8 len + ascii]*"""
    if raw[:4] != b"JRPC":
        return None
    size, count = struct.unpack_from("<2I", raw, 4)
    out, i = [], 12
    end = 4 + 4 + size - 4
    while i < min(len(raw), 4 + size) and len(out) < count * 3:
        n = raw[i]
        i += 1
        s = raw[i : i + n]
        i += n
        if n == 0 or n > 200 or i > len(raw):
            break
        try:
            out.append(s.decode("ascii"))
        except UnicodeDecodeError:
            break
    return count, out


def main():
    hashes = load_pak_hashes()
    log(f"resources.hash rows: {len(hashes)}")

    # ---- C1: what does ResourcePath.cfg really contain? ----
    rows = con.execute(
        "SELECT hash, pak, offset, original FROM resources WHERE lower(path) LIKE '%resourcepath.cfg%'"
    ).fetchall()
    log(f"ResourcePath.cfg resources rows: {len(rows)} -> {rows[:3]}")

    # the pak reader path: use payload decode through the already-extracted tree if present
    cand = list((SCRATCH / "out" / "tree").rglob("ResourcePath.cfg"))
    log(f"extracted ResourcePath.cfg candidates: {[str(c) for c in cand][:4]}")
    best = None
    for c in cand:
        raw = c.read_bytes()
        got = drain_rpc_blob(raw)
        log(f"  {c} size={len(raw)} magic={raw[:4]!r} -> {None if not got else (got[0], len(got[1]))}")
        if got and (best is None or len(got[1]) > len(best[1])):
            best = got
    if not best:
        log("C1: 没能从解包树里读到 JRPC，跳过（不下结论）")
    else:
        declared, paths = best
        ext = Counter()
        for p in paths:
            m = re.search(r"\.([A-Za-z0-9]{1,6})$", p)
            ext[(m.group(1).lower() if m else "(noext)")] += 1
        log(f"C1 JRPC declared count = {declared}, drained paths = {len(paths)}, distinct = {len(set(paths))}")
        log("   extension census (top 14): " + ", ".join(f"{k}={v}" for k, v in ext.most_common(14)))
        tga = [p for p in paths if p.lower().endswith(".tga")]
        log(f"   .tga paths in cfg: {len(tga)} (sample {tga[:3]})")
        hit = sum(1 for p in tga if f"{jhash.path_hash(p):016x}" in hashes)
        log(f"   .tga whose path_hash IS an installed resource: {hit} / {len(tga)}")
        allm = sum(1 for p in paths if f"{jhash.path_hash(p):016x}" in hashes)
        log(f"   ALL cfg paths whose hash is installed: {allm} / {len(paths)}")
        named_db = {r[0] for r in con.execute("SELECT lower(path) FROM resources WHERE path IS NOT NULL")}
        missing = [p for p in paths if f"{jhash.path_hash(p):016x}" in hashes and p.lower() not in named_db]
        log(f"   installed-but-absent-from-db-rows: {len(missing)} (sample {missing[:3]})")

    # ---- C2: .scene record layout ----
    scenes = [r[0] for r in con.execute("SELECT path FROM resources WHERE lower(path) LIKE '%.scene' AND path IS NOT NULL")]
    log(f"\nC2 .scene rows in db: {len(scenes)}")
    files = [p for p in scenes if p.lower().endswith(".scene")]
    picked = []
    for rel in files:
        f = SCRATCH / "out" / "tree" / Path(rel)
        if f.exists() and f.stat().st_size > 20000:
            picked.append((rel, f))
        if len(picked) >= 3:
            break
    for rel, f in picked:
        raw = f.read_bytes()
        n, tag, z = struct.unpack_from("<3I", raw, 0)
        rec = 761
        log(f"\n  {rel} size={len(raw)} head=({n},{tag},{z}) 12+{rec}*{n}={12 + rec * n} vs {len(raw)}")
        ok_m = ok_name = 0
        grids = Counter()
        lim = min(n, 400, (len(raw) - 12 - 64) // rec)
        for i in range(lim):
            off = 12 + rec * i
            m = struct.unpack_from("<16f", raw, off)
            last = [round(x, 4) for x in m[12:16]]
            if abs(last[0]) < 1e-6 and abs(last[1]) < 1e-6 and abs(last[2]) < 1e-6 and abs(last[3] - 1) < 1e-4:
                ok_m += 1
            nb = raw[off + 64 : off + rec]
            e = nb.find(b"\0")
            nm = nb[: e if e >= 0 else 0].decode("latin1")
            if nm.endswith(".mesh"):
                ok_name += 1
            if i < 40:
                grids[(int(m[12] // 32), int(m[14] // 32))] += 1
            if i < 2:
                log(f"    rec{i} matrix={[round(x,3) for x in m]}  name={nm!r}")
        log(f"    checked {lim}: row-last-0001 {ok_m}, name ends .mesh {ok_name}")
        log(f"    grid cells floor(x/32),floor(z/32) first40: {grids.most_common(4)}  filename parts={Path(rel).name.split('_')}")
    OUT.write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L[:6]))


if __name__ == "__main__":
    main()
