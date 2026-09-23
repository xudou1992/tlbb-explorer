"""Characterise the region between the index blocks and EOF."""
import struct
import sys

import numpy as np

sys.path.insert(0, r"D:\TLGL\.scratch")
import agent_fmt_lib as lib  # noqa: E402

T = "D:\\TLGL\\.scratch\\out\\tree\\"
CASES = [
    r"data\source\npc\quest\w1351_new_npc_muwanqing\w1351_new_npc_muwanqing.mesh",
    r"data\source\npc\quest\w1351_pets_xianglong_b3\w1351_pets_xianglong_b3.mesh",
    r"data\source\npc\model\w1351_model_kongmo_001\w1351_model_kongmo_001.mesh",
    r"data\effect\effectmodel\w1351_jianmo_v1.mesh",
    r"data\effect\effectmodel\test_jianzhen.mesh",
    r"data\source\npc\quest\w1351_boss_wangyuyan\w1351_boss_wangyuyan.mesh",
    r"mobile_maps_source\w1351_bpzd_dashubaoshi_001.mesh",
]
OUT = open(r"D:\TLGL\.scratch\agent_fmt_tailprobe.txt", "w", encoding="utf-8")


def w(*a):
    print(*a, file=OUT)


for rel in CASES:
    raw = open(T + rel, "rb").read()
    vc, fc, sm = struct.unpack_from("<3I", raw, 0x8C)
    sm = int(sm or 1)
    pe = 0x118 + vc * 12
    got = lib.locate(raw, vc, fc, sm, pe)
    w("=" * 100)
    w(rel, "size", len(raw), "vc", vc, "fc", fc, "sm", sm, "p", hex(got[0]),
      "counts", got[1], "middle", got[0] - pe, "mid-20vc", got[0] - pe - 20 * vc,
      "mid-28vc-2fc", got[0] - pe - 28 * vc - 2 * fc)
    p = got[0]
    for reg, (lo, hi) in (("middle", (pe, p)), ("tail", (p + 4 * sm + 6 * fc, len(raw)))):
        buf = raw[lo:hi]
        if not buf:
            w(f"  [{reg}] empty")
            continue
        n = len(buf) // 4
        v = np.frombuffer(buf[:n * 4], dtype="<f4")
        eb = (np.frombuffer(buf[:n * 4], dtype="<u4") >> 23) & 0xFF
        like = float((((eb >= 100) & (eb <= 150))).mean())
        w(f"  [{reg}] off=0x{lo:X} len={len(buf)} len/vc={len(buf)/vc:.3f} "
          f"f32-like={like:.3f}")
        w(f"    head64 : {buf[:64].hex(' ')}")
        w(f"    tail64 : {buf[-64:].hex(' ')}")
        w(f"    f32[0:16]: " + ", ".join(f"{x:.6g}" for x in v[:16]))
        # printable runs
        runs = []
        i = 0
        while i < len(buf):
            if 32 <= buf[i] < 127:
                j = i
                while j < len(buf) and 32 <= buf[j] < 127:
                    j += 1
                if j - i >= 4:
                    runs.append((i, buf[i:j].decode("latin1")))
                i = j
            else:
                i += 1
        w(f"    ascii runs>=4: {len(runs)} -> {runs[:10]}")
        # 24-byte and 20-byte record views: f32 triples/quads
        for S in (20, 24, 28, 32):
            m = min(len(buf) // S, 4000)
            if m < 8:
                continue
            a = np.frombuffer(buf[:m * S], dtype=np.uint8).reshape(m, S)
            u = a.copy().view(np.float32).reshape(m, S // 4)
            best = (0, None)
            for k in range(0, S // 4 - 3):
                q = u[:, k:k + 4]
                ok = np.all(np.isfinite(q) & (q >= 0) & (q <= 1), axis=1)
                s1 = np.abs(np.nansum(q, axis=1) - 1.0) < 0.02
                frac = float((ok & s1).mean())
                if frac > best[0]:
                    best = (frac, k)
            u16 = a.copy().view(np.uint16).reshape(m, S // 2)
            w(f"    stride{S}: best 4xf32 sum1 frac={best[0]:.3f} at field {best[1]}  "
              f"u16 max={int(u16.max())} u16 mean={float(u16.mean()):.1f}")
        # per-vertex f32x3 stream test at several offsets
        for off in (0, 12 * vc, 20 * vc, 8 * vc, 24 * vc, 28 * vc):
            if off + 12 * min(vc, 2000) > len(buf):
                continue
            m = min(vc, 2000)
            q = np.frombuffer(buf[off:off + m * 12], dtype="<f4").reshape(m, 3)
            ln = np.linalg.norm(q, axis=1)
            w(f"    f32x3@+0x{off:X}: unit_frac={float((np.abs(ln - 1) < 0.02).mean()):.3f} "
              f"|v|p50={float(np.median(ln)):.4g} max={float(np.abs(q).max()):.5g}")
OUT.close()
print("done")
