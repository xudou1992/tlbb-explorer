"""Task A FINAL validation.

Candidate rules, applied to every .mesh:
  R_LEG  = geometry.rs behaviour: first p with u32(p)==fc and fc*3 u16 < vc (scan from pos_end)
  R_FWD  = forward validated scan: first p where u32[sm] sums to fc AND 6*fc bytes of
           u16 following the array are all < vc
  R_EOF  = same validation but anchored from EOF (smallest tail that fits) -> tells us
           whether the index blocks are the last thing in the file
Reports recovery over the R_LEG failures (the 1775 sm>=2 files), agreement with the
static layout, tail distribution, block-level sanity and ambiguity.
"""
import json
import struct
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

TREE = Path(r"D:\TLGL\.scratch\out\tree")
OUT = Path(r"D:\TLGL\.scratch\agent_fmt_rule3.txt")
L = []


def log(*a):
    L.append(" ".join(str(x) for x in a))


def u32_at(b, o):
    return struct.unpack_from("<I", b, o)[0] if 0 <= o and o + 4 <= len(b) else None


import agent_fmt_lib as _lib


def fwd_scan(raw, vc, fc, sm, pos_end, cap=4):
    return _lib.count_array_positions(raw, vc, fc, sm, pos_end, cap=cap)


def eof_scan(raw, vc, fc, sm, pos_end, limit=8192):
    n = len(raw)
    if fc == 0:
        return None
    for tail in range(0, min(limit, n) + 1, 2):
        p = n - tail - 6 * fc - 4 * sm
        if p < pos_end:
            break
        counts = struct.unpack_from("<%dI" % sm, raw, p)
        if sum(counts) != fc or max(counts) > fc:
            continue
        idx = np.frombuffer(raw, dtype="<u2", count=fc * 3, offset=p + 4 * sm)
        if int(idx.max()) >= vc:
            continue
        return p, tail, tuple(counts)
    return None


def legacy_locate(raw, lo, fc, vc):
    need = 4 + fc * 6
    if fc == 0 or len(raw) < need:
        return None
    hi = len(raw) - need
    want = struct.pack("<I", fc)
    at = lo
    while at <= hi:
        p = raw.find(want, at, hi + 4)
        if p < 0:
            return None
        idx = np.frombuffer(raw[p + 4:p + need], dtype="<u2")
        if idx.size == fc * 3 and int(idx.max(initial=0)) < vc:
            return p
        at = p + 4
    return None


def block_check(raw, p, sm, counts, vc):
    """per-submesh index ranges; returns list of (min,max,distinct) and overlap flag"""
    o = p + 4 * sm
    info = []
    seen_lo = None
    bad = 0
    for c in counts:
        idx = np.frombuffer(raw, dtype="<u2", count=max(c * 3, 1), offset=o) if c else None
        if c:
            mn, mx = int(idx.min()), int(idx.max())
            info.append((mn, mx))
            if mx >= vc:
                bad += 1
        else:
            info.append((None, None))
        o += c * 6
    return info, bad


