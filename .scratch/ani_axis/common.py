"""共用解析层：读当前 GLB（已翻案版），产出 bind 世界 B / IBM=B^-1 / 动画局部 TRS。

语义：skins[0].inverseBindMatrices = B^{-1}；nodes[1+j] 静态 TRS = bind 局部；
沿 node 树复合 = bind 世界 B_j；列向量蒙皮 M_j(f) = G_j(f) · IBM_j（= 引擎 row 口径 B^{-1}·world）。
"""
import json, struct, math
import numpy as np

GLB = r"D:\TLGL\.scratch\glb_rigged\m_db18794d0000cd38.glb"
CT = {5120: "b", 5121: "B", 5122: "h", 5123: "H", 5125: "I", 5126: "f"}
NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def load_glb(path=GLB):
    data = open(path, "rb").read()
    assert struct.unpack_from("<III", data, 0)[0] == 0x46546C67
    off, g, BIN = 12, None, b""
    while off + 8 <= len(data):
        clen, ctype = struct.unpack_from("<II", data, off); off += 8
        chunk = data[off:off + clen]; off += clen
        if ctype == 0x4E4F534A: g = json.loads(chunk.decode("utf-8"))
        elif ctype == 0x004E4942: BIN = chunk
    return g, BIN


def read_acc(g, BIN, ai):
    a = g["accessors"][ai]; bv = g["bufferViews"][a["bufferView"]]
    base = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    n = NCOMP[a["type"]]
    fmt = "<" + CT[a["componentType"]] * n
    stride = bv.get("byteStride") or struct.calcsize(fmt)
    o = np.empty((a["count"], n), dtype=np.float64)
    for i in range(a["count"]):
        o[i] = struct.unpack_from(fmt, BIN, base + i * stride)
    return o


def quat_mat(q):
    x, y, z, w = q
    n = math.sqrt(x * x + y * y + z * z + w * w)
    if n == 0: return np.eye(3)
    x, y, z, w = x / n, y / n, z / n, w / n
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def trs_mat(t, q, s):
    M = np.eye(4)
    M[:3, :3] = quat_mat(q) * np.asarray(s, float)[None, :]
    M[:3, 3] = t
    return M


def affine_inv4(m):
    R = m[:3, :3]; t = m[:3, 3]; Ri = np.linalg.inv(R)
    o = np.eye(4); o[:3, :3] = Ri; o[:3, 3] = -Ri @ t
    return o


def build():
    g, BIN = load_glb()
    prim = g["meshes"][0]["primitives"][0]
    POS = read_acc(g, BIN, prim["attributes"]["POSITION"])
    JOI = read_acc(g, BIN, prim["attributes"]["JOINTS_0"]).astype(int)
    WEI = read_acc(g, BIN, prim["attributes"]["WEIGHTS_0"])
    NODES = g["nodes"]; JOINTS = g["skins"][0]["joints"]; NJ = len(JOINTS)
    IBM = read_acc(g, BIN, g["skins"][0]["inverseBindMatrices"]).reshape(NJ, 4, 4, order="F")
    names = [NODES[ni]["name"] for ni in JOINTS]
    jof = {ni: j for j, ni in enumerate(JOINTS)}
    par = {}
    for ni, n in enumerate(NODES):
        for c in n.get("children", []): par[c] = ni
    jpar = [jof.get(par.get(ni, -1), -1) for ni in JOINTS]
    blocal = np.stack([trs_mat(NODES[ni].get("translation", [0, 0, 0]),
                               NODES[ni].get("rotation", [0, 0, 0, 1]),
                               NODES[ni].get("scale", [1, 1, 1])) for ni in JOINTS])
    B = np.zeros_like(blocal)
    todo = set(range(NJ))
    for _ in range(NJ + 2):
        for j in list(todo):
            p = jpar[j]
            if p < 0:
                B[j] = blocal[j]; todo.discard(j)
            elif p not in todo:
                B[j] = B[p] @ blocal[j]; todo.discard(j)
    Binv = np.stack([affine_inv4(B[j]) for j in range(NJ)])
    Wm = np.zeros((len(POS), NJ))
    for s in range(4):
        np.add.at(Wm, (np.arange(len(POS)), JOI[:, s]), WEI[:, s])
    mx = Wm.max(1); amax = Wm.argmax(1); wsum = Wm.sum(1)
    root_only = (mx > 0.999) & (amax == 0) & (wsum > 0.999)
    return dict(g=g, BIN=BIN, POS=POS, JOI=JOI, WEI=WEI, NODES=NODES, JOINTS=JOINTS, NJ=NJ,
                names=names, jpar=jpar, blocal=blocal, B=B, IBM=IBM, Binv=Binv, Wm=Wm,
                root_only=root_only, wsum=wsum, par=par, jof=jof)


def read_anims(D):
    """-> {anim_name: {joint: {path: (times, out)}}}，并记录每段帧数。"""
    g, BIN = D["g"], D["BIN"]
    res = {}
    for A in g["animations"]:
        per = {}
        for c in A["channels"]:
            ni = c["target"]["node"]
            if ni not in D["jof"]: continue
            j = D["jof"][ni]
            sam = A["samplers"][c["sampler"]]
            inp = read_acc(g, BIN, sam["input"])[:, 0]
            out = read_acc(g, BIN, sam["output"])
            per.setdefault(j, {})[c["target"]["path"]] = (inp, out)
            per[j]["_interp"] = sam.get("interpolation", "LINEAR")
        res[A.get("name")] = per
    return res


def anim_keyframe(per, j, path, f, ncomp, fill):
    d = per.get(j)
    if not d or path not in d: return fill
    inp, out = d[path]
    k = f if f < len(out) else len(out) - 1
    return out[k]
