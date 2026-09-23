"""Full-corpus validation of the multi-submesh tail rule.

RULE (under test):
    pos_end = 0x118 + vc*12
    p       = len - tail - 6*fc - 4*sm          (p >= pos_end, tail >= 0 even)
    u32 counts[sm] @ p        : sum(counts) == fc, every count <= fc
    u16 index data @ p+4*sm   : fc*3 values, every one < vc
    sm == 1 degenerates to the legacy single [u32 fc][fc*3 u16] block.
"""
import json
import struct
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

TREE = Path(r"D:\TLGL\.scratch\out\tree")
OUT = Path(r"D:\TLGL\.scratch\agent_fmt_rule.txt")
FAST_TAILS = (0, 4, 8, 12, 16)
MAXT = 4096

log_lines = []


def log(*a):
    log_lines.append(" ".join(str(x) for x in a))


def u32_at(b, o):
    return struct.unpack_from("<I", b, o)[0] if 0 <= o and o + 4 <= len(b) else None


def check_p(raw, n, vc, fc, sm, pos_end, tail):
    p = n - tail - 6 * fc - 4 * sm
    if p < pos_end or p < 0 or p + 4 * sm + 6 * fc > n:
        return None
    counts = struct.unpack_from("<%dI" % sm, raw, p)
    if sum(counts) != fc or any(c > fc for c in counts):
        return None
    if fc:
        idx = np.frombuffer(raw, dtype="<u2", count=fc * 3, offset=p + 4 * sm)
        if int(idx.max()) >= vc:
            return None
    return p, counts


def rule_fit(raw, vc, fc, sm, pos_end):
    n = len(raw)
    for tail in FAST_TAILS:
        r = check_p(raw, n, vc, fc, sm, pos_end, tail)
        if r:
            return r[0], tail, r[1]
    for tail in range(0, min(MAXT, n) + 1, 2):
        if tail in FAST_TAILS:
            continue
        r = check_p(raw, n, vc, fc, sm, pos_end, tail)
        if r:
            return r[0], tail, r[1]
    return None


def rule_all(raw, vc, fc, sm, pos_end, limit=8192):
    n = len(raw)
    out = []
    for tail in range(0, min(limit, n) + 1, 2):
        r = check_p(raw, n, vc, fc, sm, pos_end, tail)
        if r:
            out.append((r[0], tail, r[1]))
    return out


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
        blk = raw[p + 4:p + need]
        idx = np.frombuffer(blk, dtype="<u2")
        if idx.size == fc * 3 and int(idx.max(initial=0)) < vc:
            return p
        at = p + 4
    return None


