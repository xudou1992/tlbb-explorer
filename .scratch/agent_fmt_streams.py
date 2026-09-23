"""Task A/B glue: does the .mesh header predict the middle-stream layout?

For every file we locate the submesh count array (validated), then fit
    middle = A*vc + B*fc + C      (A integer, B in {0,2,4,...}, C small)
and cross-tabulate against the raw header words 0x98..0x117, plus record the
trailing region (index-data end -> EOF) and try to fit it the same way.
"""
import struct
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

import agent_fmt_lib as lib

TREE = Path(r"D:\TLGL\.scratch\out\tree")
OUT = Path(r"D:\TLGL\.scratch\agent_fmt_streams.txt")
L = []


def log(*a):
    L.append(" ".join(str(x) for x in a))


def rel_short(f):
    return str(f.relative_to(TREE))


def main():
    t0 = time.time()
    files = sorted(TREE.rglob("*.mesh"))
    combo = Counter()
    cross = Counter()
    hdr_hist = Counter()
    tail_fit = Counter()
    tails = []
    unexplained = Counter()
    rows = []
    probes = []
    n_loc = n_tot = 0
    for f in files:
        try:
            raw = f.read_bytes()
        except OSError:
            continue
        if len(raw) < 0x118:
            continue
        try:
            vc, fc, sm = struct.unpack_from("<3I", raw, 0x8C)
        except struct.error:
            continue
        sm = int(sm or 1)
        if vc > 8_000_000 or fc > 8_000_000 or sm > 64 or vc == 0:
            continue
        pos_end = 0x118 + vc * 12
        r = lib.locate(raw, vc, fc, sm, pos_end)
        n_tot += 1
        if r is None:
            unexplained["not_located"] += 1
            continue
        n_loc += 1
        p, counts = r
        middle = p - pos_end
        end = p + 4 * sm + 6 * fc
        tail = len(raw) - end
        # exact A: middle = A*vc + B*fc, B in {0,2,4}
        found = None
        for B in (0, 2, 4, 6, 8, 12, 20):
            rem = middle - B * fc
            if rem >= 0 and rem % vc == 0:
                A = rem // vc
                if 8 <= A <= 128:
                    found = (A, B)
                    break
        if found is None:
            for B in (0, 2, 4, 6, 8):
                rem = middle - B * fc
                if rem >= 0:
                    C = rem % vc
                    A = rem // vc
                    if 8 <= A <= 128 and C <= 256:
                        found = (A, B, C)
                        break
        tag = f"A={found[0]} B={found[1]}" + (f" C={found[2]}" if found and len(found) > 2 else "") if found else "UNFIT"
        combo[tag] += 1
        hw = struct.unpack_from("<4H", raw, 0x10C)
        w110 = struct.unpack_from("<H", raw, 0x110)[0]
        w112 = struct.unpack_from("<H", raw, 0x112)[0]
        w114 = struct.unpack_from("<H", raw, 0x114)[0]
        w116 = struct.unpack_from("<H", raw, 0x116)[0]
        hdr_hist[f"[0x110]={w110} [0x112]={w112} [0x114]={w114} [0x116]={w116}"] += 1
        cross[(f"{w110},{w112},{w114},{w116}", tag)] += 1
        if tail == 0:
            tail_fit["tail=0"] += 1
        elif tail == 8:
            tail_fit["tail=8"] += 1
        elif tail == 2 * fc:
            tail_fit["tail=2*fc"] += 1
        elif tail == 4 * fc:
            tail_fit["tail=4*fc"] += 1
        elif tail == 12 * vc:
            tail_fit["tail=12*vc"] += 1
        elif tail == vc * 2:
            tail_fit["tail=2*vc"] += 1
        elif tail == sm * 4 or tail == sm * 8 or tail == sm * 12:
            tail_fit[f"tail=k*sm"] += 1
        elif tail < 0:
            tail_fit["negative!?"] += 1
        else:
            tail_fit["other"] += 1
            if len(probes) < 12 and 16 <= tail <= 4096:
                probes.append((f, raw, vc, fc, sm, p, counts, end, tail))
        rows.append((rel_short(f), vc, fc, sm, middle, tag, tail, f"{w110},{w112},{w114},{w116}"))
        if time.time() - t0 > 200:
            log("!! budget")
            break

    log(f"scanned {n_tot} files, located {n_loc}")
    log("=== middle stream layout: middle = A*vc + B*fc ===")
    for k, v in combo.most_common(20):
        log(f"  {k:28} {v}")
    log("\n=== header words 0x110/0x112/0x114/0x116 (top 12) ===")
    for k, v in hdr_hist.most_common(12):
        log(f"  {k}: {v}")
    log("\n=== (header words) x (layout) cross tab (top 25) ===")
    for (h, tag), v in cross.most_common(25):
        log(f"  hdr[{h}] {tag:22} -> {v}")
    log("\n=== trailing region classification ===")
    for k, v in tail_fit.most_common():
        log(f"  {k:14} {v}")
    if tails:
        pass
    log("\n=== tail probes (name size vc fc sm p counts end tail) ===")
    for f, raw, vc, fc, sm, p, counts, end, tail in probes:
        buf = raw[end:]
        nb = len(buf) // 4
        w = np.frombuffer(buf[:nb * 4], dtype="<u4") if nb else np.zeros(0, np.uint32)
        eb = (w >> 23) & 0xFF if nb else None
        fl = ((eb >= 100) & (eb <= 150)) if nb else np.zeros(0, bool)
        u16 = np.frombuffer(buf[:len(buf) // 2 * 2], dtype="<u2")
        log(f"\n  {rel_short(f)} size={len(raw)} vc={vc} fc={fc} sm={sm} p=0x{p:X} counts={list(counts)}")
        log(f"    tail={tail} at 0x{end:X}   tail/vc={tail/vc:.3f} tail/fc={tail/max(1,fc):.3f} tail/sm={tail/sm:.3f}")
        log("    hex head: " + buf[:48].hex(" "))
        log("    hex tail: " + buf[-32:].hex(" "))
        if nb:
            log("    u32: " + ", ".join(str(int(x)) for x in w[:16]))
            log(f"    f32-like words: {100*fl.mean():.0f}%")
        log("    u16: " + ", ".join(str(int(x)) for x in u16[:24]))
    OUT.write_text("\n".join(L), encoding="utf-8")
    print("wrote", OUT, "elapsed", round(time.time() - t0, 1), "located", n_loc)


if __name__ == "__main__":
    main()
