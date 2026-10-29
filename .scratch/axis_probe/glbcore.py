"""共用解析层：读 GLB，产出 46 骨的 IBM 原矩阵 / 派生世界矩阵 / 蒙皮重心。"""
import json, struct, math, pathlib
import numpy as np

GLB = pathlib.Path(r"D:\TLGL\.scratch\glb_rigged\m_db18794d0000cd38.glb")
CT = {5120: "b", 5121: "B", 5122: "h", 5123: "H", 5125: "I", 5126: "f"}
NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}

def load():
    data = GLB.read_bytes()
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
    fmt = "<" + CT[a["componentType"]] * NCOMP[a["type"]]
    stride = bv.get("byteStride") or struct.calcsize(fmt)
    o = np.empty((a["count"], NCOMP[a["type"]]), dtype=np.float64)
    for i in range(a["count"]):
        o[i] = struct.unpack_from(fmt, BIN, base + i * stride)
    return o

def affine_inv4(m):
    R = m[:3, :3]; t = m[:3, 3]; Ri = np.linalg.inv(R)
    o = np.eye(4); o[:3, :3] = Ri; o[:3, 3] = -Ri @ t; return o

def quat_mat(q):
    x, y, z, w = q; n = math.sqrt(x*x+y*y+z*z+w*w); x, y, z, w = x/n, y/n, z/n, w/n
    return np.array([[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                     [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                     [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]])

def build():
    g, BIN = load()
    prim = g["meshes"][0]["primitives"][0]
    POS = read_acc(g, BIN, prim["attributes"]["POSITION"])
    JOI = read_acc(g, BIN, prim["attributes"]["JOINTS_0"])
    WEI = read_acc(g, BIN, prim["attributes"]["WEIGHTS_0"])
    NODES = g["nodes"]; JOINTS = g["skins"][0]["joints"]; NJ = len(JOINTS)
    Mraw = read_acc(g, BIN, g["skins"][0]["inverseBindMatrices"]).reshape(NJ, 4, 4, order="F")  # GLB 里的 "IBM"
    W = np.stack([affine_inv4(Mraw[j]) for j in range(NJ)])                                    # 管线认定的 bind 世界矩阵
    names = [NODES[ni]["name"] for ni in JOINTS]
    parents = {}
    for ni, n in enumerate(NODES):
        for c in n.get("children", []): parents[c] = ni
    jpar = [(JOINTS.index(parents[ni]) if (ni in parents and parents[ni] in JOINTS) else -1) for ni in JOINTS]
    Wm = np.zeros((len(POS), NJ))
    for s in range(4):
        np.add.at(Wm, (np.arange(len(POS)), JOI[:, s].astype(int)), WEI[:, s])
    return dict(g=g, BIN=BIN, POS=POS, JOI=JOI, WEI=WEI, NODES=NODES, JOINTS=JOINTS, NJ=NJ,
                Mraw=Mraw, W=W, names=names, parents=parents, jpar=jpar, Wm=Wm)

def centroids(D, exclude_root_only=True, ROOT=None):
    POS, Wm = D["POS"], D["Wm"]
    wsum = Wm.sum(1); mx = Wm.max(1); amax = Wm.argmax(1)
    if ROOT is None:
        cnt = {j: int(((amax == j) & (mx > 0.999) & (wsum > 0.999)).sum()) for j in range(D["NJ"])}
        ROOT = max(cnt, key=cnt.get)
    used = (wsum > 0.999) & ( ~( (mx > 0.999) & (amax == ROOT) ) if exclude_root_only else True)
    V = POS[used]; Wv = Wm[used]
    NJ = D["NJ"]
    C = np.zeros((NJ, 3)); S = np.zeros(NJ); N = np.zeros(NJ, int); cov = np.zeros(NJ, bool)
    for j in range(NJ):
        w = Wv[:, j]; sel = w > 0
        if sel.any():
            C[j] = (V[sel] * w[sel, None]).sum(0) / w[sel].sum(); S[j] = w[sel].sum(); N[j] = int(sel.sum()); cov[j] = True
    return C, S, N, cov, ROOT, int(used.sum())
