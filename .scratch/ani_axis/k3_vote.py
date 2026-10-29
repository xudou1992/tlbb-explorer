"""跨怪物投票（2026-10-07）：frame0 稳定性 + 静态区语义在别的怪上是否复现。
纯 Python 解 .mesh 尾部（k2_mat64 的解析器）+ .ani（k2_rest 的解析器），不走 cargo。
对每只怪：
  [Y] 静态区跨动作是否逐字节一致（抽 3 条动作）
  [Z] frame0 局部跨动作稳定性：完全一致的动作分组（最大组占比）+ 带权重骨上的差异
      （权重来自 .mesh 尾部影响表 infN！不用 GLB）
  [Z2] qrest == blocal⁻¹（被动序）在记录骨上的命中率；off48 == 第一孩子轨道平移命中率
输出 k3_vote.txt
"""
import sys, struct, math, json, glob, os
import numpy as np

sys.path.insert(0, r"D:\TLGL\.scratch\ani_axis")
from k2_mat64 import parse_tail, try_entry, record_at, u32, name_at, is_u92, is_mat64, is_inf, NODE_RECORD
from k2_rest import parse_ani, qmul

OUT = []


def say(s=""):
    OUT.append(str(s))
    print(s)


def qmat(q):
    x, y, z, w = q
    n = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
    x, y, z, w = x / n, y / n, z / n, w / n
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]], float)


def mq(R):
    t = R[0, 0] + R[1, 1] + R[2, 2]
    if t > 0:
        s = math.sqrt(t + 1) * 2; w = s / 4; x = (R[2, 1] - R[1, 2]) / s; y = (R[0, 2] - R[2, 0]) / s; z = (R[1, 0] - R[0, 1]) / s
    elif R[0, 0] > R[1, 1] and R[0, 0] > R[2, 2]:
        s = math.sqrt(1 + R[0, 0] - R[1, 1] - R[2, 2]) * 2; w = (R[2, 1] - R[1, 2]) / s; x = s / 4; y = (R[0, 1] + R[1, 0]) / s; z = (R[0, 2] + R[2, 0]) / s
    elif R[1, 1] > R[2, 2]:
        s = math.sqrt(1 + R[1, 1] - R[0, 0] - R[2, 2]) * 2; w = (R[0, 2] - R[2, 0]) / s; x = (R[0, 1] + R[1, 0]) / s; y = s / 4; z = (R[1, 2] + R[2, 1]) / s
    else:
        s = math.sqrt(1 + R[2, 2] - R[0, 0] - R[1, 1]) * 2; w = (R[1, 0] - R[0, 1]) / s; x = (R[0, 2] + R[2, 0]) / s; y = (R[1, 2] + R[2, 1]) / s; z = s / 4
    return [x, y, z, w]


def qang(a, b):
    return ang(qmat(a) @ qmat(b).T) if False else _qang(a, b)


def ang(M):
    return math.degrees(math.acos(max(-1.0, min(1.0, (np.trace(M) - 1) / 2))))


def _qang(a, b):
    return ang(qmat(a) @ qmat(b).T)


MONSTERS = [
    ("hamigua", r"D:\TLGL\.scratch\out\tree\data\source\npc\changjingdaoju\w1351_caiji_hamigua_01"),
    ("heihou", r"D:\TLGL\.scratch\out\tree\data\source\npc\changjingdaoju\w1351_caiji_heihou_01"),
    ("duchanchu", r"D:\TLGL\.scratch\out\tree\data\source\npc\changjingdaoju\w1351_caiji_duchanchu_01"),
    ("bosijihao", r"D:\TLGL\.scratch\out\tree\data\source\npc\changjingdaoju\w1351_caiji_bosijihao_01"),
    ("xiyuqiezei", r"D:\TLGL\.scratch\out\tree\data\source\npc\quest\w1351_monster_xiyuqiezei"),
]

