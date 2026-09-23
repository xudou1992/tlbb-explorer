"""Probe 1: multi-submesh index layout hunt.

For failing samples (sm>=2) dump:
  * the whole 0x8C..0x118 header tail as u32/u16 arrays (looking for a submesh table)
  * every self-consistent index block candidate at/after the position stream end
"""
import struct
import sys
from pathlib import Path

TREE = Path(r"D:\TLGL\.scratch\out\tree")
OUT = Path(r"D:\TLGL\.scratch\agent_fmt_probe1.txt")

FILES = [
    r"data\effect\effectmodel\w1351_model_emiter_lf002.mesh",
    r"mobile_maps_source\w1351_st_fwzhongxing_001.mesh",
    r"data\effect\effectmodel\test_jianzhen.mesh",
]


def u32(b, o):
    return struct.unpack_from("<I", b, o)[0] if o + 4 <= len(b) else None


def head_dump(name, raw, L):
    L([])
    L([f"### {name}  size={len(raw)}"])
    vc, fc, sm = struct.unpack_from("<3I", raw, 0x8C)
    L([f"vc={vc} fc={fc} sm={sm} ver={u32(raw,0x48)} tag={raw[0x40:0x44]!r} banner={raw[:8]==b'Copyright '}"])
    L([f"expect single-block size = 0x118 + vc*12 + vc*20 + 4 + fc*6 = {0x118+vc*32+4+fc*6}"])
    L([f"pos_end=0x{0x118+vc*12:X}  static_idx=0x{0x118+vc*32:X}  EOF-hint"])
    # header tail 0x8C..0x118 as u32 / u16
    words = struct.unpack_from("<27I", raw, 0x8C)
    L(["hdr u32 @0x8C.. : " + ", ".join(f"[{0x8C+4*i:#x}]{w}" for i, w in enumerate(words))])
    L(["hdr nonzero u16 @0x98..: " + ", ".join(
        f"[{0x98+2*i:#x}]{w}" for i, w in enumerate(struct.unpack_from("<64H", raw, 0x98)) if w)])
    L(["tail 64B of file: " + " ".join(f"{b:02x}" for b in raw[-64:])])
    return vc, fc, sm


def candidates(raw, vc, fc, lo, L):
    """all p >= lo with u32(p)=n, 0<n<=fc, p+4+6n<=len, all 3n u16 < vc"""
    out = []
    n = len(raw)
    for p in range(lo, n - 3):
        v = u32(raw, p)
        if v is None or v == 0 or v > fc:
            continue
        end = p + 4 + v * 6
        if end > n:
            continue
        seg = raw[p + 4:end]
        idx = struct.unpack_from("<%dH" % (v * 3), seg, 0)
        if max(idx) < vc:
            out.append((p, v, max(idx)))
    L([f"candidates >=0x{lo:X}: {len(out)}"])
    for p, v, mx in out[:80]:
        L([f"  off=0x{p:X} ({p}) n={v} p%8={p%8} gap_from_pos_end=0x{p-lo:X} ({p-lo}) max_idx={mx} end=0x{p+4+v*6:X}"])
    return out


def main():
    lines = []

    def L(row):
        lines.extend(row)

    extra = []
    for f in TREE.rglob("*.mesh"):
        raw = f.read_bytes()
        if len(raw) < 0x118:
            continue
        try:
            vc, fc, sm = struct.unpack_from("<3I", raw, 0x8C)
        except struct.error:
            continue
        if sm and 2 <= sm <= 9 and len(raw) < 60000 and vc and vc < 3000:
            # quick sanity: is it a failure under the old single-block rule?
            extra.append(f)
            if len(extra) >= 6:
                break

    targets = [TREE / p for p in FILES] + extra
    for f in targets:
        if not f.exists():
            L([f"!! missing {f}"])
            continue
        raw = f.read_bytes()
        vc, fc, sm = head_dump(str(f.relative_to(TREE)), raw, L)
        pos_end = 0x118 + vc * 12
        cands = candidates(raw, vc, fc, pos_end, L)
        # greedy consume: can we tile [u32][6n] blocks from consecutive candidates
        L([f"sm={sm}: sum of all candidate counts = {sum(v for _,v,_ in cands)} vs fc={fc}"])

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print("wrote", OUT, len(lines), "lines")


if __name__ == "__main__":
    main()
