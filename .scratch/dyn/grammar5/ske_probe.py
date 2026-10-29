"""旁证：同目录 .ske / .ani 里有没有同样的 ×100。
做法：在 .ske/.ani 里滑 4 字节步长找「行主序 4x4 仿射」形态（m[15]≈1、三行两两垂直、等比），
统计基向量长度分布；同时数 (100.0,100.0,100.0) 三元组出现次数。只读。"""
import os, struct, math, re

ROOT = "D:/TLGL"
MODEL = f"{ROOT}/.scratch/out/tree/data/source/npc/model"
OUT = f"{ROOT}/.scratch/dyn/grammar5"
FIVE = ["w1351_model_mj_nan_stone_h01", "w1351_model_bell_h002", "w1351_model_glass_ani_lf001",
        "w1351_model_fazhen_ani_lf001", "w1351_model_ymg01_stone01"]
SCALE100 = struct.pack("<3f", 100.0, 100.0, 100.0)


def mats(raw, stride=4):
    """扫出所有像行主序仿射矩阵的位置，返回 [(off, 平均基长, 平移长)]。"""
    out = []
    n = len(raw)
    i = 0
    while i + 64 <= n:
        m = struct.unpack_from("<16f", raw, i)
        if abs(m[15] - 1.0) <= 1e-3 and all(abs(v) < 1e7 and v == v for v in m):
            R = [m[0:3], m[4:7], m[8:11]]
            L = [math.sqrt(sum(x * x for x in v)) for v in R]
            mn, mx = min(L), max(L)
            if mn > 1e-6 and mx / mn <= 1.05:
                o = True
                for a in range(3):
                    for b in range(a + 1, 3):
                        if abs(sum(R[a][k] * R[b][k] for k in range(3))) / (L[a] * L[b]) > 0.03:
                            o = False
                if o:
                    out.append((i, sum(L) / 3.0, math.sqrt(sum(x * x for x in m[12:15]))))
                    i += 64
                    continue
        i += stride
    return out


def main():
    L = []
    for k in FIVE:
        d = os.path.join(MODEL, k)
        L.append("=" * 96)
        L.append(f"### {k}")
        for fn in sorted(os.listdir(d)):
            if not fn.lower().endswith((".ske", ".ani", ".mdl", ".mesh")):
                continue
            p = os.path.join(d, fn)
            if os.path.isdir(p):
                continue
            raw = open(p, "rb").read()
            ms = mats(raw)
            bl = sorted(x[1] for x in ms)
            tl = sorted(x[2] for x in ms)
            q = lambda a, pp: a[min(int(len(a) * pp), len(a) - 1)] if a else None
            s100 = raw.count(SCALE100)
            L.append(f"  {fn:52s} size={len(raw):8d} 像仿射矩阵的位置={len(ms):5d} "
                     f"(100,100,100)三元组={s100}")
            if bl:
                L.append(f"      基向量长度: min={bl[0]:.4f} 中位={q(bl,.5):.4f} max={bl[-1]:.4f}"
                         f"   平移长度: min={tl[0]:.4f} 中位={q(tl,.5):.4f} max={tl[-1]:.4f}")
                bands = {}
                for x in bl:
                    key = "≈1" if 0.95 <= x <= 1.05 else ("≈100" if 95 <= x <= 105 else "其它")
                    bands[key] = bands.get(key, 0) + 1
                L.append(f"      基向量长度分档: {bands}")
    # 对照：一份「正常且只用 96B 记录」的文件（从 5 份之外挑 A 记录多、变体 0 条的）
    L.append("=" * 96)
    L.append("### 对照：正常文件的 .mesh/.ske")
    for k in ["w1351_monster_xiyuqiezei_yifu_001", "w1351_npc_afei_lian_001"]:
        for sub in ["data/source/npc/monster", "data/source/npc"]:
            p = f"{ROOT}/.scratch/out/tree/{sub}/{k}/{k}.mesh"
            if os.path.exists(p):
                raw = open(p, "rb").read()
                ms = mats(raw)
                bl = sorted(x[1] for x in ms)
                L.append(f"  {k}.mesh size={len(raw)} 仿射矩阵位置={len(ms)} "
                         f"(100,100,100)三元组={raw.count(SCALE100)} "
                         f"基长 min={bl[0]:.4f} 中位={bl[len(bl)//2]:.4f} max={bl[-1]:.4f}"
                         if bl else f"  {k}.mesh 没找到矩阵形态")
                sk = p[:-5] + ".ske"
                if os.path.exists(sk):
                    r2 = open(sk, "rb").read()
                    m2 = mats(r2)
                    L.append(f"      同名 .ske: size={len(r2)} 矩阵位置={len(m2)} 三元组={r2.count(SCALE100)}")
                break
    open(os.path.join(OUT, "ske_side.txt"), "w", encoding="utf-8").write("\n".join(L))
    print("WROTE ske_side.txt", len(L))


if __name__ == "__main__":
    main()
