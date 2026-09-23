"""Task B2 deep dive: does .ske carry bone transforms (matrices / quats)?

Metrics per file (all 1630):
  * size, root-chunk (id 86) payload size == "body", string count, bone-like name count
  * float-like word test: IEEE exponent in [100,150] (|v| ~ 1e-8..1e14) -> real floats,
    as opposed to small u32 integers that decode to denormals (~1e-43)
  * longest run of float-like words (4-byte aligned) anywhere in the file
  * count of unit-quaternion-like f32x4 windows and identity-ish 4x4 windows
  * biggest (id,size) records found by a naive chunk walk + whether their payload is float-like
Corpus extras: extension census (is the keyframe data (.ani/.anis) even unpacked?)
"""
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

TREE = Path(r"D:\TLGL\.scratch\out\tree")
OUT = Path(r"D:\TLGL\.scratch\agent_fmt_ske2.txt")
sys.path.insert(0, r"D:\TLGL\.scratch")
import jbcf  # noqa: E402

L = []


def log(*a):
    L.append(" ".join(str(x) for x in a))


def float_like(words):
    e = (words >> 23) & 0xFF
    return (e >= 100) & (e <= 150)


def longest_run(mask):
    best = cur = 0
    for x in mask:
        cur = cur + 1 if x else 0
        if cur > best:
            best = cur
    return best


def longest_run_np(mask):
    if not mask.any():
        return 0, 0
    idx = np.flatnonzero(~mask)
    bounds = np.concatenate(([-1], idx, [mask.size]))
    ln = np.diff(bounds) - 1
    k = int(ln.argmax())
    return int(ln[k]), int(bounds[k] + 1)


def analyse(path):
    raw = path.read_bytes()
    n = len(raw)
    try:
        hdr, so, flag, strs = jbcf.parse(raw)
    except Exception as e:  # noqa
        return (path.name, n, None, str(e)[:40])
    body = hdr[5]
    names = [s for s, _ in strs]
    kw = ("bip", "bone", "pelvis", "spine", "shoulder", "arm", "hand", "leg", "foot", "head",
          "chest", "waist", "thigh", "calf", "finger", "clav", "forearm", "neck", "shou", "tui")
    bones = [s for s in names if any(k in s.lower() for k in kw)]
    nw = n // 4
    w = np.frombuffer(raw[:nw * 4], dtype="<u4")
    fl = float_like(w)
    run, rstart = longest_run_np(fl)
    f = w.astype(np.uint32).view(np.float32) if hasattr(w, "view") else None
    fv = np.frombuffer(raw[:nw * 4], dtype="<f4").astype(np.float64)
    finite = np.isfinite(fv)
    quat = 0
    idmat = 0
    if nw >= 16:
        s4 = fv[:nw - 3] ** 2 + fv[1:nw - 2] ** 2 + fv[2:nw - 1] ** 2 + fv[3:nw] ** 2
        q_ok = (s4 > 0.998) & (s4 < 1.002) & np.all(np.abs(np.stack(
            [fv[:nw - 3], fv[1:nw - 2], fv[2:nw - 1], fv[3:nw]])) <= 1.0, axis=0)
        quat = int(q_ok.sum())
    return {"file": path.name, "size": n, "body": body, "str": len(strs), "bones": len(bones),
            "flag": flag, "so": so, "eof_slack": n - (so + 8 + struct.unpack_from("<I", raw, so + 4)[0]),
            "float_words": int(fl.sum()), "float_frac": float(fl.mean()) if nw else 0,
            "max_run": run, "max_run_at": rstart * 4, "quat_hits": quat}


