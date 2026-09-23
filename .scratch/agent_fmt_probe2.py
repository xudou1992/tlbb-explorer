"""Probe 2: verify the [sm x u32 faceCount][sm blocks of 3*count u16][tail] tail layout.

Rule under test:
    len(raw) = TAIL + 6*fc + 4*sm + MIDDLE + vc*12 + 0x118
    at p = len - TAIL - 6*fc - 4*sm : u32 count[sm], sum(count)==fc
    at p + 4*sm : sm consecutive blocks, block i = count[i]*3 u16, all < vc
"""
import struct
import sys
from pathlib import Path

import numpy as np

TREE = Path(r"D:\TLGL\.scratch\out\tree")
OUT = Path(r"D:\TLGL\.scratch\agent_fmt_probe2.txt")
L = []


def log(*a):
    L.append(" ".join(str(x) for x in a))


def u32(b, o):
    return struct.unpack_from("<I", b, o)[0] if 0 <= o and o + 4 <= len(b) else None


def hexdump(raw, off, n, title):
    log(f"--- {title} @0x{off:X} ---")
    for i in range(off, min(off + n, len(raw)), 16):
        chunk = raw[i:i + 16]
        log(f"  {i:#08x} " + " ".join(f"{b:02x}" for b in chunk) + "  |" +
            "".join(chr(b) if 32 <= b < 127 else "." for b in chunk) + "|")


def solve(raw, vc, fc, sm, tails=(0, 8)):
    """try each tail length, return (p, counts, ok_reason)"""
    for t in tails:
        p = len(raw) - t - 6 * fc - 4 * sm
        if p < 0x118 + vc * 12:
            continue
        counts = struct.unpack_from("<%dI" % sm, raw, p)
        if sum(counts) != fc:
            continue
        hi = max(int(np.max(np.frombuffer(raw, dtype='<u2', count=fc * 3, offset=p + 4 * sm))) if fc else 0, 0)
        if hi >= vc:
            continue
        return p, counts, t, hi
    return None


def analyse(path):
    raw = path.read_bytes()
    vc, fc, sm = struct.unpack_from("<3I", raw, 0x8C)
    pos_end = 0x118 + vc * 12
    log(f"\n### {path.name} size={len(raw)} vc={vc} fc={fc} sm={sm} ver={u32(raw,0x48)} "
        f"tag={raw[0x40:0x44]!r} banner={raw[:8]==b'Copyright '} pos_end={pos_end:#x}")
    log(f"    last16: {raw[-16:].hex(' ')}")
    r = solve(raw, vc, fc, sm)
    if r is None:
        # brute force over tail 0..64
        for t in range(0, 65):
            r = solve(raw, vc, fc, sm, (t,))
            if r:
                log(f"    !! needed tail={t}")
                break
    if r is None:
        log("    NO FIT for tail in 0..64")
        return
    p, counts, t, hi = r
    middle = p - pos_end
    log(f"    count-array @0x{p:X} ({p})  p%4={p%4} middle={middle} middle/vc={middle/vc:.3f} tail={t}")
    log(f"    counts={list(counts)} sum={sum(counts)}")
    # per block stats
    o = p + 4 * sm
    for i, c in enumerate(counts):
        blk = np.frombuffer(raw, dtype='<u2', count=c * 3, offset=o)
        log(f"    block{i}: off=0x{o:X} faces={c} min={int(blk.min())} max={int(blk.max())} "
            f"first8={list(map(int, blk[:8]))} distinct_verts={int(len(np.unique(blk)))}")
        o += c * 6
    log(f"    index data ends at 0x{o:X} ({o}) ; file end 0x{len(raw):X}; tail bytes={raw[o:].hex(' ')}")
    hexdump(raw, max(0x118, p - 48), 48, "48B before count array")
    hexdump(raw, pos_end, 64, "first 64B of middle")
    hexdump(raw, pos_end + middle - 64, 64, "last 64B of middle")
    # float view of middle start
    f = np.frombuffer(raw, dtype='<f4', count=24, offset=pos_end)
    log("    middle as f32[0:24]: " + ", ".join(f"{x:.4g}" for x in f))
    f = np.frombuffer(raw, dtype='<f4', count=24, offset=pos_end + middle - 96)
    log("    middle tail as f32: " + ", ".join(f"{x:.4g}" for x in f))


def main():
    named = [
        r"data\effect\effectmodel\w1351_model_emiter_lf002.mesh",
        r"mobile_maps_source\w1351_st_fwzhongxing_001.mesh",
        r"data\effect\effectmodel\test_jianzhen.mesh",
        r"mobile_maps_source\w1351_bmy_shanshi_009.mesh",
        r"mobile_maps_source\w1351_bpzd_dashubaoshi_001.mesh",
        r"mobile_maps_source\w1351_bpzd_dasongshuduan_001.mesh",
        r"mobile_maps_source\w1351_bpzd_gouhuoyuanguo_001.mesh",
        r"data\effect\effectmodel\w1351_model_mianpian_l001.mesh",
    ]
    for rel in named:
        f = TREE / rel
        if f.exists():
            analyse(f)
        else:
            log(f"!! missing {rel}")

    # a spread of failures across sm, found by header-only scan (cheap)
    picked = {}
    for f in TREE.rglob("*.mesh"):
        try:
            with open(f, "rb") as fh:
                fh.seek(0x8C)
                h = fh.read(12)
            if len(h) < 12:
                continue
            vc, fc, sm = struct.unpack("<3I", h)
        except (OSError, struct.error):
            continue
        if not sm or sm < 2 or sm > 9 or vc > 20000:
            continue
        if 0x118 + vc * 32 + 4 + fc * 6 > f.stat().st_size:
            pass  # candidate failure
        key = int(sm)
        if len(picked.get(key, [])) < 2:
            picked.setdefault(key, []).append(f)
        if all(len(v) >= 2 for v in picked.values()) and len(picked) >= 8:
            break
    for k in sorted(picked):
        for f in picked[k]:
            try:
                analyse(f)
            except Exception as e:  # noqa
                log(f"\n### {f.name} EXC {type(e).__name__}: {e}")

    OUT.write_text("\n".join(L), encoding="utf-8")
    print("wrote", OUT, len(L), "lines")


if __name__ == "__main__":
    main()
