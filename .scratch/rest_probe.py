"""rest.rs 落码前探针：在 Python 里把「静态区反解重建」按 core 的行向量口径走一遍，
核验算法细节（neck 为什么 solved、命中率、解剖高度、fallback 链），再搬进 Rust。
只读研究班产物与解包树，不改任何研究脚本。
"""
import sys, struct, math
import numpy as np

MESHES = {
    "xiyuqiezei": r"D:\TLGL\.scratch\out\tree\data\source\npc\quest\w1351_monster_xiyuqiezei",
    "heihou": r"D:\TLGL\.scratch\out\tree\data\source\npc\changjingdaoju\w1351_caiji_heihou_01",
    "duchanchu": r"D:\TLGL\.scratch\out\tree\data\source\npc\changjingdaoju\w1351_caiji_duchanchu_01",
}
NAME_FIELD = 32
NODE_RECORD = 96
OUT = []


def say(s=""):
    OUT.append(str(s))
    print(s)


def f32(raw, at):
    if at + 4 > len(raw):
        return None
    return struct.unpack_from("<f", raw, at)[0]


def u32(raw, at):
    if at + 4 > len(raw):
        return None
    return struct.unpack_from("<I", raw, at)[0]


def name_at(raw, at):
    if at < 1 or at + 32 > len(raw):
        return None
    prev = raw[at - 1]
    if prev < 128 and (chr(prev).isalnum() or prev in b"_.-"):
        return None
    nb = raw[at:at + 32]
    end = nb.find(0)
    if end < 3 or end > 31:
        return None
    if not all(48 <= c <= 57 or 65 <= c <= 90 or 97 <= c <= 122 or c in b"_.-" for c in nb[:end]):
        return None
    if any(c != 0 for c in nb[end:]):
        return None
    return nb[:end].decode("ascii")


def record_at(raw, at):
    nm = name_at(raw, at)
    if nm is None:
        return None
    m = []
    for k in range(16):
        v = f32(raw, at + 32 + k * 4)
        if v is None or not math.isfinite(v) or abs(v) >= 1e7:
            return None
        m.append(v)
    if abs(m[15] - 1.0) > 1e-3:
        return None
    rows = [m[0:3], m[4:7], m[8:11]]
    lens = [np.linalg.norm(r) for r in rows]
    if min(lens) <= 1e-6 or max(lens) / min(lens) > 1.05:
        return None
    for i in range(3):
        for k in range(i + 1, 3):
            d = sum(rows[i][t] * rows[k][t] for t in range(3))
            if abs(d) / (lens[i] * lens[k]) > 0.03:
                return None
    return nm, np.array(m, float).reshape(4, 4)


def is_u92(raw, at):
    d = f32(raw, at)
    if d is None or not (0.9 <= d <= 1.1):
        return False
    for o, want in ((20, d), (40, d), (60, 1.0)):
        v = f32(raw, at + o)
        if v is None or abs(v - want) > (1e-6 if want == d else 1e-3):
            return False
    return all(abs((f32(raw, at + o) or 0) - 100.0) < 1e-2 for o in (76, 80, 84))


def is_mat64(raw, at):
    m = []
    for k in range(16):
        v = f32(raw, at + k * 4)
        if v is None or not math.isfinite(v) or abs(v) >= 1e7:
            return None
    # 重读成数组
    m = [f32(raw, at + k * 4) for k in range(16)]
    if abs(m[3]) > 1e-3 or abs(m[7]) > 1e-3 or abs(m[11]) > 1e-3 or abs(m[15] - 1.0) > 1e-3:
        return None
    rows = [m[0:3], m[4:7], m[8:11]]
    lens = [np.linalg.norm(r) for r in rows]
    if min(lens) <= 1e-4 or max(lens) / min(lens) > 1.05:
        return None
    for i in range(3):
        for k in range(i + 1, 3):
            if abs(sum(rows[i][t] * rows[k][t] for t in range(3))) > 1e-2:
                return None
    return np.array(m, float).reshape(4, 4)


