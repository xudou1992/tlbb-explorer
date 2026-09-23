"""Task A, final rule: FORWARD validated scan for the submesh count array.

    pos_end = 0x118 + vc*12
    scan p = pos_end .. len-(4*sm+6*fc), step 2:
        counts = u32[sm] @ p                ; sum(counts)==fc, each count<=fc
        idx    = u16[3*fc] @ p+4*sm         ; every value < vc
    first p that validates is the answer; sm==1 degenerates to the legacy rule.

Also reports:
  * how far the index blocks sit from EOF (the "tail" region, variable)
  * ground-truth cross-check against the static layout (middle == vc*20)
  * ambiguity (how many p validate) and false-positive rate
"""
import json
import struct
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

TREE = Path(r"D:\TLGL\.scratch\out\tree")
OUT = Path(r"D:\TLGL\.scratch\agent_fmt_rule2.txt")
log_lines = []


def log(*a):
    log_lines.append(" ".join(str(x) for x in a))


def u32_at(b, o):
    return struct.unpack_from("<I", b, o)[0] if 0 <= o and o + 4 <= len(b) else None


def scan(raw, vc, fc, sm, pos_end, want_all=False, cap=8):
    n = len(raw)
    need = 4 * sm + 6 * fc
    hi = n - need
    if fc == 0 or hi < pos_end:
        return []
    win = raw[pos_end:hi + 1]
    m = (len(win) - 3) // 2
    if m <= sm:
        return []
    b = np.frombuffer(win, dtype=np.uint8)
    a = np.lib.stride_tricks.as_strided(b, shape=(m, 4), strides=(2, 1))
    u = (a[:, 0].astype(np.int64) | (a[:, 1].astype(np.int64) << 8)
         | (a[:, 2].astype(np.int64) << 16) | (a[:, 3].astype(np.int64) << 24))
    cs = np.concatenate(([0], np.cumsum(u)))
    sums = cs[sm:] - cs[:-sm]
    cand = np.nonzero(sums == fc)[0]
    out = []
    idx_lim = vc
    for i in cand:
        i = int(i)
        p = pos_end + 2 * i
        blk = u[i:i + sm]
        if blk.max() > fc:
            continue
        off = p + 4 * sm
        if off + 6 * fc > n:
            continue
        idx = np.frombuffer(raw, dtype="<u2", count=fc * 3, offset=off)
        if int(idx.max()) >= idx_lim:
            continue
        out.append((p, tuple(int(x) for x in blk)))
        if not want_all or len(out) >= cap:
            break
    return out


def main():
    t0 = time.time()
    files = sorted(TREE.rglob("*.mesh"))
    log(f"corpus: {len(files)} .mesh")
    stat = Counter()
    per_sm = defaultdict(Counter)
    tail_h = Counter()
    align_h = Counter()
    ambig_h = Counter()
    gt = Counter()
    bad = defaultdict(list)
    good = defaultdict(list)
    big_vc = []
    tailsum = Counter()
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
        pos_end = 0x118 + vc * 12
        rel = str(f.relative_to(TREE))
        if pos_end > n:
            stat["pos_stream_overflow"] += 1
            per_sm[min(smv, 12)]["pos_overflow"] += 1
            if len(bad["pos_overflow"]) < 15:
                bad["pos_overflow"].append((rel, n, vc, fc, smv))
            continue
        if vc > 65535:
            big_vc.append((rel, n, vc, fc, smv))
        # legacy ground truth for sm==1 static files (and every static file whose
        # first u32 at pos_end+vc*20 equals fc)
        static_p = pos_end + vc * 20
        legacy_p = static_p if u32_at(raw, static_p) == fc else None
        res = scan(raw, vc, fc, smv, pos_end, want_all=True, cap=6)
        if not res:
            stat["scan_fail"] += 1
            per_sm[min(smv, 12)]["scan_fail"] += 1
            if len(bad["scan_fail"]) < 40:
                bad["scan_fail"].append((rel, n, vc, fc, smv, legacy_p))
            continue
        p, counts = res[0]
        stat["scan_ok"] += 1
        per_sm[min(smv, 12)]["scan_ok"] += 1
        align_h[p % 4] += 1
        ambig_h[len(res)] += 1
        tail = n - (p + 4 * smv + 6 * fc)
        tail_h[min(tail, 4096) // 32 * 32] += 1
        tailsum["eq0" if tail == 0 else ("le8" if tail <= 8 else ("le256" if tail <= 256 else "gt256"))] += 1
        if legacy_p is not None:
            gt["same" if legacy_p == p else "diff"] += 1
            if legacy_p != p and len(bad["static_mismatch"]) < 20:
                bad["static_mismatch"].append((rel, n, vc, fc, smv, f"static=0x{legacy_p:X} scan=0x{p:X}"))
        if smv >= 2 and len(good[min(smv, 12)]) < 3:
            good[min(smv, 12)].append((rel, n, vc, fc, smv, p, tail, list(counts), p - pos_end))
        if time.time() - t0 > 230:
            log(f"!! TIME BUDGET after {done}/{len(files)}")
            break

    log("")
    log("=== outcome ===")
    for k, v in stat.most_common():
        log(f"  {k:22s} {v}")
    log("")
    log("=== per sm: scan_ok / scan_fail / pos_overflow ===")
    okf = okb = 0
    for k in sorted(per_sm):
        c = per_sm[k]
        okf += c["scan_ok"]
        okb += c["scan_fail"] + c["pos_overflow"]
        log(f"  sm={k:<4} ok={c['scan_ok']:<6} fail={c['scan_fail']:<6} pos_ovf={c['pos_overflow']}")
    log(f"  TOTAL ok={okf} fail={okb}")
    log("")
    log("=== index-block-to-EOF distance (bytes, bucketed by 32) ===")
    for k, v in sorted(tail_h.items())[:20]:
        log(f"  tail~{k:<6} {v}")
    log("  buckets: " + str(tailsum.most_common()))
    log("=== alignment of count array p%4 ===")
    for k, v in sorted(align_h.items()):
        log(f"  p%4={k}: {v}")
    log("=== how many validating positions found per file ===")
    for k, v in sorted(ambig_h.items())[:10]:
        log(f"  {k}: {v}")
    log("=== cross-check vs static layout (u32@pos_end+vc*20 == fc) ===")
    for k, v in gt.most_common():
        log(f"  {k}: {v}")
    log("")
    log(f"=== files with vc>65535 (u16 index limit): {len(big_vc)} ===")
    for e in big_vc[:15]:
        log(f"  {e}")
    log("")
    log("=== examples by sm ===")
    for k in sorted(good):
        for e in good[k][:2]:
            log(f"  sm={k} {e[0]}")
            log(f"     size={e[1]} vc={e[2]} fc={e[3]} sm={e[4]} p=0x{e[5]:X} tail={e[6]} middle={e[8]} counts={e[7]}")
    log("")
    log("=== failures ===")
    for k in bad:
        for e in bad[k][:25]:
            log(f"  [{k}] {e}")
    OUT.write_text("\n".join(log_lines), encoding="utf-8")
    json.dump({"stat": dict(stat), "per_sm": {str(k): dict(v) for k, v in per_sm.items()},
               "tail": {str(k): v for k, v in tail_h.most_common(40)}, "gt": dict(gt),
               "align": {str(k): v for k, v in align_h.items()}},
              open(r"D:\TLGL\.scratch\agent_fmt_rule2.json", "w"), indent=1)
    print("wrote", OUT, "elapsed", round(time.time() - t0, 1))


if __name__ == "__main__":
    main()
