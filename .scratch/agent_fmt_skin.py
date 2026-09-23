"""Task B1 decisive test: bone indices + weights?

For each located mesh we score *every* plausible skin record layout
    weights: 4 x f32   (in [0,1], sum ~= 1)     |  4 x u8 (sum == 255 / == 100)
    indices: 4 x u16 or 4 x u8 (max < 1024)
against both the leftover middle region and the trailing region, report the best
scoring (stride, field offsets) per file, and cross-check the implied bone count
against the sibling .ske string table.
"""
import struct
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

import agent_fmt_lib as lib

sys.path.insert(0, r"D:\TLGL\.scratch")
import jbcf  # noqa: E402

TREE = Path(r"D:\TLGL\.scratch\out\tree")
OUT = Path(r"D:\TLGL\.scratch\agent_fmt_skin.txt")
L = []
BONEKW = ("bip", "bone", "pelvis", "spine", "shoulder", "arm", "hand", "leg", "foot", "head",
          "chest", "waist", "thigh", "calf", "finger", "clav", "forearm", "neck", "shou", "tui")


def log(*a):
    L.append(" ".join(str(x) for x in a))


def ske_bones(mesh_path):
    for ext in (".ske", ".SKE"):
        cand = mesh_path.with_suffix(ext)
        if not cand.exists():
            cand = mesh_path.parent / (mesh_path.stem + ".ske")
            if not cand.exists():
                continue
        try:
            raw = cand.read_bytes()
            _, _, _, strs = jbcf.parse(raw)
        except Exception:  # noqa
            continue
        names = [s for s, _ in strs]
        b = [s for s in names if any(k in s.lower() for k in BONEKW)]
        return len(names), len(b)
    return None


def score_region(buf, tag, maxrec=40000):
    """returns list of dicts describing plausible skin layouts"""
    out = []
    if len(buf) < 64:
        return out
    for S in (12, 16, 20, 22, 24, 28, 32, 36, 40, 44, 48):
        n = min(len(buf) // S, maxrec)
        if n < 64:
            continue
        a = np.frombuffer(buf[:n * S], dtype=np.uint8).reshape(n, S)
        nw = S // 4
        if nw >= 4:
            u = a[:, :nw * 4].copy().view(np.float32).reshape(n, nw)
            for k in range(0, nw - 3):
                w = u[:, k:k + 4]
                with np.errstate(invalid="ignore"):
                    inrange = np.all(np.isfinite(w) & (w >= 0.0) & (w <= 1.0), axis=1)
                    s1 = np.abs(w.sum(axis=1) - 1.0) < 0.02
                    hit = float((inrange & s1).mean())
                if hit > 0.5:
                    # companion index field
                    desc = {"tag": tag, "stride": S, "kind": "4xf32", "off": k * 4, "score": hit,
                            "n": n, "wmax": float(np.nanmax(w)), "bone_max": None}
                    for (ik, it) in ((0, "u8"), (1, "u16")):
                        if it == "u8" and k >= 4:
                            ib = a[:, k - 4:k].astype(np.int64)
                            bm = int(ib.max())
                            if bm < 1024:
                                desc["idx_kind"] = f"u8@-{4}"
                                desc["bone_max"] = bm
                        if it == "u16" and k >= 2:
                            iu = a[:, (k - 2) * 4:k * 4].copy().view(np.uint16).reshape(n, 4)
                            bm = int(iu.max())
                            if bm < 1024:
                                desc["idx_kind"] = f"u16@-{8}"
                                desc["bone_max"] = bm
                    out.append(desc)
        nb = S
        for k in range(0, nb - 3):
            b = a[:, k:k + 4].astype(np.int64)
            tot = b.sum(axis=1)
            for target in (255, 100):
                hit = float((np.abs(tot - target) <= 2).mean())
                if hit > 0.6:
                    out.append({"tag": tag, "stride": S, "kind": f"4xu8(sum={target})",
                                "off": k, "score": hit, "n": n})
    return out


def main():
    t0 = time.time()
    files = sorted(TREE.rglob("*.mesh"))
    st = Counter()
    shown = 0
    shown_f32 = 0
    for f in files:
        if time.time() - t0 > 230:
            log("!! budget")
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
        if not vc or vc > 8_000_000 or fc > 8_000_000 or sm > 64:
            continue
        pos_end = 0x118 + vc * 12
        r = lib.locate(raw, vc, fc, sm, pos_end)
        if r is None:
            st["not_located"] += 1
            continue
        p, counts = r
        end = p + 4 * sm + 6 * fc
        middle = p - pos_end
        tail = len(raw) - end
        st["located"] += 1
        mid_extra = middle - (20 * vc + 2 * fc)
        cand_mid = middle - 20 * vc
        regions = []
        if tail >= 12 * vc and tail > 0:
            regions.append(("tail", raw[end:], tail))
        if cand_mid >= 12 * vc:
            regions.append(("mid_extra", raw[pos_end + 20 * vc:p], cand_mid))
        if not regions:
            st["no_candidate_region"] += 1
            continue
        best = []
        for tag, buf, size in regions:
            best += score_region(buf[:min(len(buf), 1200000)], tag)
        good = [b for b in best if b["kind"] == "4xf32"]
        u8good = [b for b in best if b["kind"].startswith("4xu8")]
        if good:
            st["has_4xf32_weight_layout"] += 1
            if len(good) and shown_f32 < 12:
                shown_f32 += 1
                g = max(good, key=lambda x: x["score"])
                log(f"\n### {f.relative_to(TREE)} vc={vc} fc={fc} sm={sm} middle={middle} tail={tail}")
                log(f"    4xf32 weight layout: stride={g['stride']} w_off={g['off']} "
                    f"score={g['score']:.3f} n={g['n']} idx={g.get('idx_kind')} bone_max={g.get('bone_max')}")
        if u8good:
            st["has_4xu8_weight_layout"] += 1
            if shown < 14:
                shown += 1
                g = max(u8good, key=lambda x: x["score"])
                log(f"\n@@@ {f.relative_to(TREE)} vc={vc} fc={fc} sm={sm} middle={middle} "
                    f"mid_extra={mid_extra} tail={tail}")
                log(f"    4xu8 layout in {g['tag']}: stride={g['stride']} off={g['off']} "
                    f"score={g['score']:.3f} n={g['n']}")
                buf = dict((t, b) for t, b, _ in regions)[g["tag"]]
                S = g["stride"]
                for i in (0, 1, 2, max(0, len(buf) // S - 2), len(buf) // S - 2):
                    if i * S + S <= len(buf):
                        log(f"      rec{i}: " + buf[i * S:(i + 1) * S].hex(" "))
                sk = ske_bones(f)
                log(f"      sibling .ske (strings, bone-like): {sk}")
        if not good and not u8good:
            st["no_skin_layout_in_candidate"] += 1
            if shown < 14 and st["no_skin_layout_in_candidate"] <= 6:
                pass
    log("\n=== aggregate ===")
    for k, v in st.most_common():
        log(f"  {k:28} {v}")
    OUT.write_text("\n".join(L), encoding="utf-8")
    print("wrote", OUT, "elapsed", round(time.time() - t0, 1))


if __name__ == "__main__":
    main()