def main():
    t0 = time.time()
    files = sorted(TREE.rglob("*.mesh"))
    log(f"corpus: {len(files)} .mesh files")

    stat = Counter()
    tail_hist = Counter()
    align_hist = Counter()
    per_sm = defaultdict(Counter)
    legacy_vs_new = Counter()
    ambig = Counter()
    bad = defaultdict(list)
    good = defaultdict(list)
    middles = Counter()
    hdrnz = Counter()
    blocksizes = Counter()
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
            stat["short_header"] += 1
            continue
        try:
            vc, fc, sm = struct.unpack_from("<3I", raw, 0x8C)
        except struct.error:
            stat["short_header"] += 1
            continue
        if vc > 8_000_000 or fc > 8_000_000 or sm > 64:
            stat["implausible_header"] += 1
            continue
        smv = int(sm or 1)
        rel = str(f.relative_to(TREE))
        pos_end = 0x118 + vc * 12
        hdr_extra = any(raw[j] for j in range(0x98, 0x118))
        hdrnz[hdr_extra] += 1
        if pos_end > n:
            stat["position_stream_overflow"] += 1
            per_sm[min(smv, 12)]["pos_overflow"] += 1
            if len(bad["pos_overflow"]) < 15:
                bad["pos_overflow"].append((rel, n, vc, fc, smv, hdr_extra))
            continue
        legacy_p = (pos_end + vc * 20
                    if u32_at(raw, pos_end + vc * 20) == fc
                    else legacy_locate(raw, pos_end, fc, vc))
        r = rule_fit(raw, vc, fc, smv, pos_end)
        if r is None:
            stat["rule_no_fit"] += 1
            per_sm[min(smv, 12)]["no_fit"] += 1
            if legacy_p is not None:
                stat["no_fit_but_legacy_ok"] += 1
            if len(bad["no_fit"]) < 40:
                bad["no_fit"].append((rel, n, vc, fc, smv, hdr_extra, legacy_p))
            continue
        p, tail, counts = r
        stat["rule_fit"] += 1
        per_sm[min(smv, 12)]["fit"] += 1
        tail_hist[tail] += 1
        align_hist[p % 4] += 1
        middle = p - pos_end
        middles["eq_vc20" if middle == vc * 20 else ("lt_vc20" if middle < vc * 20 else "gt_vc20")] += 1
        blocksizes[(middle - vc * 20) if middle >= vc * 20 else middle] += 1
        if legacy_p is None:
            stat["rule_rescues_legacy_fail"] += 1
            per_sm[min(smv, 12)]["rescue"] += 1
        else:
            stat["both_fit"] += 1
            legacy_vs_new["same" if legacy_p == p else "diff"] += 1
            if legacy_p != p and len(bad["legacy_diff"]) < 15:
                bad["legacy_diff"].append((rel, n, vc, fc, smv, f"legacy=0x{legacy_p:X} rule=0x{p:X}"))
        if len(good[min(smv, 12)]) < 3:
            good[min(smv, 12)].append((rel, n, vc, fc, smv, p, tail, list(counts), middle))
        if time.time() - t0 > 210:
            log(f"!! TIME BUDGET after {done}/{len(files)} files")
            break

    log("")
    log("=== outcome (files considered: %d) ===" % done)
    for k, v in stat.most_common():
        log(f"  {k:28s} {v}")
    log("")
    log("=== per sm: fit / no_fit / rescue(legacy failed) / pos_overflow ===")
    tot_fit = tot_bad = 0
    for k in sorted(per_sm):
        c = per_sm[k]
        tot_fit += c["fit"]
        tot_bad += c["no_fit"] + c["pos_overflow"]
        log(f"  sm={k:<3} fit={c['fit']:<6} no_fit={c['no_fit']:<5} rescue={c['rescue']:<5} pos_ovf={c['pos_overflow']}")
    log(f"  TOTAL fit={tot_fit} unexplained={tot_bad}")
    log("")
    log("=== tail after index data ===")
    for k, v in tail_hist.most_common(14):
        log(f"  tail={k:<6} {v}")
    log("=== count-array alignment p%4 ===")
    for k, v in sorted(align_hist.items()):
        log(f"  p%4={k} : {v}")
    log("=== middle vs vc*20 ===")
    for k, v in middles.most_common():
        log(f"  {k}: {v}")
    log("=== legacy vs rule agreement on legacy hits ===")
    for k, v in legacy_vs_new.most_common():
        log(f"  {k}: {v}")
    log("=== header 0x98..0x117 all-zero? ===")
    for k, v in hdrnz.most_common():
        log(f"  hdr_extra_nonzero={k}: {v}")
    log("")
    log("=== examples: rule fit, by sm ===")
    for k in sorted(good):
        for e in good[k][:2]:
            mv = (e[8] / e[2]) if e[2] else 0
            log(f"  sm={k} {e[0]}")
            log(f"      size={e[1]} vc={e[2]} fc={e[3]} sm={e[4]} p=0x{e[5]:X} tail={e[6]} "
                f"counts={e[7]} middle={e[8]} middle/vc={mv:.3f}")
    log("")
    log("=== failures ===")
    for k in bad:
        for e in bad[k][:25]:
            log(f"  [{k}] {e}")

    OUT.write_text("\n".join(log_lines), encoding="utf-8")
    json.dump({"stat": dict(stat), "tail": {str(k): v for k, v in tail_hist.most_common(20)},
               "per_sm": {str(k): dict(v) for k, v in per_sm.items()},
               "blocksizes": {str(k): v for k, v in blocksizes.most_common(40)}},
              open(r"D:\TLGL\.scratch\agent_fmt_rule.json", "w"), indent=1)
    print("wrote", OUT, "elapsed", round(time.time() - t0, 1), "s")


if __name__ == "__main__":
    main()