for tag, mdir in MONSTERS:
    say("#" * 72)
    say("=== %s ===" % tag)
    meshes = sorted(glob.glob(os.path.join(mdir, "*.mesh")))
    anis = sorted(glob.glob(os.path.join(mdir, "ani", "*.ani")))
    if not meshes or not anis:
        say("  缺 .mesh 或 .ani，跳过")
        continue
    # 层级（取第一个 mesh）
    entries, prelude, vc, socks = parse_tail(meshes[0])
    if entries is None:
        say("  .mesh 尾部解析失败，跳过")
        continue
    names = [e["name"] for e in entries]
    name2i_ani = None
    # 影响表 -> 每骨是否有权重（用第一个 mesh 的条目 inf 块）
    weighted = set()
    for e in entries:
        for b in e["blocks"]:
            if b[0] == "inf" and b[2] > 0:
                weighted.add(e["name"])
    # 静态区共享性 + frame0 稳定性
    A0 = parse_ani(anis[0])
    say("  mesh=%d 个, ani=%d 条, 骨 %d, 静态区=%s" %
        (len(meshes), len(anis), A0["bones"], "解出" if A0["rests"] else "失败"))
    # [Y] 静态区共享：比较 idle 类与 walk 类动作的静态区字节
    raws = {os.path.basename(p): open(p, "rb").read() for p in anis[:4]}
    if len(raws) >= 2:
        ks = list(raws)
        r1, r2 = raws[ks[0]], raws[ks[1]]
        bones, frames1 = A0["bones"], A0["frames"]
        # 静态区范围 = rest_base .. track_start
        tb1 = len(r1) - bones * frames1 * 32
        frames2 = struct.unpack_from("<H", r2, 0xc2)[0]
        tb2 = len(r2) - bones * frames2 * 32
        base1 = base2 = None
        named = sum(1 for x in A0["names"] if x)
        for n in (named, bones):
            b1 = 0xf0 + n * 30 + 16
            if b1 + bones * 60 <= tb1:
                base1 = b1
            b2 = 0xf0 + n * 30 + 16
            if b2 + bones * 60 <= tb2:
                base2 = b2
        if base1 is not None and base2 is not None:
            seg1 = r1[base1:base1 + bones * 60]
            seg2 = r2[base2:base2 + bones * 60]
            ndiff = sum(1 for a, b in zip(seg1, seg2) if a != b)
            say("  [Y] 静态区 %s vs %s: %d/%d 字节不同" % (ks[0], ks[1], ndiff, bones * 60))
    # [Z] frame0 分组
    f0 = {}
    for p in anis:
        Ax = parse_ani(p)
        key = []
        for i in range(Ax["bones"]):
            key.append(tuple(np.round(Ax["tracks"][i]["rot"][0], 7)) if Ax["tracks"][i]["rot"] else ())
            key.append(tuple(np.round(Ax["tracks"][i]["pos"][0], 7)) if Ax["tracks"][i]["pos"] else ())
        f0.setdefault(tuple(key), []).append(os.path.basename(p))
    groups = sorted(f0.values(), key=len, reverse=True)
    say("  [Z] %d 条动作按 frame0 局部分组: %s" %
        (len(anis), [len(g) for g in groups]))
    say("      最大组(%d 条): %s" % (len(groups[0]), ", ".join(groups[0][:6])))
    # [Z2] qrest 命中率：需要 bind 局部 = 条目孩子槽记录推导 -> 用 parse_tail 的 own/children
    # 重建 worlds（与 GLB 导出口径一致：bind = own 或 父孩子槽记录；无 -> 父世界）
    index = {e["name"]: i for i, e in enumerate(entries)}
    parent = {}
    for i, e in enumerate(entries):
        for cn, cb in e["children"]:
            parent[cn] = e["name"]
    binds = {}
    for e in entries:
        if e["own"] is not None:
            binds[e["name"]] = e["own"]
    for e in entries:
        for cn, cb in e["children"]:
            if cb is not None and cn not in binds:
                binds[cn] = cb
    # 行主序 96B 记录 = 世界绑定逆（列口径 B = inv(record)）；局部 = B_child · B_parent^{-1}
    import numpy as np2
    def inv4(M):
        """96B 记录 = 行主序引擎矩阵 = B_col⁻¹ 的转置；B_col = inv(record).T"""
        return np.linalg.inv(M).T
    W = {}
    for e in entries:
        nm = e["name"]
        if nm in binds:
            W[nm] = inv4(binds[nm])
    # 逐骨局部（有记录且父有记录）
    hits = tot = 0; misses = []
    off_hits = off_tot = 0
    for i, nm in enumerate(A0["names"]):
        if not nm:
            continue
        p = parent.get(nm)
        if nm in binds and p in binds and nm in W and p in W:
            L = np.linalg.inv(W[p]) @ W[nm]
            qb = mq(L[:3, :3])
            j = index[nm]
            ii = A0["names"].index(nm)
            qr = A0["rests"][ii][1]
            tot += 1
            if _qang(qr, [-qb[0], -qb[1], -qb[2], qb[3]]) < 0.01:
                hits += 1
            else:
                misses.append(nm)
        # off48 == 第一孩子轨道平移
        kids = [c for c in parent if parent[c] == nm]
        if nm in [n for n in A0["names"] if n] and kids:
            ck = kids[0]
            if ck in A0["names"]:
                ii = A0["names"].index(nm); ic = A0["names"].index(ck)
                o48 = A0["rests"][ii][2]
                tc = A0["tracks"][ic]["pos"][0]
                off_tot += 1
                if np.linalg.norm(np.array(o48) - np.array(tc)) < 1e-4:
                    off_hits += 1
    say("  [Z2] qrest==blocal⁻¹: %d/%d %s" % (hits, tot, ("miss: " + ", ".join(misses[:6])) if misses else ""))
    say("       off48==第一孩子轨道t: %d/%d" % (off_hits, off_tot))

open(r"D:\TLGL\.scratch\ani_axis\k3_vote.txt", "w", encoding="utf-8").write("\n".join(OUT) + "\n")
print("saved -> k3_vote.txt")
