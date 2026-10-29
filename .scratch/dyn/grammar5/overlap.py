"""把一份正常文件里 A（96B）与 V（双名+矩阵@+68）两套记录的位置/名字/蒙皮条目并排列出来，
判断 V 到底是「现有解析器漏掉的骨」还是「同一根骨的第二份表」。只读。"""
import os, struct, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from variant import field_name, a_matrix, skin_table, a_positions, v_positions

OUT = os.path.dirname(os.path.abspath(__file__))
TARGETS = sys.argv[1:] or [
    "data/source/npc/model/w1351_caiji_duwugong_01/w1351_caiji_duwugong_01.mesh",
    "data/source/npc/w1351_diancang_hama_yifu_001/w1351_diancang_hama_yifu_001.mesh",
]
ROOT = "D:/TLGL/.scratch/out/tree/"

L = []
for t in TARGETS:
    p = os.path.join(ROOT, t.replace("/", "/"))
    if not os.path.exists(p):
        cand = []
        for dp, dn, fn in os.walk(ROOT):
            for x in fn:
                if x == os.path.basename(t):
                    cand.append(os.path.join(dp, x))
        if not cand:
            L.append(f"!! 找不到 {t}")
            continue
        p = cand[0]
    raw = open(p, "rb").read()
    vc = struct.unpack_from("<I", raw, 0x8C)[0]
    bones = struct.unpack_from("<I", raw, 0x110)[0]
    ap = sorted(a_positions(raw))
    vp = sorted(v_positions(raw, vc), key=lambda r: r["at"])
    L.append("=" * 100)
    L.append(f"{os.path.basename(p)} size={len(raw)} vc={vc} 声明骨={bones} A={len(ap)} V={len(vp)}")
    an = {}
    for i in ap:
        an.setdefault(field_name(raw, i).decode(), []).append(i)
    L.append("  A 记录名（次数, 首个偏移, 蒙皮条目数）:")
    tot_a = 0
    for nm, offs in sorted(an.items(), key=lambda kv: kv[1][0]):
        st = skin_table(raw, offs[0] + 96, vc)
        tot_a += st[0] if st else 0
        L.append(f"    {nm:26s} x{len(offs)} @{hex(offs[0]):>9} N={st[0] if st else 0}")
    L.append(f"  A 蒙皮条目合计 {tot_a}")
    L.append("  V 记录（偏移, 名, N, 与前一条的间隔, 是否也在 A 名单里）:")
    tot_v = 0
    for k, r in enumerate(vp):
        st = skin_table(raw, r["at"] + 132, vc)
        tot_v += st[0]
        gap = "" if k == 0 else f"{r['at'] - vp[k-1]['at']}"
        exp = "" if k == 0 else ("=228+8N_prev" if r["at"] - vp[k-1]["at"] == 228 + 8 * skin_table(raw, vp[k-1]["at"] + 132, vc)[0] else "≠")
        L.append(f"    @{hex(r['at']):>9} {r['nm']:22s} N={st[0]:5d} gap={gap:>7s} {exp:<12s} 在A名单={r['nm'] in an}")
    L.append(f"  V 蒙皮条目合计 {tot_v}   A+V 条目={tot_a + tot_v}  顶点数={vc}")
open(os.path.join(OUT, "overlap.txt"), "w", encoding="utf-8").write("\n".join(L))
print("WROTE overlap.txt", len(L))
