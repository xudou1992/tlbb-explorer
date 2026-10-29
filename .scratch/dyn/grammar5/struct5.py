"""结构核验：5 份异常 .mesh 的骨架记录布局逐字段验证 + 矩阵基向量长度 / 平移量级 / 记录前的缩放三元组。
只读。产物写到 grammar5/。
"""
import struct, re, os, math, json

ROOT = "D:/TLGL"
OUT = os.path.join(ROOT, ".scratch/dyn/grammar5")
MODEL = f"{ROOT}/.scratch/out/tree/data/source/npc/model"

FIVE = ["w1351_model_mj_nan_stone_h01", "w1351_model_bell_h002", "w1351_model_glass_ani_lf001",
        "w1351_model_fazhen_ani_lf001", "w1351_model_ymg01_stone01"]


def f32(raw, at):
    return struct.unpack_from("<f", raw, at)[0]


def u32(raw, at):
    return struct.unpack_from("<I", raw, at)[0]


def norm(v):
    return math.sqrt(sum(x * x for x in v))


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def name_at(raw, at, width=32):
    b = raw[at:at + width]
    z = b.find(b"\0")
    n = len(b) if z < 0 else z
    s = b[:n]
    if n < 3:
        return None
    if not re.fullmatch(rb"[A-Za-z0-9_.\-]+", s):
        return None
    if any(c != 0 for c in b[n:]):
        return None
    return s.decode("ascii")


def analyze(path, key, L):
    raw = open(path, "rb").read()
    vc, fc, bones = u32(raw, 0x8C), u32(raw, 0x90), u32(raw, 0x110)
    L.append("=" * 108)
    L.append(f"### {key}  size={len(raw)}  vc={vc} fc={fc} 0x110声明骨={bones}")
    # 顶点包围盒
    lo = [1e30] * 3; hi = [-1e30] * 3
    for i in range(min(vc, 200000)):
        p = struct.unpack_from("<3f", raw, 0x118 + i * 12)
        for k in range(3):
            lo[k] = min(lo[k], p[k]); hi[k] = max(hi[k], p[k])
    ext = [hi[k] - lo[k] for k in range(3)]
    maxabs = max(max(abs(x) for x in hi), max(abs(x) for x in lo))
    L.append(f"  bbox min={[round(v,4) for v in lo]} max={[round(v,4) for v in hi]}")
    L.append(f"  bbox 尺寸={[round(v,4) for v in ext]}  最大|坐标|={maxabs:.4f}")

    # 逐个 bone 名（boneNNN 或任意 char[32] 名）：用「名字双写 + 后面 64 字节 4 组 (0,xyz)」定位
    recs = []
    pat = re.compile(rb"[A-Za-z0-9_.\-]{3,31}")
    for m in pat.finditer(raw, 0x118, len(raw)):
        at = m.start()
        if at < 4:
            continue
        nm = name_at(raw, at)
        if nm is None:
            continue
        nm2 = name_at(raw, at + 32)
        if nm2 != nm:      # 双写名
            continue
        mb = at + 64
        if mb + 64 > len(raw):
            continue
        groups = []
        ok = True
        for g in range(4):
            w = f32(raw, mb + g * 16)
            v = (f32(raw, mb + g * 16 + 4), f32(raw, mb + g * 16 + 8), f32(raw, mb + g * 16 + 12))
            if abs(w) > 1e-3:
                ok = False
            groups.append((w, v))
        if not ok:
            continue
        lens = [norm(v) for _, v in groups]
        if min(lens) <= 1e-6:
            continue
        recs.append((at, nm, groups, lens))

    L.append(f"  结构匹配记录数 = {len(recs)}（判据：名 char[32] + 同名 char[32] + 4 组 (w≈0, 三元组)）")
    if not recs:
        return None
    offs = [r[0] for r in recs]
    L.append(f"  首 5 个: {[(hex(o), n) for o, n, _, _ in recs[:5]]}")
    # 相邻记录间隔
    d = {}
    for a, b in zip(offs, offs[1:]):
        d[b - a] = d.get(b - a, 0) + 1
    L.append(f"  相邻间隔分布 top6: {sorted(d.items(), key=lambda x: -x[1])[:6]}")
    # 基向量长度（前三组）与平移（第四组）
    basel, tranl = [], []
    orth_bad = 0
    for _, _, groups, lens in recs:
        bl = lens[:3]; tl = lens[3]
        basel += bl; tranl.append(tl)
        vs = [v for _, v in groups[:3]]
        for i in range(3):
            for j in range(i + 1, 3):
                c = abs(dot(vs[i], vs[j])) / (lens[i] * lens[j] if lens[i] * lens[j] else 1)
                if c > 0.02:
                    orth_bad += 1
    basel.sort()
    tranl.sort()
    q = lambda a, p: a[min(int(len(a) * p), len(a) - 1)]
    L.append(f"  基向量长度: min={basel[0]:.4f} p10={q(basel,.10):.4f} 中位={q(basel,.5):.4f} "
             f"p90={q(basel,.9):.4f} max={basel[-1]:.4f}")
    L.append(f"  平移长度:   min={tranl[0]:.4f} 中位={q(tranl,.5):.4f} max={tranl[-1]:.4f}")
    L.append(f"  基向量两两不垂直(>2%%cos)计数={orth_bad}")
    # 记录前的 4 浮点（缩放三元组？）
    pre = offs[0] - 16
    if pre >= 0:
        L.append(f"  首记录前 16 字节 @{hex(pre)}: f={[round(f32(raw,pre+4*i),4) for i in range(4)]} "
                 f"u={[u32(raw,pre+4*i) for i in range(4)]}")
        L.append(f"  首记录前 48 字节: f={[round(f32(raw,offs[0]-48+4*i),4) for i in range(12)]}")
    # 首条记录全量解码
    at, nm, groups, lens = recs[0]
    L.append(f"  首记录 @{hex(at)} 名={nm}")
    for g, (w, v) in enumerate(groups):
        L.append(f"    组{g}: w={w:.6g}  三元组=({v[0]:.6f}, {v[1]:.6f}, {v[2]:.6f}) 长度={norm(v):.6f}")
    nxt = offs[1] if len(offs) > 1 else at + 260
    L.append(f"    矩阵尾@{hex(at+128)} 之后到 {hex(nxt)} 逐槽:")
    o = at + 128
    while o + 4 <= nxt:
        fv, uv = f32(raw, o), u32(raw, o)
        if abs(fv) > 1e-12 or uv != 0:
            L.append(f"      +{o-at:4d} @{hex(o)}  f={fv:.7g}  u={uv}  作为骨号? {'<vc' if uv < vc else '>=vc'}")
        o += 4
    return dict(key=key, recs=len(recs), vc=vc, bones=bones, basel=basel, tranl=tranl,
                ext=ext, maxabs=maxabs, offs=offs, raw=raw)


def main():
    L = []
    res = {}
    for k in FIVE:
        p = os.path.join(MODEL, k, k + ".mesh")
        r = analyze(p, k, L)
        if r:
            raw = r.pop("raw")
            res[k] = r
    open(os.path.join(OUT, "struct5.txt"), "w", encoding="utf-8").write("\n".join(L))
    print("WROTE struct5.txt")
    for k, r in res.items():
        bl = r["basel"]
        print(k, "recs", r["recs"], "bones", r["bones"], "median_basel", round(bl[len(bl)//2], 4),
              "maxabs", round(r["maxabs"], 4), "ext", [round(x, 3) for x in r["ext"]])


if __name__ == "__main__":
    main()