def main():
    t0 = time.time()
    files = sorted(TREE.rglob("*.mesh"))
    log(f"corpus {len(files)} .mesh")
    stat = Counter()
    per_sm = defaultdict(Counter)
    agree = Counter()
    tail_h = Counter()
    amb = Counter()
    examples = defaultdict(list)
    bad = defaultdict(list)
    resc_sm = Counter()
    fail_sm = Counter()
    done = 0
    for f in files:
        done += 1
        try:
            raw = f.read_bytes()
        except OSError:
            stat["read_error"] += 1
            continue
        n = len(raw)
        if n < 0x118:
            stat["too_short"] += 1
            continue
        try:
            vc, fc, sm = struct.unpack_from("<3I", raw, 0x8C)
        except struct.error:
            stat["too_short"] += 1
            continue
        if vc > 8_000_000 or fc > 8_000_000 or sm > 64:
            stat["implausible"] += 1
            continue
        smv = int(sm or 1)
        rel = str(f.relative_to(TREE))
        pos_end = 0x118 + vc * 12
        if pos_end + 4 * smv + 6 * fc > n:
            stat["file_too_small_for_streams"] += 1
            per_sm[min(smv, 12)]["too_small"] += 1
            if len(bad["too_small"]) < 12:
                bad["too_small"].append((rel, n, vc, fc, smv))
            continue
        leg = legacy_locate(raw, pos_end, fc, vc)
        fwd = fwd_scan(raw, vc, fc, smv, pos_end)
        eof = eof_scan(raw, vc, fc, smv, pos_end)
        k = min(smv, 12)
        per_sm[k]["n"] += 1
        if fwd:
            p, counts = fwd[0]
            stat["fwd_ok"] += 1
            per_sm[k]["fwd_ok"] += 1
            amb[len(fwd)] += 1
            tail = n - (p + 4 * smv + 6 * fc)
            tail_h["t=0" if tail == 0 else "t<=8" if tail <= 8 else "t<=256" if tail <= 256
                    else "t<=4096" if tail <= 4096 else "t>4096"] += 1
            info, nbad = block_check(raw, p, smv, counts, vc)
            if nbad:
                stat["block_index_oob"] += 1
            sp = pos_end + vc * 20
            if u32_at(raw, sp) == fc and smv == 1:
                agree["static_eq_fwd_sm1" if sp == p else "static_ne_fwd_sm1"] += 1
            elif smv >= 2 and all(c > 0 for c in counts) and u32_at(raw, sp) == counts[0]:
                agree["static_eq_fwd_smN"] += 1
            if eof:
                agree["eof_same" if eof[0] == p else "eof_diff"] += 1
                if eof[0] != p and len(bad["eof_diff"]) < 12:
                    bad["eof_diff"].append((rel, n, vc, fc, smv, f"fwd=0x{p:X} eof=0x{eof[0]:X} tail_eof={eof[1]}"))
            else:
                agree["no_eof_fit"] += 1
            if leg is None:
                stat["fwd_rescues_legacy"] += 1
                resc_sm[k] += 1
                if len(examples[k]) < 4:
                    examples[k].append((rel, n, vc, fc, smv, p, tail, list(counts), p - pos_end, info[:4]))
            else:
                stat["both_ok"] += 1
                agree["legacy_same" if leg == p else "legacy_diff"] += 1
                if leg != p and len(bad["legacy_diff"]) < 12:
                    bad["legacy_diff"].append((rel, n, vc, fc, smv, f"legacy=0x{leg:X} fwd=0x{p:X}"))
        else:
            stat["fwd_fail"] += 1
            per_sm[k]["fwd_fail"] += 1
            fail_sm[k] += 1
            if len(bad["fwd_fail"]) < 40:
                bad["fwd_fail"].append((rel, n, vc, fc, smv, f"legacy={leg}"))
        if time.time() - t0 > 260:
            log(f"!! TIME BUDGET after {done}/{len(files)}")
            break

    log("\n=== outcome ===")
    for k, v in stat.most_common():
        log(f"  {k:28s} {v}")
    log("\n=== per sm: n / fwd_ok / fwd_fail / too_small ===")
    for k in sorted(per_sm):
        c = per_sm[k]
        log(f"  sm={k:<4} n={c['n']:<6} ok={c['fwd_ok']:<6} fail={c['fwd_fail']:<6} too_small={c['too_small']}")
    log("\n=== rescue of legacy failures (the sm>=2 set) by sm ===")
    log("  rescued: " + str(sorted(resc_sm.items())))
    log("  still failing: " + str(sorted(fail_sm.items())))
    log("\n=== agreements ===")
    for k, v in agree.most_common():
        log(f"  {k}: {v}")
    log("\n=== distance from index-data end to EOF ===")
    for k, v in tail_h.most_common():
        log(f"  {k}: {v}")
    log("\n=== number of validating positions per file ===")
    for k, v in sorted(amb.items())[:8]:
        log(f"  {k}: {v}")
    log("\n=== rescue examples (rel size vc fc sm p tail counts middle blockranges) ===")
    for k in sorted(examples):
        for e in examples[k]:
            log(f"  sm={k} {e[0]}")
            log(f"     size={e[1]} vc={e[2]} fc={e[3]} sm={e[4]} p=0x{e[5]:X} tail={e[6]} counts={e[7]} middle={e[8]} blocks={e[9]}")
    log("\n=== problems ===")
    for k in bad:
        for e in bad[k][:22]:
            log(f"  [{k}] {e}")
    OUT.write_text("\n".join(L), encoding="utf-8")
    json.dump({"stat": dict(stat), "per_sm": {str(k): dict(v) for k, v in per_sm.items()},
               "agree": dict(agree), "tail": dict(tail_h),
               "rescued": {str(k): v for k, v in resc_sm.items()},
               "still_failing": {str(k): v for k, v in fail_sm.items()}},
              open(r"D:\TLGL\.scratch\agent_fmt_rule3.json", "w"), indent=1)
    print("wrote", OUT, "elapsed", round(time.time() - t0, 1))


if __name__ == "__main__":
    main()
