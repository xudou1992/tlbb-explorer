"""probe6.py — 动画是否落在与 bind 同一空间：S_j(f)=W_j(f)·IBM_j 的平移量 & 全帧最小位移"""
import json, struct, math, pathlib
import numpy as np
import glbcore as G
p3 = __import__("importlib").import_module("probe3") if False else None
data = G.GLB.read_bytes(); off, g, BIN = 12, None, b""
while off + 8 <= len(data):
    clen, ctype = struct.unpack_from("<II", data, off); off += 8
    ch = data[off:off+clen]; off += clen
    if ctype == 0x4E4F534A: g = json.loads(ch.decode("utf-8"))
    elif ctype == 0x004E4942: BIN = ch
CT = {5126: "f", 5123: "H"}; NC = {"SCALAR":1,"VEC3":3,"VEC4":4,"MAT4":16}
def acc(ai):
    a = g["accessors"][ai]; bv = g["bufferViews"][a["bufferView"]]
    base = bv.get("byteOffset",0)+a.get("byteOffset",0); fmt = "<"+CT[a["componentType"]]*NC[a["type"]]
    stride = bv.get("byteStride") or struct.calcsize(fmt)
    return np.array([struct.unpack_from(fmt, BIN, base+i*stride) for i in range(a["count"])], dtype=float)
prim = g["meshes"][0]["primitives"][0]
POS = acc(prim["attributes"]["POSITION"]); JOI = acc(prim["attributes"]["JOINTS_0"]).astype(int); WEI = acc(prim["attributes"]["WEIGHTS_0"])
NODES = g["nodes"]; JOINTS = g["skins"][0]["joints"]; NJ=len(JOINTS)
Mraw = acc(g["skins"][0]["inverseBindMatrices"]).reshape(NJ,4,4,order="F")
names = [NODES[ni]["name"] for ni in JOINTS]
def qm(q):
    x,y,z,w = q; n=math.sqrt(x*x+y*y+z*z+w*w); x,y,z,w=x/n,y/n,z/n,w/n
    return np.array([[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)],[2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)],[2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)]])
def lm(ni, over=None):
    n = over if over is not None else NODES[ni]; m=np.eye(4)
    m[:3,:3] = qm(n.get("rotation",[0,0,0,1]))*np.array(n.get("scale",[1,1,1])); m[:3,3]=n.get("translation",[0,0,0]); return m
parents={}
for ni,n in enumerate(NODES):
    for c in n.get("children",[]): parents[c]=ni
def world(ni, ov):
    chain=[]
    while True:
        chain.append(ni)
        if ni not in parents: break
        ni=parents[ni]
    m=np.eye(4)
    for a in reversed(chain): m = m @ (ov.get(a, lm(a)))
    return m
print("%-14s %6s %9s %9s %9s %9s" % ("anim","frame","meanDisp","maxDisp","mean|tS|","min|tS|"))
allmin=[]
for a in g["animations"]:
    chmap={}
    for c in a["channels"]: chmap.setdefault(c["target"]["node"],{})[c["target"]["path"]]=c["sampler"]
    best=None
    for fr in range(21):
        ov={}
        for ni,paths in chmap.items():
            cur=dict(NODES[ni])
            for pth,si in paths.items():
                s=a["samplers"][si]; O=acc(s["output"]); k=min(fr,len(O)-1)
                cur[{"rotation":"rotation","translation":"translation","scale":"scale"}[pth]] = O[k]
            ov[ni]=lm(ni, cur)
        S=np.stack([world(JOINTS[j],ov)@Mraw[j] for j in range(NJ)])
        disp=np.zeros_like(POS)
        for slot in range(4):
            idx=JOI[:,slot]; wq=WEI[:,slot]
            disp += wq[:,None]*(np.einsum("nij,nj->ni",S[idx,:3,:3],POS)+S[idx,:3,3])
        d=np.linalg.norm(disp-POS,axis=1)
        tS=np.linalg.norm(S[:,:3,3],axis=1)
        cover = np.array([ (WEI[:, i] if False else 0) for i in range(0)])
        rec=(float(d.mean()), float(d.max()), float(tS.mean()), float(tS.min()), fr)
        if best is None or rec[0]<best[0]: best=rec
        if a is g["animations"][0] and fr in (0,1,2,20):
            print("%-14s %6d %9.4f %9.4f %9.4f %9.4f" % (a["name"], fr, *rec[:4]))
    print("%-14s %6s %9.4f %9.4f %9.4f %9.4f   <- 全部 21 帧里最接近静置的那帧" % (a["name"], best[4], *best[:4]))
    allmin.append(best)
A=np.array([x[:4] for x in allmin])
print("\n15 段动画的 '最接近静置帧' 统计: mean位移 min=%.4f med=%.4f max=%.4f | mean|t(S_j)| min=%.4f med=%.4f" % (
    A[:,0].min(), np.median(A[:,0]), A[:,0].max(), A[:,2].min(), np.median(A[:,2])))
print("=> 若动画与 bind 同空间，应存在某帧 mean位移≈0 且 |t(S_j)|≈0；实测最小 mean位移=%.4f" % A[:,0].min())
