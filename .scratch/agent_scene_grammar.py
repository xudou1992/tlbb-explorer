"""Nail the .scene record grammar from the data, not from a guessed stride.

Method: every record carries an embedded ASCII mesh name. So take the byte offsets of
all name occurrences in a file and measure the gaps. A constant stride shows one value;
variable records show a base + per-record extra. Then locate the 4x4 matrix relative to
each name and see what field (if any) encodes the record length.
"""
import re
import sqlite3
import struct
from collections import Counter
from pathlib import Path

SCRATCH = Path(r"D:\TLGL\.scratch")
TREE = SCRATCH / "out" / "tree"
OUT = SCRATCH / "agent_scene_grammar.txt"
L = []
NAME_RE = re.compile(rb"[ -~]{5,64}?\.(?:mesh|tga|mtl|ske|ani)\x00")


def log(*a):
    L.append(" ".join(str(x) for x in a))


def names(raw):
    return [(m.start(), m.group().rstrip(b"\x00")) for m in re.finditer(rb"[ -~]{5,64}?\.(?:mesh|tga|mtl|ske|ani)\x00", raw)]


def probe(rel):
    f = TREE / rel
    if not f.exists():
        return None
    raw = f.read_bytes()
    if len(raw) < 64:
        head = struct.unpack_from("<I", raw, 0)[0] if len(raw) >= 4 else "?"
        log(f"  {rel}: 只有 {len(raw)} 字节（空格子文件，u32@0={head}）")
        return None
    n0, tag, w = struct.unpack_from("<3I", raw, 0)
    ns = names(raw)
    gaps = Counter(ns[i + 1][0] - ns[i][0] for i in range(len(ns) - 1))
    # what sits at offset 0..? of each record: find the matrix by looking 64 bytes before the name
    mats = 0
    for off, _ in ns[:60]:
        mo = off - 64
        if mo < 12:
            continue
        m = struct.unpack_from("<16f", raw, mo)
        row4 = m[12:16]
        col4 = (m[3], m[7], m[11], m[15])
        if all(abs(c) < 1e-6 for c in col4[:3]) and abs(col4[3] - 1) < 1e-4 and abs(row4[3] - 1) < 1e-4:
            mats += 1
    # candidate length fields: u32 just before each record start
    lens = []
    for off, _ in ns[:80]:
        base = off - 64
        for back in (4, 8, 12, 68, 72):
            v = struct.unpack_from("<I", raw, base - back)[0] if base - back >= 0 else 0
            if 40 < v < 4000:
                lens.append((back, v))
    log(f"\n{rel}")
    log(f"  size={len(raw)} head u32=({n0},{tag},{w}) f32@8={struct.unpack_from('<f', raw, 8)[0]:.4f}")
    log(f"  names found={len(ns)}  declared N={n0}   distinct={len(set(x[1] for x in ns))}")
    log(f"  gaps between name starts (top 8): {gaps.most_common(8)}")
    log(f"  (size-12)/N = {(len(raw)-12)/max(n0,1):.2f}   (size-12)/names = {(len(raw)-12)/max(len(ns),1):.2f}")
    log(f"  matrices with 0,0,0,1 col AND x,y,z,1 row: {mats}/{min(len(ns),60)}")
    log(f"  plausible length fields (back_from_record_start, value) top 6: {Counter(lens).most_common(6)}")
    return raw, n0, tag, ns


def main():
    con = sqlite3.connect("file:resources.db?mode=ro", uri=True)
    rows = [r[0] for r in con.execute("SELECT path FROM resources WHERE lower(path) LIKE '%.scene' AND path IS NOT NULL")]
    by_map = {}
    for p in rows:
        parts = p.split("/")
        if len(parts) >= 3 and parts[0] == "mobile_maps":
            by_map.setdefault(parts[1], []).append(p)
    picked = sorted(by_map, key=lambda k: -len(by_map[k]))[:3]
    log(f"scene files in db: {len(rows)}, maps with scenes: {len(by_map)}")
    for mp in picked:
        fs = sorted(by_map[mp])
        log(f"\n=== 地图 {mp}: {len(fs)} 个格子文件, 例 {fs[0]}")
        sizes = [ (TREE / p).stat().st_size for p in fs if (TREE / p).exists() ]
        log(f"  size 分布: min={min(sizes)} max={max(sizes)} n={len(sizes)}")
        biggest = max(fs, key=lambda p: (TREE / p).stat().st_size if (TREE / p).exists() else 0)
        probe(biggest)
        probe(fs[0])
        # whole-map consistency: does N always equal number of embedded names?
        eq = tot = 0
        strides = Counter()
        for p in fs[:120]:
            f = TREE / p
            if not f.exists():
                continue
            raw = f.read_bytes()
            if len(raw) <= 12:
                continue
            n0 = struct.unpack_from("<I", raw, 0)[0]
            ns = names(raw)
            tot += 1
            eq += n0 == len(ns)
            if ns:
                g = Counter(ns[i + 1][0] - ns[i][0] for i in range(len(ns) - 1))
                if g:
                    strides[g.most_common(1)[0][0]] += 1
        log(f"  全图抽样 {tot} 个文件：N == 内嵌名字条数 的有 {eq} ({100*eq/max(tot,1):.1f}%)")
        log(f"  最常见记录间距分布 top6: {strides.most_common(6)}")
    OUT.write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L[:26]))


if __name__ == "__main__":
    main()
