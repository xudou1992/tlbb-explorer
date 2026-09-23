"""Decode the trailing node/bone table of .mesh (names + 4x4 matrices?) and
cross-check against the sibling .ske string table.  Also re-test the A=44/45
middle variants for a per-vertex weight array (u8 / u16 / f32, any normalisation).
"""
import struct
import sys
from pathlib import Path

import numpy as np

import agent_fmt_lib as lib

sys.path.insert(0, r"D:\TLGL\.scratch")
import jbcf  # noqa: E402

TREE = Path(r"D:\TLGL\.scratch\out\tree")
OUT = open(r"D:\TLGL\.scratch\agent_fmt_nodes.txt", "w", encoding="utf-8")


def w(*a):
    print(*a, file=OUT)


CASES = [
    r"data\source\npc\quest\w1351_new_npc_muwanqing\w1351_new_npc_muwanqing.mesh",
    r"data\source\npc\model\w1351_model_kongmo_001\w1351_model_kongmo_001.mesh",
    r"data\effect\effectmodel\w1351_jianmo_v1.mesh",
    r"data\source\npc\quest\w1351_boss_wangyuyan\w1351_boss_wangyuyan.mesh",
]


def rows(buf, base, n=14):
    for i in range(0, min(len(buf), n * 32), 32):
        seg = buf[i:i + 32]
        u = struct.unpack("<8I", seg + b"\0" * (32 - len(seg)))
        f = struct.unpack("<8f", seg[:32])
        w(f"   {base + i:#08x} " + " ".join(f"{b:02x}" for b in seg) +
          "  |" + "".join(chr(b) if 32 <= b < 127 else "." for b in seg) + "|")
        w(f"            u32 {list(u)}")


def try_table(buf):
    """parse [name[32]][mat[64]] style records, report stride candidates"""
    for S in (32, 64, 96, 128):
        n = len(buf) // S
        if n < 2:
            continue
        ok = 0
        for i in range(min(n, 40)):
            seg = buf[i * S:(i + 1) * S]
            nm = seg.split(b"\0")[0]
            printable = all(32 <= c < 127 for c in nm) and 3 <= len(nm) <= 31
            mat = seg[len(nm):len(nm) + 64] if len(seg) >= len(nm) + 64 else None
            ident = False
            fl = None
            if mat is not None and len(mat) >= 64:
                q = np.frombuffer(mat[:64], dtype="<f4").reshape(4, 4)
                if np.isfinite(q).all() and np.abs(q).max() < 1e6:
                    fl = q.ravel()
                ident = bool(np.allclose(fl @ fl, 4.0, atol=1e-3) or
                             np.allclose(fl[[0, 5, 10, 15]], [1, 1, 1, 1], atol=1e-6))
            if printable and (ident or S >= 96):
                ok += 1
        w(f"    stride={S}: {ok}/{min(n,40)} records look like name+matrix")


