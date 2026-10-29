"""刀1/刀3 决定性实验：解析 .ani 骨架静态区（rest_poses 的 Python 复刻），检验管线闭合。

假设 H_rest：引擎局部 = 静态区 rest ∘ 轨道增量，即
    local_j(f) = [q_rest_j ⊗ q_track_j(f),  off48_j + t_track_j(f)]   （及若干乘序变体）
静态区记录（anim.rs::rest_poses 口径，60B/骨）：+0 缩放3(恒0.00992) +12 旋转4 +28 零3
    +40 1.0 +44 0 +48 逐骨3。轨道数据在文件尾（bones×frames×32）。

步骤：
  [S] 解 idle01.ani：轨道表（名字/顺序）+ 静态区 46 条（quat/offset48）。
  [T] 语义对照：q_rest vs 轨道 frame0 四元数 vs bind 局部旋转（记录骨）；
      off48 vs 轨道常量平移 vs bind 局部平移；X/Y/Z 分量分布（Z-up? Y-up?）。
  [U] 管线闭合：按 H_rest 各变体复合 frame0 世界 vs bind 世界（记录骨 + 全骨），
      最优变体再播全帧（idle01/walk，IBM 锚）量蒙皮位移。
输出 k2_rest.txt
"""
import sys, struct, math, json
import numpy as np

sys.path.insert(0, r"D:\TLGL\.scratch\ani_axis")
from common2 import GLBS, build, compose_worlds, ang, skin, centroid_resid

ANIDIR = r"D:\TLGL\.scratch\out\tree\data\source\npc\quest\w1351_monster_xiyuqiezei\ani"
OUT = []


def say(s=""):
    OUT.append(str(s))
    print(s)


def parse_ani(path):
    raw = open(path, "rb").read()
    tag = raw[0x40:0x48].split(b"\0")[0]
    assert tag == b"ani", raw[:8]
    bones = struct.unpack_from("<H", raw, 0xba)[0]
    bones2 = struct.unpack_from("<H", raw, 0xbe)[0]
    frames = struct.unpack_from("<H", raw, 0xc2)[0]
    assert bones == bones2
    names = []
    for i in range(bones):
        slot = raw[0xf0 + i * 30: 0xf0 + (i + 1) * 30]
        end = slot.find(0)
        if end < 0:
            end = 30
        nm = slot[:end]
        ok = nm and all(48 <= c <= 57 or 65 <= c <= 90 or 97 <= c <= 122 or c in b"_-." for c in nm)
        names.append(nm.decode() if ok else "")
    total = bones * frames * 32
    base = len(raw) - total
    # 静态区：名字表末尾 + 16（两个候选起点都试）
    named = sum(1 for x in names if x)
    rests = None
    for n in (named, bones):
        base_r = 0xf0 + n * 30 + 16
        if base_r + bones * 60 > base:
            continue
        cand = []
        ok = True
        for i in range(bones):
            o = base_r + i * 60
            unit = struct.unpack_from("<3f", raw, o)
            q = struct.unpack_from("<4f", raw, o + 12)
            nn = math.sqrt(sum(v * v for v in q))
            if not (nn < 1e-6 or 0.98 <= nn <= 1.02):
                ok = False
                break
            off = struct.unpack_from("<3f", raw, o + 48)
            cand.append((unit, q, off))
        if ok:
            rests = cand
            rest_base = base_r
            break
    tracks = []
    for i in range(bones):
        o = base + i * frames * 32
        rots = struct.unpack_from("<%df" % (frames * 4), raw, o)
        poss = struct.unpack_from("<%df" % (frames * 3), raw, o + frames * 16)
        scs = struct.unpack_from("<%df" % frames, raw, o + frames * 28)
        tracks.append(dict(rot=[[rots[4 * f + k] for k in range(4)] for f in range(frames)],
                           pos=[[poss[3 * f + k] for k in range(3)] for f in range(frames)],
                           sc=list(scs)))
    return dict(bones=bones, frames=frames, names=names, rests=rests, tracks=tracks,
                rest_base=rests is not None and rest_base or None)


def qmul(a, b):
    x1, y1, z1, w1 = a; x2, y2, z2, w2 = b
    return [w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
            w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
            w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
            w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2]


def qmat(q):
    x, y, z, w = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]], float)


def qang(a, b):
    """两个四元数（同旋转意义）的夹角。"""
    Ra, Rb = qmat(a), qmat(b)
    return ang(Ra @ Rb.T)


D = build(GLBS["yifu"])
ANg = read_anims if False else None
from common import read_anims
AN = read_anims(D)
NJ, names, jpar = D["NJ"], D["names"], D["jpar"]
B, IBM, C = D["B"], D["IBM"], D["C"]
covj = np.where(D["cov"])[0]; covj = covj[covj != 0]
Rb = D["blocal"][:, :3, :3].copy(); blt = D["blocal"][:, :3, 3].copy()
ph = [j for j in range(NJ) if np.linalg.norm(blt[j]) < 1e-6 and np.abs(Rb[j] - np.eye(3)).max() < 1e-5]

