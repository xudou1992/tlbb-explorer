"""统一口径：这 5 份（以及全库一批文件）的骨架记录 = 标准 96B 记录前面多插了
「重复骨名 char[32] + 4 字节 0」——矩阵仍在 骨名+68 处、仍是行主序 A 判据那套。
本脚本按这个口径全库普查，并对 30 份正常文件做误命中实测。只读。

记录布局（起点 i = 骨名首字节）：
  +0   char[32] 骨名
  +32  char[32] 同一个骨名（重复一次）
  +64  f32 恒 0（记录里的一个标量槽）
  +68  f32[16] 标准行主序仿射矩阵（m[15]=1，前三行基向量、第四行平移）
  +132 u32 N 影响顶点数
  +136 u32[N] 顶点号
  +136+4N f32[N] 权重
  之后 92 字节尾块（末 16 字节恒为 (100.0,100.0,100.0, u32 1)）
  ⇒ 记录长度 L = 228 + 8N
"""
import os, re, struct, math, sys, json

ROOT = "D:/TLGL"
TREE = f"{ROOT}/.scratch/out/tree"
OUT = f"{ROOT}/.scratch/dyn/grammar5"
OK = set(range(48, 58)) | set(range(65, 91)) | set(range(97, 123)) | {95, 45, 46}
RUN = re.compile(rb"[!-~]{3,31}")
FIVE = {"w1351_model_mj_nan_stone_h01.mesh", "w1351_model_bell_h002.mesh",
        "w1351_model_glass_ani_lf001.mesh", "w1351_model_fazhen_ani_lf001.mesh",
        "w1351_model_ymg01_stone01.mesh"}


def field_name(raw, i):
    if i > 0 and raw[i - 1] in OK:
        return None
    f = raw[i:i + 32]
    if len(f) < 32:
        return None
    e = f.find(b"\x00")
    if e < 3 or any(c not in OK for c in f[:e]) or any(c != 0 for c in f[e:]):
        return None
    return f[:e]


def a_matrix(raw, at):
    """标准 16 浮点行主序仿射矩阵判据（对齐 read_node 的矩阵部分）。返回 (ok, basis长, 平移长)。"""
    if at + 64 > len(raw):
        return False, 0, 0
    m = struct.unpack_from("<16f", raw, at)
    if any(abs(v) >= 1e7 or v != v for v in m):
        return False, 0, 0
    if abs(m[15] - 1.0) > 1e-3:
        return False, 0, 0
    R = [list(m[0:3]), list(m[4:7]), list(m[8:11])]
    L = [math.sqrt(sum(x * x for x in v)) for v in R]
    mn, mx = min(L), max(L)
    if mn <= 1e-6 or mx / mn > 1.05:
        return False, 0, 0
    for i in range(3):
        for j in range(i + 1, 3):
            if abs(sum(R[i][k] * R[j][k] for k in range(3))) / (L[i] * L[j]) > 0.03:
                return False, 0, 0
    t = math.sqrt(sum(x * x for x in m[12:15]))
    return True, sum(L) / 3.0, t


def skin_table(raw, at, vc):
    N = struct.unpack_from("<I", raw, at)[0] if at + 4 <= len(raw) else 0
    if not (0 < N <= min(vc, 65536)):
        return None
    ib = raw[at + 4:at + 4 + 4 * N]
    wb = raw[at + 4 + 4 * N:at + 4 + 8 * N]
    if len(ib) < 4 * N or len(wb) < 4 * N:
        return None
    ids = struct.unpack("<%dI" % N, ib)
    wts = struct.unpack("<%df" % N, wb)
    if len(set(ids)) != N or any(x >= vc for x in ids):
        return None
    if any(not (0.0 <= w <= 1.0001) or w != w for w in wts) or all(w <= 1e-6 for w in wts):
        return None
    return N, ids, wts


