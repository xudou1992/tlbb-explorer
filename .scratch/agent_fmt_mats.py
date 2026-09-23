"""Decisive check: are there 4x4 bone/node matrices in the .mesh tail?"""
import struct
import sys
from pathlib import Path

import numpy as np

import agent_fmt_lib as lib

TREE = Path(r"D:\TLGL\.scratch\out\tree")
OUT = open(r"D:\TLGL\.scratch\agent_fmt_mats.txt", "w", encoding="utf-8")
CASES = [
    r"data\source\npc\quest\w1351_new_npc_muwanqing\w1351_new_npc_muwanqing.mesh",
    r"data\source\npc\quest\w1351_boss_wangyuyan\w1351_boss_wangyuyan.mesh",
    r"data\source\npc\model\w1351_model_kongmo_001\w1351_model_kongmo_001.mesh",
    r"data\effect\effectmodel\w1351_jianmo_v1.mesh",
    r"data\source\player\w1351_nv\w1351_nv.mesh",
]


def w(*a):
    print(*a, file=OUT)


def mats(buf, base):
    hits = []
    for k in range(0, len(buf) - 64, 4):
        q = np.frombuffer(buf[k:k + 64], dtype="<f4")
        if not np.isfinite(q).all() or np.abs(q).max() > 1e6:
            continue
        r = q[:12].reshape(3, 4)
        rr = r[:, :3]
        if np.allclose(rr @ rr.T, np.eye(3), atol=8e-3) and abs(float(np.linalg.det(rr)) - 1) < 8e-3:
            hits.append((base + k, q))
    return hits


for rel in CASES:
    f = TREE / rel
    if not f.exists():
        f2 = next(iter(TREE.rglob(f.name)), None)
        if f2 is None:
            w(f"missing {rel}")
            continue
        f = f2
    raw = f.read_bytes()
    vc, fc, sm = struct.unpack_from("<3I", raw, 0x8C)
    sm = int(sm or 1)
    pe = 0x118 + vc * 12
    got = lib.locate(raw, vc, fc, sm, pe)
    if not got:
        w(f"{f.name}: locate failed")
        continue
    p, counts = got
    end = p + 4 * sm + 6 * fc
    tail = raw[end:]
    w("=" * 100)
    w(f"{f.relative_to(TREE)} size={len(raw)} vc={vc} fc={fc} sm={sm} p=0x{p:X} counts={list(counts)} "
      f"middle={p-pe} tail={len(tail)}")
    h = mats(tail, end)
    w(f"  orthonormal 3x3 (4x4 f32) windows in TAIL: {len(h)}")
    for off, q in h[:6]:
        w(f"    @0x{off:X}: " + " | ".join(",".join(f"{x:.4g}" for x in q[i * 4:i * 4 + 4]) for i in range(4)))
    hn = mats(raw[pe:p], pe)
    w(f"  orthonormal windows in MIDDLE: {len(hn)}")
    # 32-byte name records in tail
    n32 = 0
    names = []
    for i in range(0, len(tail) - 32, 32):
        seg = tail[i:i + 32]
        a = struct.unpack_from("<2I", seg)
        nm = seg[8:].split(b"\0")[0]
        if nm and all(32 <= c < 127 for c in nm) and a[0] in (0, 0xFFFFFFFF) or (nm and a[0] < 4096):
            pass
        if nm and all(32 <= c < 127 for c in nm) and len(nm) >= 3:
            n32 += 1
            names.append((end + i, nm.decode("latin1"), a[0], a[1]))
    w(f"  32B-aligned name records in tail: {n32}  first: {names[:8]}")
    w(f"  tail last 96 bytes: {tail[-96:].hex(' ')}")
    q = np.frombuffer(tail[-96:], dtype="<f4")
    w(f"  tail last 96 as f32: " + ", ".join(f"{x:.5g}" for x in q))
    sib = f.with_suffix(".ske")
    if sib.exists():
        sys.path.insert(0, r"D:\TLGL\.scratch")
        import jbcf
        try:
            _, _, _, st = jbcf.parse(sib.read_bytes())
            sn = {s for s, _ in st}
            hit = sum(1 for _, nm, _, _ in names if nm in sn)
            w(f"  sibling {sib.name}: {len(st)} strings; tail names present in .ske strtab: {hit}/{len(names)}")
        except Exception as e:  # noqa
            w(f"  sibling ske parse err {e}")
    else:
        w("  no sibling .ske")
OUT.close()
print("done")