def is_inf(raw, at, vc):
    n = u32(raw, at)
    if n is None:
        return False
    if n == 0:
        return True
    if n > vc or at + 4 + 8 * n > len(raw):
        return False
    seen = set()
    for k in range(n):
        v = u32(raw, at + 4 + 4 * k)
        if v is None or v >= vc or v in seen:
            return False
        seen.add(v)
    for k in range(n):
        w = f32(raw, at + 4 + 4 * n + 4 * k)
        if w is None or not math.isfinite(w) or w < -1e-3 or w > 1.001:
            return False
    return True


def try_entry(raw, at, vc):
    p = at
    own = record_at(raw, p)
    if own is not None:
        p += NODE_RECORD
    while True:
        if is_u92(raw, p):
            p += 88
            continue
        if is_mat64(raw, p) is not None:
            p += 64
            continue
        n = u32(raw, p)
        if n is not None and is_inf(raw, p, vc):
            p += 4 + 8 * n
            continue
        break
    flag = u32(raw, p)
    if flag is None:
        return None
    p += 4
    nm1 = name_at(raw, p)
    nm2 = name_at(raw, p + 32) if nm1 is not None else None
    if nm1 is None or nm1 != nm2:
        return None
    if own is not None and own[0] != nm1:
        return None
    p += 64
    c = u32(raw, p)
    if c is None or c > 4096:
        return None
    p += 4
    children = []
    for _ in range(c):
        r = record_at(raw, p)
        if r is not None:
            children.append((r[0], r[1]))
            p += NODE_RECORD
        else:
            cn = name_at(raw, p)
            if cn is None:
                return None
            children.append((cn, None))
            p += 32
    return dict(name=nm1, own=own[1] if own else None, children=children), p


def try_sockets(raw, at, vc):
    p = at
    while p < len(raw):
        if u32(raw, p) == 1:
            cnt = u32(raw, p + 4)
            if cnt is not None and cnt <= 4096 and p + 8 + cnt * 128 == len(raw):
                return True
        if is_u92(raw, p):
            p += 88
            continue
        if is_mat64(raw, p) is not None:
            p += 64
            continue
        n = u32(raw, p)
        if n is not None and is_inf(raw, p, vc):
            p += 4 + 8 * n
            continue
        return None
    return None


def parse_tail(path):
    raw = open(path, "rb").read()
    vc = struct.unpack_from("<I", raw, 0x8C)[0]
    starts = []
    for i in range(0, len(raw) - NODE_RECORD):
        r = record_at(raw, i)
        if r is not None and r[0] == "origin":
            starts.append(i)
    for i in range(0, len(raw) - 4 - 64):
        if u32(raw, i) == 0xFFFFFFFF:
            if name_at(raw, i + 4) is not None and name_at(raw, i + 4) == name_at(raw, i + 4 + 32):
                starts.append(i)
    for start in starts:
        p = start
        entries = []
        while p < len(raw):
            got = try_entry(raw, p, vc)
            if got is not None:
                entries.append(got[0])
                p = got[1]
                continue
            r = record_at(raw, p)
            if r is not None:
                p += NODE_RECORD
                continue
            if try_sockets(raw, p, vc):
                p = len(raw)
                break
            break
        if p == len(raw) and entries:
            return entries
    return None


def parse_ani(path):
    raw = open(path, "rb").read()
    bones = struct.unpack_from("<H", raw, 0xBA)[0]
    bones2 = struct.unpack_from("<H", raw, 0xBE)[0]
    frames = struct.unpack_from("<H", raw, 0xC2)[0]
    assert bones == bones2
    names = []
    for i in range(bones):
        slot = raw[0xF0 + i * 30: 0xF0 + (i + 1) * 30]
        end = slot.find(0)
        if end < 0:
            end = 30
        nm = slot[:end]
        ok = nm and all(48 <= c <= 57 or 65 <= c <= 90 or 97 <= c <= 122 or c in b"_.-" for c in nm)
        names.append(nm.decode() if ok else "")
    total = bones * frames * 32
    base = len(raw) - total
    named = sum(1 for x in names if x)
    rests = None
    for n in (named, bones):
        base_r = 0xF0 + n * 30 + 16
        if base_r + bones * 60 > base:
            continue
        cand = []
        ok = True
        for i in range(bones):
            o = base_r + i * 60
            q = struct.unpack_from("<4f", raw, o + 12)
            nn = math.sqrt(sum(v * v for v in q))
            if not (nn < 1e-6 or 0.98 <= nn <= 1.02):
                ok = False
                break
            off = struct.unpack_from("<3f", raw, o + 48)
            cand.append((q, off))
        if ok:
            rests = cand
            break
    tracks = []
    for i in range(bones):
        o = base + i * frames * 32
        poss = struct.unpack_from("<%df" % (frames * 3), raw, o + frames * 16)
        pos = [[poss[3 * f + k] for k in range(3)] for f in range(frames)]
        tracks.append(dict(pos=pos))
    return dict(bones=bones, frames=frames, names=names, rests=rests, tracks=tracks)