def a_positions(raw):
    """现有解析器（96B 记录）认到的位置集合。候选点用可打印串枚举（真记录的名字
    必然是一段可打印 ASCII，所以这是合法候选集的超集，与逐 4 字节扫描等价但快得多）。"""
    out = []
    for m in RUN.finditer(raw):
        i = m.start()
        if i % 4:
            continue
        nm = field_name(raw, i)
        if nm is None:
            continue
        if i >= 32:
            prev = raw[i - 32:i]
            pl = prev.find(b"\x00")
            pl = 32 if pl < 0 else pl
            if pl >= 3 and all(c in OK for c in prev[:pl]) and prev[:3].lower() == b"tx_":
                continue
        ok, _, _ = a_matrix(raw, i + 32)
        if ok:
            out.append(i)
    out.sort()
    kept, last = [], -10**9
    for i in out:                      # 与 Rust scan_nodes 一致：命中后跳 96，不重叠计数
        if i >= last + 96:
            kept.append(i)
            last = i
    return kept


def v_positions(raw, vc):
    """变体记录（双名 + 4 字节 0 + 矩阵@+68 + 表@+132）。"""
    out = []
    for m in RUN.finditer(raw):
        i = m.start()
        if i % 4:
            continue
        nm = field_name(raw, i)
        if nm is None or field_name(raw, i + 32) != nm:
            continue
        if i + 136 > len(raw):
            continue
        if abs(struct.unpack_from("<f", raw, i + 64)[0]) > 1e-3:
            continue
        ok, bl, tl = a_matrix(raw, i + 68)
        if not ok:
            continue
        st = skin_table(raw, i + 132, vc)
        if st is None:
            continue
        out.append(dict(at=i, nm=nm.decode(), basis=bl, trans=tl, N=st[0]))
    return out


def census(path):
    raw = open(path, "rb").read()
    if len(raw) < 0x118:
        return None
    vc = struct.unpack_from("<I", raw, 0x8C)[0]
    bones = struct.unpack_from("<I", raw, 0x110)[0]
    if vc == 0 or vc > 8_000_000:
        return None
    ap = a_positions(raw)
    vp = v_positions(raw, vc)
    # 链式验证：变体记录按 L=228+8N 是否首尾相接
    vp.sort(key=lambda r: r["at"])
    chain = sum(1 for a, b in zip(vp, vp[1:]) if a["at"] + 228 + 8 * a["N"] == b["at"])
    seen = {}
    for r in vp:
        st = skin_table(raw, r["at"] + 132, vc)
        for v, w in zip(st[1], st[2]):
            seen[v] = seen.get(v, 0.0) + w
    cov = len(seen)
    one = sum(1 for s in seen.values() if abs(s - 1.0) < 1e-3)
    scal = sum(1 for r in vp
               if r["at"] + 228 + 8 * r["N"] <= len(raw)
               and all(abs(x - 100.0) < 1e-3 for x in struct.unpack_from("<3f", raw, r["at"] + 212 + 8 * r["N"])))
    zs = [struct.unpack_from("<I", raw, r["at"] + 64)[0] for r in vp]
    return dict(size=len(raw), vc=vc, bones=bones, a=len(ap), v=len(vp),
                chain=chain, rec_pair=len(vp) - 1 if vp else 0, cov=cov, one=one,
                scale100=scal, zslots=sorted(set(zs))[:4],
                basis=[round(r["basis"], 4) for r in vp], trans=[round(r["trans"], 3) for r in vp])


def main():
    files = []
    for dp, dn, fn in os.walk(TREE):
        for x in fn:
            if x.lower().endswith(".mesh"):
                files.append(os.path.join(dp, x))
    files.sort()
    res = {}
    for p in files:
        r = census(p)
        if r:
            res[p] = r
    with open(os.path.join(OUT, "census.tsv"), "w", encoding="utf-8") as fh:
        fh.write("path\tsize\tvc\tbones\ta\tv\tchain_ok\tvpairs\tcov\twsum1\tscale100\tzslots\n")
        for p, r in res.items():
            fh.write("\t".join(str(x) for x in [p, r["size"], r["vc"], r["bones"], r["a"], r["v"],
                                                r["chain"], r["rec_pair"], r["cov"], r["one"],
                                                r["scale100"], ",".join(map(str, r["zslots"]))]) + "\n")
    json.dump({k: {kk: vv for kk, vv in v.items() if kk not in ("basis", "trans")}
               for k, v in res.items()}, open(os.path.join(OUT, "census.json"), "w"))
    print("census files:", len(res))


if __name__ == "__main__":
    main()
