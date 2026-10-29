"""只读取证：把 5 份「声明骨却读不出记录」的 .mesh 的尾部记录区逐字节解码。
产物全部写到 D:/TLGL/.scratch/dyn/grammar5/。
"""
import struct, re, sys, os

ROOT = "D:/TLGL"
OUT = os.path.join(ROOT, ".scratch/dyn/grammar5")

FIVE = {
    "mj_nan_stone_h01": f"{ROOT}/.scratch/out/tree/data/source/npc/model/w1351_model_mj_nan_stone_h01/w1351_model_mj_nan_stone_h01.mesh",
    "bell_h002":        f"{ROOT}/.scratch/out/tree/data/source/npc/model/w1351_model_bell_h002/w1351_model_bell_h002.mesh",
    "glass_ani_lf001":  f"{ROOT}/.scratch/out/tree/data/source/npc/model/w1351_model_glass_ani_lf001/w1351_model_glass_ani_lf001.mesh",
    "fazhen_ani_lf001": f"{ROOT}/.scratch/out/tree/data/source/npc/model/w1351_model_fazhen_ani_lf001/w1351_model_fazhen_ani_lf001.mesh",
    "ymg01_stone01":    f"{ROOT}/.scratch/out/tree/data/source/npc/model/w1351_model_ymg01_stone01/w1351_model_ymg01_stone01.mesh",
}

NAME_RE = re.compile(rb"[A-Za-z0-9_.\-]{3,40}")


def u32(raw, at):
    return struct.unpack_from("<I", raw, at)[0] if at + 4 <= len(raw) else None


def f32(raw, at):
    return struct.unpack_from("<f", raw, at)[0] if at + 4 <= len(raw) else None


def head(raw):
    return dict(size=len(raw), vc=u32(raw, 0x8C), fc=u32(raw, 0x90), sm=u32(raw, 0x94),
                bones=u32(raw, 0x110))


def bbox(raw, vc):
    """位置流在 0x118，vc*3 个 f32（口径见 parse_mesh）。"""
    lo = [float("inf")] * 3
    hi = [float("-inf")] * 3
    bad = 0
    for i in range(vc):
        for k in range(3):
            v = f32(raw, 0x118 + (i * 3 + k) * 4)
            if v is None or not (v == v) or abs(v) > 1e9:
                bad += 1
                continue
            lo[k] = min(lo[k], v)
            hi[k] = max(hi[k], v)
    return lo, hi, bad


def name_hits(raw, pat=NAME_RE, lo=0, hi=None):
    hi = len(raw) if hi is None else hi
    return [(m.start(), m.group().decode("ascii", "replace")) for m in pat.finditer(raw, lo, hi)]


def fmt_float(x, w=13, p=6):
    if x is None:
        return " " * w
    if x != x:
        return " " * (w - 3) + "nan"
    return f"{x:>{w}.{p}g}"


def dump_region(raw, at, nfloats, label, out):
    A = out.append
    A(f"--- {label} @ {hex(at)} ---")
    rows = []
    for i in range(nfloats):
        o = at + i * 4
        v = f32(raw, o)
        u = u32(raw, o)
        rows.append((i, o, v, u))
    for chunk in range(0, nfloats, 4):
        parts = []
        for i in range(chunk, min(chunk + 4, nfloats)):
            o, v, u = rows[i][1], rows[i][2], rows[i][3]
            parts.append(f"[{i:2d}]@{o:6x} f={fmt_float(v,12,6)} u={u}")
        A("  " + " | ".join(parts))
    return rows


def main():
    lines = []
    out = lines.append
    for key, path in FIVE.items():
        raw = open(path, "rb").read()
        h = head(raw)
        out("=" * 100)
        out(f"### {key}  size={h['size']} vc={h['vc']} fc={h['fc']} sm={h['sm']} 声明骨={h['bones']}")
        lo, hi, bad = bbox(raw, h["vc"])
        diag = [hi[k] - lo[k] for k in range(3)] if all(x != float("inf") for x in lo) else None
        out(f"顶点包围盒 min={[round(v,3) for v in lo]} max={[round(v,3) for v in hi]} "
            f"尺寸={[round(d,3) for d in diag]} 坏值={bad}")
        # 找尾部 bone 名（boneNNN 形态）
        hits = name_hits(raw)
        bnames = [(o, n) for o, n in hits if re.fullmatch(r"[Bb]one\d+", n)]
        out(f"全文件 ASCII 段 {len(hits)} 个；形如 boneNNN 的 {len(bnames)} 个")
        if bnames:
            offs = [o for o, _ in bnames]
            deltas = {}
            for a, b in zip(offs, offs[1:]):
                deltas[b - a] = deltas.get(b - a, 0) + 1
            out(f"  bone 名偏移差分布 top8: {sorted(deltas.items(), key=lambda x:-x[1])[:8]}")
            out(f"  前 6 个: {[(hex(o), n) for o, n in bnames[:6]]}")
            out(f"  最后 4 个: {[(hex(o), n) for o, n in bnames[-4:]]}")
            first = offs[0]
            dump_region(raw, first, 68, "首条 bone 名起 68 个 4 字节槽", lines)
        else:
            tail = h["size"] - 4096
            dump_region(raw, max(0, tail), 64, "尾部 4KB 起", lines)
        out("")
    open(os.path.join(OUT, "dump1_records.txt"), "w", encoding="utf-8").write("\n".join(lines))
    print("WROTE dump1_records.txt", len(lines), "lines")


if __name__ == "__main__":
    main()