def qmat(q):
    x, y, z, w = q
    n = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
    x, y, z, w = x / n, y / n, z / n, w / n
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]], float)


def ang(R):
    c = (np.trace(R) - 1.0) / 2.0
    return math.degrees(math.acos(max(-1.0, min(1.0, c))))


def inv4(m):
    """行主序仿射逆（行向量口径，core mat_inverse_affine 同款）。"""
    R = m[:3, :3]
    t = m[3, :3]
    Ri = R.T  # 正交
    o = np.eye(4)
    o[:3, :3] = Ri
    o[3, :3] = -t @ Ri
    return o


def mul(a, b):
    return a @ b


def run(tag, dirpath):
    say("#" * 72)
    say("=== %s ===" % tag)
    import os
    mesh = None
    for f in os.listdir(dirpath):
        if f.endswith(".mesh"):
            mesh = os.path.join(dirpath, f)
            break
    entries = parse_tail(mesh)
    if entries is None:
        say("  尾部解析失败")
        return
    names = [e["name"] for e in entries]
    idx = {n: i for i, n in enumerate(names)}
    N = len(names)
    parent = [None] * N
    kids = {i: [] for i in range(N)}
    for i, e in enumerate(entries):
        for cn, _ in e["children"]:
            j = idx[cn]
            parent[j] = i
            kids[i].append(j)
    # 绑定矩阵：own 优先，否则孩子槽里的
    binds = [e["own"] for e in entries]
    for e in entries:
        for cn, cb in e["children"]:
            j = idx[cn]
            if cb is not None and binds[j] is None:
                binds[j] = cb
    stored_world = {}
    for j in range(N):
        if binds[j] is not None:
            stored_world[j] = inv4(binds[j])  # 存储值求逆 = bind 世界（行向量口径）
    # .ani 静态区
    anidir = os.path.join(dirpath, "ani")
    anis = sorted(f for f in os.listdir(anidir) if f.endswith(".ani"))
    A = parse_ani(os.path.join(anidir, anis[0]))
    say("  骨 %d · 轨道 %d · 帧 %d · 动作 %d 条（取 %s）" % (N, A["bones"], A["frames"], len(anis), anis[0]))
    # 轨道常量平移（中位数）+ 恒定性
    tmed = {}
    tstd = {}
    for i, nm in enumerate(A["names"]):
        if not nm or nm not in idx:
            continue
        tr = np.array(A["tracks"][i]["pos"])
        tmed[nm] = np.median(tr, axis=0)
        tstd[nm] = float(np.abs(tr - tr.mean(axis=0)).max())
    qrest = {}
    off48 = {}
    for i, nm in enumerate(A["names"]):
        if nm and nm in idx:
            qrest[nm] = A["rests"][i][0]
            off48[nm] = A["rests"][i][1]
    # 轨道名单与骨架骨集的覆盖
    missing_track = [names[j] for j in range(N) if names[j] not in tmed]
    say("  无轨道的骨: %s" % missing_track)

    # ---- 干净骨语义自检（记录骨 + 父记录骨）----
    rot_hits = rot_miss = tr_hits = tr_miss = 0
    rot_miss_names, tr_miss_names = [], []
    for j in range(N):
        p = parent[j]
        if binds[j] is None or p is None or binds[p] is None:
            continue
        if names[j] not in qrest:
            continue
        bl = mul(stored_world[j], inv4(stored_world[p]))  # 行向量局部 = W_child · W_parent⁻¹
        pred = qmat(qrest[names[j]])  # 行向量口径下的重建旋转 = qmat(qrest)
        dR = ang(bl[:3, :3] @ pred.T)
        if dR <= 0.1:
            rot_hits += 1
        else:
            rot_miss += 1
            rot_miss_names.append(names[j])
        if names[j] in tmed:
            dT = float(np.linalg.norm(bl[3, :3] - tmed[names[j]]))
            if dT <= 1e-3:
                tr_hits += 1
            else:
                tr_miss += 1
                tr_miss_names.append((names[j], dT))
    say("  自检（干净骨）: qrest 旋转命中 %d/%d miss=%s" % (rot_hits, rot_hits + rot_miss, rot_miss_names))
    say("               轨道t==bind局部t 命中 %d/%d miss=%s" % (tr_hits, tr_hits + tr_miss,
        [(n, round(d, 4)) for n, d in tr_miss_names]))

    # ---- 重建（行向量口径）----
    # L_rec(j)（行向量）：旋转 = qmat(qrest)；平移 = 轨道常量 t；根运动骨（轨道不恒定）用 off48(父)
    L_rec = {}
    src = {}
    for j in range(N):
        nm = names[j]
        rot = qmat(qrest[nm]) if nm in qrest else np.eye(3)
        t = None
        if nm in tmed and tstd.get(nm, 0) < 1e-3:
            t = tmed[nm]
        elif nm in tmed and parent[j] is not None and names[parent[j]] in off48:
            t = np.array(off48[names[parent[j]]])  # 根运动骨：父骨 off48
        L = np.eye(4)
        L[:3, :3] = rot
        if t is not None:
            L[3, :3] = t
        L_rec[j] = L
    W = {}
    src = {}
    # 第一遍：记录骨直接用存储逆；第二遍定点迭代：child-solve / fallback
    for j in range(N):
        if binds[j] is not None:
            W[j] = stored_world[j]
            src[j] = "stored"
    for _ in range(N + 1):
        progress = False
        for j in range(N):
            if j in W:
                continue
            p = parent[j]
            rec_kids = [c for c in kids[j] if binds[c] is not None]
            if rec_kids:
                cands = []
                for c in rec_kids:
                    cands.append((c, mul(inv4(L_rec[c]), W[c])))  # W_parent = L_child⁻¹ · W_child
                W[j] = cands[0][1]
                src[j] = "child:%s" % names[cands[0][0]]
                if len(cands) > 1:
                    for c, w2 in cands[1:]:
                        dR = ang(w2[:3, :3] @ W[j][:3, :3].T)
                        dT = float(np.linalg.norm(w2[3, :3] - W[j][3, :3]))
                        say("    交叉验证 %s 经 %s vs %s: dR=%.4f° dT=%.6f" %
                            (names[j], names[cands[0][0]], names[c], dR, dT))
                progress = True
            elif p is not None and p in W:
                W[j] = mul(L_rec[j], W[p])  # W_j = L_j · W_parent
                src[j] = "fallback"
                progress = True
        if not progress:
            break
    # 参考锚点：关键记录骨的存储世界位
    for nm in ("bip01", "bip01_pelvis", "bip01_spine", "bip01_r_clavicle", "bip01_l_hand",
               "bip01_r_hand", "bip01_l_calf", "bip01_r_calf", "bone05", "bip01_l_upperarm"):
        j = idx.get(nm)
        if j is not None and j in stored_world:
            t = stored_world[j][3, :3]
            say("    [stored] %-20s pos=(%.4f,%.4f,%.4f)" % (nm, t[0], t[1], t[2]))

    # 两种重建变体：A=child-solve 优先（k4 原样）；B=fallback 优先（只在无父世界时 child-solve）
    def rebuild(child_first):
        W2 = {}
        for j in range(N):
            if binds[j] is not None:
                W2[j] = stored_world[j]
        for _ in range(N + 1):
            progress = False
            for j in range(N):
                if j in W2:
                    continue
                p = parent[j]
                if binds[j] is not None:
                    W2[j] = stored_world[j]
                    progress = True
                    continue
                rec_kids = [c for c in kids[j] if binds[c] is not None]
                fb_ok = p is not None and p in W2
                use_child = rec_kids and (child_first or not fb_ok)
                if use_child:
                    c = rec_kids[0]
                    W2[j] = mul(inv4(L_rec[c]), W2[c])
                    progress = True
                elif fb_ok:
                    W2[j] = mul(L_rec[j], W2[p])
                    progress = True
            if not progress:
                break
        return W2

    def mirror_name(nm):
        if "_l_" in nm:
            return nm.replace("_l_", "_r_")
        return None

    for tag2, cf in (("A child优先", True), ("B fallback优先", False)):
        W2 = rebuild(cf)
        say("  --- 变体 %s ---" % tag2)
        for j in range(N):
            if binds[j] is not None or j not in W2:
                continue
            p = parent[j]
            tp = W2[p][3, :3] if p is not None and p in W2 else np.zeros(3)
            d = float(np.linalg.norm(W2[j][3, :3] - tp))
            tc = tmed.get(names[j])
            dtc = ("  |Δ|vs轨道常量 %.4f(%.4f)" % (d, float(np.linalg.norm(tc)))) if tc is not None else ""
            say("    %-24s pos=(%.4f,%.4f,%.4f) 父距 %.4f%s" %
                (names[j], W2[j][3, :3][0], W2[j][3, :3][1], W2[j][3, :3][2], d, dtc))
        # 镜像对称：重建骨与其对侧记录骨的 y/z 应同、x 反号
        for j in range(N):
            if binds[j] is not None or j not in W2:
                continue
            mn = mirror_name(names[j])
            if not mn or mn not in idx:
                continue
            k = idx[mn]
            if binds[k] is None or k not in W2:
                continue
            a, b = W2[j][3, :3], W2[k][3, :3]
            say("    镜像 %s vs %s(存储): dx=%.4f dy=%.4f dz=%.4f" %
                (names[j], mn, a[0] + b[0], a[1] - b[1], a[2] - b[2]))
    # 骨线数：改前（父+子都有记录）/ 改后（重建补上）
    WA = rebuild(True)
    WB = rebuild(False)
    before = sum(1 for j in range(N) if parent[j] is not None and binds[j] is not None and binds[parent[j]] is not None)
    afterA = sum(1 for j in range(N) if parent[j] is not None and j in WA and parent[j] in WA)
    afterB = sum(1 for j in range(N) if parent[j] is not None and j in WB and parent[j] in WB)
    say("  骨线: 改前 %d -> A %d / B %d" % (before, afterA, afterB))
    bad = [names[j] for j in range(N) if j in WB and not np.all(np.isfinite(WB[j]))]
    say("  非有限值: %s" % (bad or "无"))


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "debug":
    import os
    d = MESHES["xiyuqiezei"]
    mesh = None
    for f in os.listdir(d):
        if f.endswith(".mesh"):
            mesh = os.path.join(d, f)
            break
    entries = parse_tail(mesh)
    print("entries:", len(entries))
    names = [e["name"] for e in entries]
    print("first 6:", names[:6])
    print("own records:", sum(1 for e in entries if e["own"] is not None))
    print("child-slot records:", sum(1 for e in entries for cn, cb in e["children"] if cb is not None))
    for i in range(3):
        print("children of %s:" % names[i], [(cn, cb is not None) for cn, cb in entries[i]["children"]])
    sys.exit(0)

if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "debug2":
    import os
    d = MESHES["xiyuqiezei"]
    mesh = None
    for f in os.listdir(d):
        if f.endswith(".mesh"):
            mesh = os.path.join(d, f)
            break
    entries = parse_tail(mesh)
    names = [e["name"] for e in entries]
    idx = {n: i for i, n in enumerate(names)}
    for i, e in enumerate(entries):
        if e["name"] in ("bip01_pelvis", "bip01_spine", "bip01_spine1", "bip01_neck", "bip01_head",
                         "bip01_l_clavicle", "bip01_r_clavicle", "bip01_l_upperarm", "bone05",
                         "bip01_l_thigh", "bip01_l_calf", "bip01_l_foot"):
            print("%-22s kids: %s" % (e["name"], [(cn, cb is not None) for cn, cb in e["children"]]))
    sys.exit(0)

for tag, d in MESHES.items():
    run(tag, d)
open(r"D:\TLGL\.scratch\rest_probe.txt", "w", encoding="utf-8").write("\n".join(OUT) + "\n")
print("saved -> rest_probe.txt")
