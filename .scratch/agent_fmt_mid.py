"""Task B1: what is the 'middle' region between the position stream and the index blocks?

For each sample we locate the count array (validated rule), take
    middle = [0x118+vc*12 , p)
and test:
  (1) linear size models   middle = a*vc + b*fc + c          (grid exact-fit count)
  (2) is there a unit-normal f32 stream inside the middle? (stride-3 run detection)
  (3) does a UV-like f32x2 stream follow it?
  (4) leftover bytes: bone index / weight layouts
"""
import struct
from pathlib import Path

import numpy as np

TREE = Path(r"D:\TLGL\.scratch\out\tree")
OUT = Path(r"D:\TLGL\.scratch\agent_fmt_mid.txt")
L = []


def log(*a):
    L.append(" ".join(str(x) for x in a))


import agent_fmt_lib as _lib


def find_p(raw, vc, fc, sm, pos_end, limit=0):
    return _lib.locate(raw, vc, fc, sm, pos_end)


def unit_runs(buf, minlen):
    """4-aligned offsets where >= minlen consecutive stride-3 f32 triples have |v|~1"""
    n = len(buf) // 4
    if n < 12:
        return []
    f = np.frombuffer(buf[:n * 4], dtype="<f4")
    sq = np.where(np.isfinite(f), f * f, np.inf)
    t = sq[:n - 2] + sq[1:n - 1] + sq[2:n]
    unit = np.zeros(n, bool)
    unit[:n - 2] = (t > 0.94) & (t < 1.06)
    out = []
    for r in (0, 1, 2):
        u = unit[r::3]
        if u.size < minlen:
            continue
        idx = np.flatnonzero(~u)
        bounds = np.concatenate(([-1], idx, [u.size]))
        for k in range(len(bounds) - 1):
            ln = bounds[k + 1] - bounds[k] - 1
            if ln >= minlen:
                st = bounds[k] + 1
                out.append((4 * (r + 3 * st), ln))  # byte offset in buf, run length in verts
    return out


def f32_stats(buf, off, count, label):
    if off < 0 or off + count * 4 > len(buf):
        return None
    v = np.frombuffer(buf, dtype="<f4", count=count, offset=off)
    fin = np.isfinite(v)
    return (f"{label}: n={count} min={v[fin].min() if fin.any() else 'nan'} "
            f"max={v[fin].max() if fin.any() else 'nan'} mean={v[fin].mean() if fin.any() else 'nan'} "
            f"finite={100.0*fin.mean():.1f}% in[0,1]={100.0*((v>=0)&(v<=1)).mean():.1f}%")


