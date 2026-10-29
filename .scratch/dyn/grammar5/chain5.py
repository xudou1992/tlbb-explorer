"""逐条走完 5 份文件的记录链，验证 L = 228 + 8N 的定长律，并统计影响表覆盖率、
基向量长度、平移量级、以及「除以 100 之后」的骨间距是否落进正常量级。只读。"""
import os, re, struct, math

ROOT = "D:/TLGL"
MODEL = f"{ROOT}/.scratch/out/tree/data/source/npc/model"
OUT = f"{ROOT}/.scratch/dyn/grammar5"
FIVE = ["w1351_model_mj_nan_stone_h01", "w1351_model_bell_h002", "w1351_model_glass_ani_lf001",
        "w1351_model_fazhen_ani_lf001", "w1351_model_ymg01_stone01"]
OK = set(range(48, 58)) | set(range(65, 91)) | set(range(97, 123)) | {95, 45, 46}
TAIL = 92          # 表后再跟 76 字节未解块 + 16 字节 (100.0,100.0,100.0,u32 1)


def fname(raw, i):
    if i > 0 and raw[i - 1] in OK:
        return None
    f = raw[i:i + 32]
    if len(f) < 32:
        return None
    e = f.find(b"\0")
    if e < 3 or any(c not in OK for c in f[:e]) or any(c != 0 for c in f[e:]):
        return None
    return f[:e]


def blen(v):
    return math.sqrt(sum(x * x for x in v))