def main():
    files = sorted(TREE.rglob("*.ske"))
    log(f".ske files: {len(files)}")
    res = []
    for p in files:
        try:
            r = analyse(p)
        except Exception as e:  # noqa
            log(f"EXC {p.name}: {type(e).__name__}: {e}")
            continue
        if isinstance(r, tuple):
            log(f"PARSE-FAIL {r}")
            continue
        res.append(r)
    log(f"analysed {len(res)}")
    st = Counter()
    for r in res:
        st["max_run>=16"] += r["max_run"] >= 16
        st["max_run>=48"] += r["max_run"] >= 48
        st["quat_hits>0"] += r["quat_hits"] > 0
        st["quat_hits>=8"] += r["quat_hits"] >= 8
        st["float_frac>0.5"] += r["float_frac"] > 0.5
        st["eof_slack==0"] += r["eof_slack"] == 0
        st["body>=64*bones"] += r["body"] >= 64 * max(1, r["bones"])
        st["body<=40*bones"] += r["body"] <= 40 * max(1, r["bones"])
    log("=== aggregate ===")
    for k, v in st.most_common():
        log(f"  {k}: {v}/{len(res)}")
    mr = sorted(r["max_run"] for r in res)
    log(f"  max float-like run per file: p50={mr[len(mr)//2]} p90={mr[int(len(mr)*.9)]} max={mr[-1]}")
    ff = sorted(r["float_frac"] for r in res)
    log(f"  float-like word fraction: p50={ff[len(ff)//2]:.4f} p90={ff[int(len(ff)*.9)]:.4f} max={ff[-1]:.4f}")
    q = sorted(r["quat_hits"] for r in res)
    log(f"  quaternion-like windows per file: p50={q[len(q)//2]} max={q[-1]}")
    bs = sorted((r["body"] / max(1, r["bones"]), r["file"]) for r in res if r["bones"])
    log(f"  body/bone_like_strings: p10={bs[len(bs)//10][0]:.1f} p50={bs[len(bs)//2][0]:.1f} "
        f"p90={bs[int(len(bs)*.9)][0]:.1f} (a 4x4 f32 matrix = 64B)")
    ss = sorted((r["body"] / max(1, r["str"]), r["file"]) for r in res)
    log(f"  body/string: p50={ss[len(ss)//2][0]:.1f} (node-tree records are ~8-24B)")
    log("\n  top files by float fraction:")
    for r in sorted(res, key=lambda x: -x["float_frac"])[:10]:
        log(f"    {r['file']} size={r['size']} body={r['body']} str={r['str']} bones={r['bones']} "
            f"float_frac={r['float_frac']:.3f} max_run={r['max_run']}@0x{r['max_run_at']:X} quat={r['quat_hits']}")
    log("\n  biggest bodies:")
    for r in sorted(res, key=lambda x: -x["body"])[:10]:
        log(f"    {r['file']} size={r['size']} body={r['body']} str={r['str']} bones={r['bones']} "
            f"max_run={r['max_run']} quat={r['quat_hits']} eof_slack={r['eof_slack']}")

    # where is the longest float-like run? dump context for 3 files
    log("\n=== longest float-like run, byte context ===")
    for r in sorted(res, key=lambda x: -x["max_run"])[:3]:
        p = next(p for p in files if p.name == r["file"])
        raw = p.read_bytes()
        off = r["max_run_at"]
        seg = raw[off:off + min(128, len(raw) - off)]
        log(f"  {r['file']} run={r['max_run']} at 0x{off:X} (body=0x18..0x{r['so']:X})")
        log("    hex: " + seg.hex(" "))
        try:
            v = struct.unpack("<%df" % (len(seg) // 4), seg)
            log("    f32: " + ", ".join(f"{x:.5g}" for x in v))
        except struct.error:
            pass

    # extension census: where could keyframes live?
    log("\n=== extension census under tree (top 25) ===")
    ext = Counter()
    for p in TREE.rglob("*"):
        if p.is_file():
            ext[p.suffix.lower() or "(none)"] += 1
    for k, v in ext.most_common(25):
        log(f"  {k:10} {v}")
    log(f"  distinct extensions: {len(ext)}")

    # a sibling listing for a rigged character
    log("\n=== sibling files of a skinned mesh ===")
    for rel in [r"data\source\player\w1351_nan", r"data\source\npc\model\w1351_model_kongmo_001"]:
        d = TREE / rel
        if d.exists():
            kids = sorted(x.name for x in d.iterdir())
            log(f"  {rel}: {len(kids)} entries: {kids[:40]}")
    OUT.write_text("\n".join(L), encoding="utf-8")
    print("wrote", OUT, len(L))


if __name__ == "__main__":
    main()
