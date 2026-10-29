"""那 5 份里被「影响表非空」这一道挡掉的记录是谁（多半是没有顶点的根骨）。只读。"""
import os, struct, sys, re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from variant import field_name, a_matrix, v_positions, RUN, FIVE, TREE

MODEL = f"{TREE}/data/source/npc/model"
L = []
for k in sorted(FIVE):
    p = os.path.join(MODEL, k[:-5], k)
    raw = open(p, "rb").read()
    vc = struct.unpack_from("<I", raw, 0x8C)[0]
    bones = struct.unpack_from("<I", raw, 0x110)[0]
    strict = v_positions(raw, vc)
    sn = set(r["nm"] for r in strict)
    loose = []
    for m in RUN.finditer(raw):
        i = m.start()
        if i % 4:
            continue
        nm = field_name(raw, i)
        if nm is None or field_name(raw, i + 32) != nm:
            continue
        if i + 136 > len(raw) or abs(struct.unpack_from("<f", raw, i + 64)[0]) > 1e-3:
            continue
        ok, b, t = a_matrix(raw, i + 68)
        if not ok:
            continue
        N = struct.unpack_from("<I", raw, i + 132)[0]
        loose.append((i, nm.decode(), N, b, t))
    miss = [x for x in loose if x[1] not in sn]
    L.append("%s: 声明%d  严格判据%d  只去掉「表非空」这一道后%d  差额%d" % (k, bones, len(strict), len(loose), len(loose) - len(strict)))
    for a, n, N, b, t in miss:
        L.append("    被挡住: @%s 名=%s N=%d 基长=%.5f |平移|=%.5f" % (hex(a), n, N, b, t))
    L.append("    严格命中的名字数=%d  声明骨=%d  差=%d" % (len(sn), bones, bones - len(sn)))
    # 名字没被认到的骨：从 .ske/ani 侧捞一遍骨名做对照
    skel = {}
    d = os.path.dirname(p)
    for f in os.listdir(d):
        if f.lower().endswith((".ske", ".ani")):
            r2 = open(os.path.join(d, f), "rb").read()
            for m in re.finditer(rb"[Bb]one[0-9_][A-Za-z0-9_]{0,28}|fracture_bone[0-9_][A-Za-z0-9_]{0,24}", r2):
                skel[m.group().decode()] = skel.get(m.group().decode(), 0) + 1
    extra = sorted(set(skel) - sn)
    L.append("    同目录 .ske/.ani 里出现、但严格判据没认到的骨名 %d 个：%s" % (len(extra), extra[:12]))
    L.append("")
open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "missing_rec.txt"), "w", encoding="utf-8").write("\n".join(L))
print("WROTE missing_rec.txt", len(L))