say("=== [S] 解 idle01.ani ===")
A = parse_ani(ANIDIR + r"\w1351_monster_xiyuqiezei_idle01.ani")
say("  bones=%d frames=%d 静态区=%s" % (A["bones"], A["frames"], "解出" if A["rests"] else "失败"))
say("  轨道名（.ani 顺序）前 8: %s" % A["names"][:8])
name2j = {nm: j for j, nm in enumerate(names)}
say("  轨道名全部能在 GLB 骨表中对上: %s（未命名 %d 条）" %
    (all(nm in name2j for nm in A["names"] if nm), sum(1 for nm in A["names"] if not nm)))
# 轨道顺序 vs GLB 顺序
ani_order = [name2j[nm] for nm in A["names"] if nm]
say("  .ani 轨道顺序 == GLB 骨序（剔除未命名后）: %s" % (ani_order == [j for j in range(NJ) if names[j] != ""][:len(ani_order)]))

# GLB 侧轨道数据（按名字映射），核对 .ani 原文与 GLB 一致
NF = A["frames"]
GLBper = AN["idle01"]
mismatch = 0
for i, nm in enumerate(A["names"]):
    if not nm:
        continue
    j = name2j[nm]
    if j not in GLBper:
        mismatch += 1; continue
    tr = GLBper[j]["translation"][1]
    rr = GLBper[j]["rotation"][1]
    if np.abs(np.array(tr) - np.array(A["tracks"][i]["pos"])).max() > 1e-9:
        mismatch += 1
    if np.abs(np.array(rr) - np.array(A["tracks"][i]["rot"])).max() > 1e-9:
        mismatch += 1
say("  .ani 原文轨道 vs GLB 轨道不一致的骨数: %d" % mismatch)

say("\n=== [T] 静态区语义 ===")
qrest = {}; off48 = {}; unit = None
for i, nm in enumerate(A["names"]):
    if not nm:
        continue
    u, q, off = A["rests"][i]
    qrest[nm] = q; off48[nm] = off
    unit = u
say("  缩放字段（恒值?）: %s" % (np.round(unit, 5)))
# q_rest vs 轨道 frame0 vs bind 局部旋转
d_rest_tr0, d_rest_bind, d_tr0_bind = [], [], []
for i, nm in enumerate(A["names"]):
    if not nm:
        continue
    j = name2j[nm]
    q0 = A["tracks"][i]["rot"][0]
    d_rest_tr0.append(qang(qrest[nm], q0))
    if j not in ph:
        d_rest_bind.append(qang(qrest[nm], [Rb[j][2, 1] - Rb[j][1, 2], Rb[j][0, 2] - Rb[j][2, 0],
                                            Rb[j][1, 0] - Rb[j][0, 1], 1 + Rb[j][0, 0] + Rb[j][1, 1] + Rb[j][2, 2]]))
        d_tr0_bind.append(qang(q0, [Rb[j][2, 1] - Rb[j][1, 2], Rb[j][0, 2] - Rb[j][2, 0],
                                    Rb[j][1, 0] - Rb[j][0, 1], 1 + Rb[j][0, 0] + Rb[j][1, 1] + Rb[j][2, 2]]))
say("  q_rest vs 轨道frame0: median %.2f° <0.01° %d/45" % (np.median(d_rest_tr0), sum(1 for x in d_rest_tr0 if x < 0.01)))
say("  q_rest vs bind局部旋转（记录骨）: median %.2f° <0.01° %d/%d" %
    (np.median(d_rest_bind), sum(1 for x in d_rest_bind if x < 0.01), len(d_rest_bind)))
say("  轨道frame0 vs bind局部旋转（记录骨）: median %.2f° <0.01° %d/%d" %
    (np.median(d_tr0_bind), sum(1 for x in d_tr0_bind if x < 0.01), len(d_tr0_bind)))
# off48 vs 轨道常量平移 vs bind 局部平移
say("  off48 / 轨道常量平移 / bind 局部平移（逐骨，记录骨+无记录骨各挑）:")
say("  %-24s %28s %28s %28s" % ("bone", "off48", "ani轨道t(med)", "bind局部t"))
for nm in ("bip01_pelvis", "bip01_spine1", "bip01_neck", "bip01_head", "bip01_l_clavicle",
           "bip01_l_forearm", "bip01_l_thigh", "bip01_l_foot", "bip01_l_calf", "bone01"):
    i = A["names"].index(nm)
    j = name2j[nm]
    tm = np.median(np.array(A["tracks"][i]["pos"]), axis=0)
    say("  %-24s %s %s %s" % (nm, np.round(off48[nm], 4), np.round(tm, 4), np.round(blt[j], 4)))

open(r"D:\TLGL\.scratch\ani_axis\k2_rest.txt", "w", encoding="utf-8").write("\n".join(OUT) + "\n")
print("saved -> k2_rest.txt")
