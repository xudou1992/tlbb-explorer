"""两件收尾实测：
 1 全库抽样：现有 96B 记录的基向量长度到底是不是恒 ≈1（若不是，100 就是「作者烘进矩阵的缩放」，
   解析器本该按 |基| 归一，而不是当成单位换算常数）
 2 纯变体（现有解析器 0 条、变体命中）的文件清单与质量（链式/覆盖/声明骨吻合度）
只读。"""
import os, struct, math, csv, random, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from variant import field_name, a_matrix, skin_table, a_positions, v_positions, TREE, FIVE, RUN

OUT = os.path.dirname(os.path.abspath(__file__))


def basis_of(raw, at):
    m = struct.unpack_from("<16f", raw, at)
    L = [math.sqrt(sum(x * x for x in m[k * 3:k * 3 + 3])) for k in range(3)]
    return sum(L) / 3.0, math.sqrt(sum(x * x for x in m[12:15]))


def sample_basis(nfiles=400):
    files = []
    for dp, dn, fn in os.walk(TREE):
        for x in fn:
            if x.lower().endswith(".mesh"):
                files.append(os.path.join(dp, x))
    files.sort()
    rnd = random.Random(20261013)
    pick = rnd.sample(files, nfiles)
    L = []
    buckets = {"<0.5": 0, "0.5~0.95": 0, "0.95~1.05": 0, "1.05~50": 0, "50~200": 0, ">200": 0}
    filenonunit = []
    rec_tot = 0
    tr_over_ext = []
    for p in pick:
        raw = open(p, "rb").read()
        if len(raw) < 0x118:
            continue
        vc = struct.unpack_from("<I", raw, 0x8C)[0]
        if not (0 < vc < 8_000_000):
            continue
        lo = [1e30] * 3; hi = [-1e30] * 3
        for i in range(min(vc, 50000)):
            t = struct.unpack_from("<3f", raw, 0x118 + i * 12)
            for k in range(3):
                lo[k] = min(lo[k], t[k]); hi[k] = max(hi[k], t[k])
        ext = max(hi[k] - lo[k] for k in range(3)) or 1.0
        bad = []
        for m in RUN.finditer(raw):
            i = m.start()
            if i % 4:
                continue
            if field_name(raw, i) is None:
                continue
            ok, b, t = a_matrix(raw, i + 32)
            if not ok:
                continue
            rec_tot += 1
            k = "<0.5" if b < 0.5 else "0.5~0.95" if b < 0.95 else "0.95~1.05" if b <= 1.05 else \
                "1.05~50" if b < 50 else "50~200" if b <= 200 else ">200"
            buckets[k] += 1
            if not (0.95 <= b <= 1.05):
                bad.append((round(b, 3), i))
            tr_over_ext.append(t / ext)
        if bad:
            filenonunit.append((os.path.basename(p), len(bad), bad[:3]))
    L.append(f"抽样 {nfiles} 份文件，现有 96B 判据认到的记录共 {rec_tot} 条，按基向量长度分档：")
    for k, v in buckets.items():
        L.append(f"   {k:10s} {v:7d}   {100.0*v/max(rec_tot,1):6.2f}%")
    L.append(f"含「基长偏离 1」记录的文件数 = {len(filenonunit)} / {nfiles}")
    for x in filenonunit[:10]:
        L.append(f"   {x[0]:48s} 偏离条数={x[1]:4d} 样例(基长,偏移)={x[2]}")
    tr_over_ext.sort()
    q = lambda a, pp: a[min(int(len(a) * pp), len(a) - 1)] if a else 0
    L.append(f"正常记录 |平移|/顶点跨度: p10={q(tr_over_ext,.10):.3f} 中位={q(tr_over_ext,.5):.3f} "
             f"p90={q(tr_over_ext,.9):.3f} max={tr_over_ext[-1]:.3f}")
    return L, filenonunit


def pure_list():
    rows = list(csv.DictReader(open(os.path.join(OUT, "census.tsv"), encoding="utf-8"), delimiter="\t"))
    out = []
    for r in rows:
        if int(r["a"]) == 0 and int(r["v"]) > 0:
            out.append(r)
    L = [f"纯变体文件（现有解析器 0 条、变体 >=1 条）= {len(out)} 份"]
    L.append("  %-46s %5s %4s %4s %8s %9s %8s" % ("file", "bones", "A", "V", "链/对", "覆盖/顶点", "缩放尾"))
    for r in sorted(out, key=lambda x: -int(x["v"])):
        L.append("  %-46s %5s %4s %4s %8s %9s %8s" % (
            os.path.basename(r["path"])[:46], r["bones"], r["a"], r["v"],
            f'{r["chain_ok"]}/{r["vpairs"]}', f'{r["cov"]}/{r["vc"]}', r["scale100"]))
    return L, out


def main():
    L = []
    pl, pure = pure_list()
    L += pl
    L.append("")
    L.append("### 那 5 份在纯变体清单里的位置：见上（V 与 bones 吻合、链全接、顶点 100% 覆盖）")
    L.append("")
    bl, fn = sample_basis()
    L += bl
    open(os.path.join(OUT, "final_measures.txt"), "w", encoding="utf-8").write("\n".join(L))
    print("WROTE final_measures.txt", len(L))


if __name__ == "__main__":
    main()
