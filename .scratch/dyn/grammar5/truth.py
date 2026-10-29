"""判定「正常文件上的变体命中」到底是噪声还是真记录。三条地面真相：
 1 A 记录名 与 V 记录名 是否互斥（同一根骨被两套各认一次 = 假命中）
 2 A+V 根数 是否正好等于头部声明骨数
 3 A∪V 的蒙皮表并集是否把顶点 100% 覆盖、逐顶点权重和≈1
并对一份正常文件的 V 命中做逐字节打印。只读。"""
import os, re, struct, math, csv, random, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from variant import field_name, a_matrix, skin_table, a_positions, v_positions, RUN, TREE, FIVE

OUT = os.path.dirname(os.path.abspath(__file__))


def a_skin_union(raw, ap, vc):
    seen = {}
    for i in ap:
        st = skin_table(raw, i + 96, vc)
        if st:
            for v, w in zip(st[1], st[2]):
                seen[v] = seen.get(v, 0.0) + w
    return seen


def one(path, L, dump=False):
    raw = open(path, "rb").read()
    vc = struct.unpack_from("<I", raw, 0x8C)[0]
    bones = struct.unpack_from("<I", raw, 0x110)[0]
    ap = a_positions(raw)
    vp = v_positions(raw, vc)
    an = set(field_name(raw, i).decode() for i in ap)
    vn = set(r["nm"] for r in vp)
    inter = an & vn
    sa = a_skin_union(raw, ap, vc)
    sv = {}
    for r in vp:
        st = skin_table(raw, r["at"] + 132, vc)
        for v, w in zip(st[1], st[2]):
            sv[v] = sv.get(v, 0.0) + w
    uni = set(sa) | set(sv)
    oksum = sum(1 for v in uni if abs(sa.get(v, 0.0) + sv.get(v, 0.0) - 1.0) < 1e-3)
    L.append(f"  {os.path.basename(path)[:48]:50s} bones={bones:4d} A={len(ap):4d} V={len(vp):4d} "
             f"A+V={len(ap)+len(vp):4d} 名重={len(inter):3d} 并集覆盖={len(uni)}/{vc} "
             f"权重和≈1={oksum}")
    if dump and vp:
        r = vp[0]
        i = r["at"]
        L.append(f"     首条 V @{hex(i)} 名={r['nm']}；该文件 A 位置里有没有落在 [{hex(i)}, {hex(i+228+8*r['N'])}) 的： "
                 f"{[hex(x) for x in ap if i - 96 <= x <= i + 260]}")
        for off in range(i - 16, i + 148, 16):
            b = raw[off:off + 16]
            asc = "".join(chr(x) if 32 <= x < 127 else "." for x in b)
            fl = " ".join("%.5g" % struct.unpack_from("<f", raw, off + 4 * k)[0] for k in range(4))
            L.append(f"       {hex(off):>10}  {b.hex(' ')}  |{asc:<16}|  {fl}")
    return len(ap), len(vp), bones, len(inter), len(uni), vc


def main():
    L = []
    files = []
    for dp, dn, fn in os.walk(TREE):
        for x in fn:
            if x.lower().endswith(".mesh"):
                files.append(os.path.join(dp, x))
    files.sort()
    L.append("### 5 份异常文件")
    for p in files:
        if os.path.basename(p) in FIVE:
            one(p, L, dump=(os.path.basename(p) == "w1351_model_fazhen_ani_lf001.mesh"))
    L.append("")
    L.append("### 30 份正常文件（题面要求的误命中实测，A>=5、按路径排序取前 30，排除那 5 份）")
    norm = []
    for p in files:
        if os.path.basename(p) in FIVE:
            continue
        norm.append(p)
    picked = []
    for p in norm:
        if len(picked) >= 30:
            break
        raw = open(p, "rb").read()
        if len(raw) < 0x118:
            continue
        vc = struct.unpack_from("<I", raw, 0x8C)[0]
        if not (0 < vc < 8_000_000):
            continue
        ap = a_positions(raw)
        if len(ap) >= 5:
            picked.append(p)
    stat = {"A": 0, "V": 0, "bones": 0, "namecoll": 0, "covfull": 0, "hitfiles": 0}
    for p in picked:
        a, v, bo, inter, uni, vc = one(p, L, dump=(os.path.basename(p) == "w1351_caiji_duwugong_01.mesh"))
        stat["A"] += a; stat["V"] += v; stat["bones"] += bo; stat["namecoll"] += inter
        if v:
            stat["hitfiles"] += 1
        if uni == vc:
            stat["covfull"] += 1
    L.append(f"  小计：A={stat['A']} V={stat['V']} A+V={stat['A']+stat['V']} 声明骨合计={stat['bones']} "
             f"名字重复(=同骨被两套各认一次)={stat['namecoll']}")
    L.append(f"  ⇒ 有命中的文件 {stat['hitfiles']}/30；A∪V 蒙皮并集把顶点全覆盖的文件 {stat['covfull']}/30")
    open(os.path.join(OUT, "truth.txt"), "w", encoding="utf-8").write("\n".join(L))
    print("WROTE truth.txt lines", len(L))


if __name__ == "__main__":
    main()