def walk(raw, L):
    vc = struct.unpack_from("<I", raw, 0x8C)[0]
    bones = struct.unpack_from("<I", raw, 0x110)[0]
    runs = re.compile(rb"[!-~]{3,31}")
    starts = []
    for m in runs.finditer(raw):
        i = m.start()
        if i % 4:
            continue
        nm = fname(raw, i)
        if nm is None or fname(raw, i + 32) != nm:
            continue
        if m.end() - m.start() > 31:
            continue
        starts.append((i, nm.decode()))
    starts.sort()
    L.append(f"  候选双名位置 {len(starts)} 个")
    recs = []
    for i, nm in starts:
        if i + 136 > len(raw):
            continue
        ws = [struct.unpack_from("<f", raw, i + 64 + 16 * k)[0] for k in range(4)]
        if any(abs(x) > 1e-3 for x in ws):
            continue
        one = struct.unpack_from("<f", raw, i + 128)[0]
        N = struct.unpack_from("<I", raw, i + 132)[0]
        if abs(one - 1.0) > 1e-3 or not (0 < N <= min(vc, 65536)):
            continue
        ids = struct.unpack_from("<%dI" % N, raw, i + 136)
        wts = struct.unpack_from("<%df" % N, raw, i + 136 + 4 * N)
        if len(set(ids)) != N or any(x >= vc for x in ids) or any(not (0.0 <= w <= 1.0001) for w in wts):
            continue
        tris = [struct.unpack_from("<3f", raw, i + 64 + 16 * k + 4) for k in range(4)]
        lens = [blen(v) for v in tris]
        recs.append(dict(at=i, nm=nm, N=N, ids=ids, wts=wts, tris=tris, lens=lens,
                         tail=struct.unpack_from("<3f", raw, i + 212 + 8 * N) if i + 228 + 8 * N <= len(raw) else None))
    recs.sort(key=lambda r: r["at"])
    # 定长律：本条起点 + 228 + 8N 是否正好等于下一条起点
    good = bad = 0
    bads = []
    for a, b in zip(recs, recs[1:]):
        exp = a["at"] + 228 + 8 * a["N"]
        if exp == b["at"]:
            good += 1
        else:
            bad += 1
            bads.append((a["nm"], hex(a["at"]), a["N"], hex(b["at"]), b["N"], b["at"] - exp))
    L.append(f"  通过全部字段判据的记录 = {len(recs)}（头部声明 {bones} 根）")
    L.append(f"  定长律 L=228+8N 相邻链吻合 {good} 处 / 不吻合 {bad} 处")
    if bads:
        L.append(f"    不吻合样例(前8): {[(a, b, c, d, e, '差%d' % f) for a, b, c, d, e, f in bads[:8]]}")
    sc = [r["tail"] for r in recs if r["tail"]]
    sc100 = sum(1 for t in sc if all(abs(x - 100.0) < 1e-3 for x in t))
    L.append(f"  记录尾 16 字节里的缩放三元组 = (100,100,100) 的条数 {sc100}/{len(sc)}")
    # 基向量 / 平移统计
    bl = sorted(x for r in recs for x in r["lens"][:3])
    tl = sorted(r["lens"][3] for r in recs)
    q = lambda a, p: a[min(int(len(a) * p), len(a) - 1)]
    L.append(f"  基向量长度 min={bl[0]:.5f} 中位={q(bl,.5):.5f} max={bl[-1]:.5f}")
    L.append(f"  平移长度   min={tl[0]:.5f} 中位={q(tl,.5):.5f} max={tl[-1]:.5f}")
    # 骨间距（相邻记录平移点两两欧氏距离）
    P = [(r["tris"][3][0], r["tris"][3][1], r["tris"][3][2]) for r in recs]
    step = sorted(blen([P[i][k] - P[i + 1][k] for k in range(3)]) for i in range(len(P) - 1))
    if step:
        L.append(f"  相邻记录骨位间距 min={step[0]:.4f} 中位={q(step,.5):.4f} max={step[-1]:.4f}"
                 f"   → 除以 100 后 min={step[0]/100:.4f} 中位={q(step,.5)/100:.4f}")
    allpair = sorted(blen([P[i][k] - P[j][k] for k in range(3)])
                     for i in range(len(P)) for j in range(i + 1, len(P)))
    if allpair:
        L.append(f"  全部骨两两间距 min={allpair[0]:.4f} 中位={q(allpair,.5):.4f} max={allpair[-1]:.4f}")
    # 覆盖率
    tot = sum(r["N"] for r in recs)
    seen = {}
    for r in recs:
        for v, w in zip(r["ids"], r["wts"]):
            seen.setdefault(v, 0.0)
            seen[v] += w
    cov = len(seen)
    ones = sum(1 for v, s in seen.items() if abs(s - 1.0) < 1e-3)
    multi = sum(1 for v, s in seen.items() if s > 1.0001)
    L.append(f"  影响表条目合计 {tot}，覆盖顶点 {cov}/{vc} = {100.0*cov/max(vc,1):.1f}%，"
             f"逐顶点权重和≈1.0 的有 {ones} 个，>1.0 的 {multi} 个")
    nn = sorted(r["N"] for r in recs)
    L.append(f"  每骨影响顶点数 min={nn[0]} 中位={q(nn,.5)} max={nn[-1]}")
    ws = sorted(set(round(w, 4) for r in recs for w in r["wts"]))
    L.append(f"  权重取值集合（前 12 个）{ws[:12]}")
    return recs, vc, bones


def main():
    L = []
    for k in FIVE:
        p = os.path.join(MODEL, k, k + ".mesh")
        raw = open(p, "rb").read()
        vc = struct.unpack_from("<I", raw, 0x8C)[0]
        lo = [1e30] * 3; hi = [-1e30] * 3
        for i in range(vc):
            t = struct.unpack_from("<3f", raw, 0x118 + i * 12)
            for j in range(3):
                lo[j] = min(lo[j], t[j]); hi[j] = max(hi[j], t[j])
        ext = max(hi[j] - lo[j] for j in range(3))
        L.append("=" * 100)
        L.append(f"### {k}  顶点 {vc}  顶点最大跨度 {ext:.4f}")
        recs = walk(raw, L)
        if recs and recs[0]:
            r0, vcx, bones = recs
            tl = sorted(rr["lens"][3] for rr in r0)
            L.append(f"  平移中位/顶点跨度 = {tl[len(tl)//2]/ext:.4f}   平移最大/跨度 = {tl[-1]/ext:.4f}")
            L.append(f"  若整块矩阵除以 100：平移中位/跨度 = {tl[len(tl)//2]/100/ext:.4f}")
    open(os.path.join(OUT, "chain5.txt"), "w", encoding="utf-8").write("\n".join(L))
    print("WROTE chain5.txt")


if __name__ == "__main__":
    main()