def analyse(path, deep=True):
    raw = path.read_bytes()
    n = len(raw)
    vc, fc, sm = struct.unpack_from("<3I", raw, 0x8C)
    sm = int(sm or 1)
    pos_end = 0x118 + vc * 12
    r = find_p(raw, vc, fc, sm, pos_end)
    log(f"\n### {path.name} size={n} vc={vc} fc={fc} sm={sm} pos_end=0x{pos_end:X}")
    if r is None:
        log("    locate FAILED")
        return None
    p, counts = r
    middle = p - pos_end
    buf = raw[pos_end:p]
    log(f"    p=0x{p:X} tail_after_idx={n-(p+4*sm+6*fc)} middle={middle} mid/vc={middle/max(1,vc):.4f} counts={list(counts)}")
    log(f"    models: vc*20={vc*20} (mid-vc*20)={middle-vc*20} fc*2={fc*2} "
        f"residual_after_20vc_2fc={middle-vc*20-fc*2} 12vc={vc*12} 24vc={vc*24} 28vc={vc*28} 32vc={vc*32}")
    if not deep:
        return
    log("    mid[0:64]   " + raw[pos_end:pos_end + 64].hex(" "))
    log("    mid[-64:]   " + raw[p - 64:p].hex(" "))
    log("    " + str(f32_stats(buf, 0, 12, "mid head f32")))
    log("    " + str(f32_stats(buf, middle - 48, 12, "mid tail f32")))
    # normal stream hunt
    runs = unit_runs(buf, max(64, int(vc * 0.8)))
    log(f"    unit-normal runs (>= {max(64, int(vc*0.8))} verts): "
        + ", ".join(f"mid+0x{off:X}(abs 0x{pos_end+off:X}) len={ln}" for off, ln in runs[:10]))
    if runs:
        off, ln = runs[0]
        log("    " + str(f32_stats(buf, off + ln * 12, min(vc * 8, len(buf) - off - ln * 12), "after-normal f32 (uv?)")))
        log("    " + str(f32_stats(buf, max(0, off - min(vc * 8, off)), min(vc * 8, off), "before-normal f32 (uv?)")))
    # whole-middle profiles in 4KB slices: f32 plausibility
    log("    slice profile (off, %finite_f32, %|f|<=1.1, %in[0,1]):")
    step = max(1, len(buf) // 40 // 4 * 4) or 4
    for off in range(0, len(buf) - 256, step):
        v = np.frombuffer(buf, dtype="<f4", count=64, offset=off)
        fin = np.isfinite(v)
        log("      0x%06X  fin=%.0f%%  le1.1=%.0f%%  in01=%.0f%%  u16max=%d" % (
            pos_end + off, 100 * fin.mean(),
            100 * np.mean(np.abs(np.where(fin, v, 9)) <= 1.1),
            100 * np.mean((v >= 0) & (v <= 1)),
            int(np.frombuffer(buf, dtype="<u2", count=128, offset=off).max())))
        if off > 200000:
            log("      ... (capped)")
            break


def model_fit(samples):
    """count exact fits of middle = a*vc + b*fc + c over all located samples"""
    best = []
    for a in (8, 12, 16, 20, 24, 28, 32, 36, 40, 44, 48):
        for b in (0, 2, 4, 6, 8, 12, 20, 24):
            for c in (0, 4, 8, 16, 32, 64):
                hits = sum(1 for vc, fc, mid in samples if mid == a * vc + b * fc + c)
                if hits:
                    best.append((hits, a, b, c))
    best.sort(reverse=True)
    log("=== size-model fit over located corpus samples (top 12) ===")
    for h, a, b, c in best[:12]:
        log(f"  middle = {a}*vc + {b}*fc + {c}   exact hits {h}/{len(samples)}")


def main():
    samples = {
        "static_ctrl": [
            r"data\effect\effectmodel\w1351_model_mianpian_l001.mesh",
            r"data\effect\effectmodel\w1351_model_plane_c01.mesh",
            r"data\source\npc\quest\w1351_npc_duantai01\w1351_npc_duantai01.mesh",
            r"data\effect\effectmodel\w1351_model_fengsha_h001.mesh",
        ],
        "skinned_effect": [
            r"data\effect\effectmodel\test_jianzhen.mesh",
            r"data\effect\effectmodel\test_jianzhen2.mesh",
            r"data\effect\effectmodel\w1351_model_emiter_lf002.mesh",
            r"data\effect\effectmodel\w1351_model_emiter_lf004.mesh",
            r"data\effect\effectmodel\w1351_model_pl_h006.mesh",
        ],
        "map_props": [
            r"mobile_maps_source\w1351_st_fwzhongxing_001.mesh",
            r"mobile_maps_source\w1351_bmy_shanshi_009.mesh",
            r"mobile_maps_source\w1351_bpzd_dashubaoshi_001.mesh",
            r"mobile_maps_source\w1351_bpzd_dasongshuduan_001.mesh",
        ],
    }
    for grp, rels in samples.items():
        log(f"########## group {grp}")
        for rel in rels:
            f = TREE / rel
            if not f.exists():
                log(f"!! missing {rel}")
                continue
            try:
                analyse(f)
            except Exception as e:  # noqa
                log(f"!! EXC {rel}: {type(e).__name__}: {e}")

    # corpus-wide linear model fit (header + tail-window reads only)
    log("\n=== collecting middle sizes over corpus ===")
    coll = []
    cnt = 0
    for f in sorted(TREE.rglob("*.mesh")):
        cnt += 1
        if cnt > 600:
            break
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
        if sm > 16 or vc > 200000 or fc > 200000:
            continue
        pos_end = 0x118 + vc * 12
        r = find_p(raw, vc, fc, sm, pos_end, limit=0)
        if r:
            coll.append((vc, fc, r[0] - pos_end))
    log(f"located {len(coll)} files (of {cnt} read)")
    model_fit(coll)
    from collections import Counter
    kk = Counter()
    for vc, fc, mid in coll:
        tag = None
        for a in (8, 12, 16, 20, 24, 28, 32, 36, 40, 44, 48):
            for b in (0, 2, 4, 6, 8, 12, 20, 24):
                c = mid - a * vc - b * fc
                if c == 0:
                    kk[f"exact:{a}*vc+{b}*fc"] += 1
        kk["eq20vc" if mid == vc * 20 else "gt20vc" if mid > vc * 20 else "lt20vc"] += 1
    log("=== per-file small residual forms (top 20) ===")
    for k, v in kk.most_common(20):
        log(f"  {k}: {v}")
    OUT.write_text("\n".join(L), encoding="utf-8")
    print("wrote", OUT, len(L))


if __name__ == "__main__":
    main()
