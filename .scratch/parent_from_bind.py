"""父骨链的一次算式搜索：绑定位移是世界系（左右镜像对验过），.ani 第 0 帧是每骨自己的位姿。
若「bind_i = local_i ∘ bind_父」成立，那对每根骨 i，能让残差最小的那个 j 就是它爸。

试四种口径组合（四元数 (x,y,z,w)/(x,y,z,w) 换序 × 行向量乘序两种），
用「是否长成单根、无环、每根骨都有明显更优的那个 j」来判哪一种是真。
"""
import io
import json
import math
import sys


def qmat(q, swap):
    x, y, z, w = (q[1], q[2], q[3], q[0]) if swap else (q[0], q[1], q[2], q[3])
    n = math.sqrt(x * x + y * y + z * z + w * w)
    if n == 0:
        return None
    x, y, z, w = x / n, y / n, z / n, w / n
    return [
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ]


def mul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def ident():
    return [[1.0 if i == j else 0.0 for j in range(3)] for i in range(3)]


def fro(a, b):
    return math.sqrt(sum((a[i][j] - b[i][j]) ** 2 for i in range(3) for j in range(3)))


def bind3(node):
    m = node["bind"]
    return [list(m[0:3]), list(m[4:7]), list(m[8:11])], (m[12], m[13], m[14])


def run(path):
    d = json.load(io.open(path, encoding="utf-8"))
    nodes = {n["name"]: n for n in d["nodes"] if n.get("name")}
    anim = d["animations"][0]
    tracks = {t["bone"]: t for t in anim["tracks"] if t.get("bone")}
    common = [b for b in nodes if b in tracks]
    print("%s · 节点 %d · 轨道 %d · 两边都有名字的 %d" % (path.split("/")[-1], len(nodes), len(tracks), len(common)))
    if len(common) < 5:
        return
    best_report = None
    for swap in (False, True):
        for order in ("LR", "RL"):
            rows = []
            for bi in common:
                Rb, tb = bind3(nodes[bi])
                t = tracks[bi]
                q = t["rotations"][0]
                p = t["positions"][0]
                Rl = qmat(q, swap)
                if Rl is None:
                    continue
                best = None
                for bj in nodes:
                    if bj == bi:
                        continue
                    Rp, tp = bind3(nodes[bj])
                    # 行向量约定：先 local 再 parent = local·parent
                    predR = mul(Rl, Rp) if order == "LR" else mul(Rp, Rl)
                    predt = (
                        (p[0] * Rp[0][0] + p[1] * Rp[1][0] + p[2] * Rp[2][0] + tp[0],
                         p[0] * Rp[0][1] + p[1] * Rp[1][1] + p[2] * Rp[2][1] + tp[1],
                         p[0] * Rp[0][2] + p[1] * Rp[1][2] + p[2] * Rp[2][2] + tp[2])
                        if order == "LR"
                        else (
                            tp[0] + p[0], tp[1] + p[1], tp[2] + p[2],
                        )
                    )
                    dr = fro(predR, Rb)
                    dt = math.sqrt(sum((a - b) ** 2 for a, b in zip(predt, tb)))
                    r = dr + dt
                    if best is None or r < best[0]:
                        best = (r, bj, dr, dt)
                # 自己就是世界系？
                self_r = fro(Rl, Rb) + math.sqrt(sum((a - b) ** 2 for a, b in zip(p, tb)))
                if best:
                    rows.append((bi, best[1], best[0], best[2], best[3], self_r))
            if not rows:
                continue
            win_self = sum(1 for _, _, _, _, _, sr in rows if sr < min(0.05, 1e9))
            clear = sum(1 for r in rows if r[2] < 0.05)
            print("  swap=%-5s order=%s · 残差<0.05 的骨 %d/%d · 自身即世界系(<0.05) %d"
                  % (swap, order, clear, len(rows), win_self))
            if best_report is None or clear > best_report[0]:
                best_report = (clear, swap, order, rows)
    if best_report:
        clear, swap, order, rows = best_report
        print("  最好的一组：swap=%s order=%s，%d 根残差<0.05" % (swap, order, clear))
        for bi, bj, r, dr, dt, sr in sorted(rows, key=lambda x: x[2])[:14]:
            print("    %-26s 候选父 %-26s 残差=%.3f (转 %.3f/位 %.3f) 自身=%.3f"
                  % (bi, bj, r, dr, dt, sr))


run(sys.argv[1] if len(sys.argv) > 1 else ".scratch/skel_dump2/w1351_monster_xiyuqiezei_yifu_001.skel.json")