def main():
    for rel in CASES:
        f = TREE / rel
        raw = f.read_bytes()
        vc, fc, sm = struct.unpack_from("<3I", raw, 0x8C)
        sm = int(sm or 1)
        pe = 0x118 + vc * 12
        p, counts = lib.locate(raw, vc, fc, sm, pe)
        end = p + 4 * sm + 6 * fc
        buf = raw[end:]
        w("=" * 110)
        w(f"{rel.split(chr(92))[-1]} size={len(raw)} vc={vc} fc={fc} sm={sm} middle={p-pe} tail={len(buf)}"
          f" tail%96={len(buf)%96} tail%32={len(buf)%32} tail%64={len(buf)%64}")
        rows(buf, end, 6)
        try_table(buf)
        names = []
        i = 0
        while i < len(buf):
            if 32 <= buf[i] < 127:
                j = i
                while j < len(buf) and 32 <= buf[j] < 127:
                    j += 1
                if j - i >= 3:
                    names.append((i, buf[i:j].decode("latin1")))
                i = j
            else:
                i += 1
        w(f"    ascii runs: {len(names)} first: {names[:14]}")
        offs = [o for o, _ in names[:60]]
        d = np.diff(offs) if len(offs) > 2 else []
        w(f"    name offsets: first={offs[:8]} deltas={list(d)[:20]}")
        # matrices: scan for orthonormal 4x4 f32 blocks
        found = []
        for k in range(0, len(buf) - 64, 4):
            q = np.frombuffer(buf[k:k + 64], dtype="<f4").reshape(4, 4)
            if not np.isfinite(q).all():
                continue
            if np.abs(q).max() > 1e5:
                continue
            r = q[:3, :3]
            if np.allclose(r @ r.T, np.eye(3), atol=5e-3) and abs(np.linalg.det(r) - 1) < 5e-3:
                found.append((k, q))
        w(f"    orthonormal-3x3 64B windows: {len(found)}")
        for k, q in found[:4]:
            w(f"      @0x{end + k:X}: " + " | ".join(",".join(f"{x:.4g}" for x in row) for row in q))
        sib = f.with_suffix(".ske")
        if sib.exists():
            try:
                _, _, _, strs = jbcf.parse(sib.read_bytes())
                sn = {s for s, _ in strs}
                hit = sum(1 for _, nm in names if nm in sn)
                w(f"    sibling {sib.name}: strings={len(strs)}  names found in ske strtab: {hit}/{len(names)}")
                w(f"      ske sample: {sorted(sn)[:12]}")
            except Exception as e:  # noqa
                w(f"    sibling ske parse failed: {e}")
        else:
            w("    no sibling .ske")

    # A=44/45 middle variants: hunt for a weight array
    w("\n" + "=" * 110)
    w("=== middle variants with A>=32 (candidate skin streams) ===")
    n = 0
    for f in sorted(TREE.rglob("*.mesh")):
        raw = f.read_bytes()
        if len(raw) < 0x118:
            continue
        try:
            vc, fc, sm = struct.unpack_from("<3I", raw, 0x8C)
        except struct.error:
            continue
        sm = int(sm or 1)
        if not vc or vc < 200 or sm > 64 or fc > 4_000_000:
            continue
        pe = 0x118 + vc * 12
        r = lib.locate(raw, vc, fc, sm, pe)
        if not r:
            continue
        p = r[0]
        mid = p - pe
        if mid % max(1, vc) == 0:
            A = mid // vc
        else:
            A = (mid - 2 * fc) / vc if vc else 0
        if not (32 <= A <= 60):
            continue
        n += 1
        if n > 6:
            break
        w(f"\n  {f.relative_to(TREE)} vc={vc} fc={fc} sm={sm} middle={mid} A={A:.3f} tail={len(raw)-(p+4*sm+6*fc)}")
        buf = raw[pe + 12 * vc:p]  # everything after normals
        m = len(buf) // vc
        for S in (8, 12, 16, 20, 24, 28, 32, 44):
            k = len(buf) // S
            if k < vc // 2:
                continue
            a = np.frombuffer(buf[:k * S], dtype=np.uint8).reshape(k, S)
            u32 = a.copy().view(np.float32).reshape(k, S // 4)
            best = (0, None, None)
            for j in range(0, S // 4 - 3):
                q = u32[:, j:j + 4]
                ok = np.all(np.isfinite(q) & (q >= -0.001) & (q <= 1.001), axis=1)
                for tgt, tol in ((1.0, 0.02),):
                    s1 = np.abs(np.nansum(q, axis=1) - tgt) < tol
                    frac = float((ok & s1).mean())
                    if frac > best[0]:
                        best = (frac, j * 4, tgt)
            u16 = a.copy().view(np.uint16).reshape(k, S // 2)
            ub = a.astype(np.int64)
            b16 = []
            for j in range(0, S // 2 - 3):
                q = u16[:, j:j + 4].astype(np.int64)
                for tgt in (65535, 1000, 100):
                    fr = float((np.abs(q.sum(axis=1) - tgt) <= 2).mean())
                    b16.append((fr, j * 2, tgt))
            b8 = []
            for j in range(0, S - 3):
                q = ub[:, j:j + 4]
                for tgt in (255, 100, 1):
                    b8.append((float((np.abs(q.sum(axis=1) - tgt) <= 1).mean()), j, tgt))
            w(f"    stride{S} nrec={k}: f32-sum1 best={max(best[0],0):.3f}@{best[1]}  "
              f"u16-sum best={max([x[0] for x in b16], default=0):.3f}  u8-sum best={max([x[0] for x in b8], default=0):.3f}")
        w("    head96: " + buf[:96].hex(" "))
        w("    mid96 (after 20*vc): " + buf[20 * vc:20 * vc + 96].hex(" ") if len(buf) > 20 * vc + 96 else "")
        q = np.frombuffer(buf[:12 * min(vc, 400)], dtype="<f4")
        w(f"    after-normal f32 range: min={q.min():.4g} max={q.max():.4g}")
    OUT.close()
    print("done")


if __name__ == "__main__":
    main()
