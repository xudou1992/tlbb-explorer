"""probe5.py — 指标口径核对：主 agent 的 1.84 来自哪种统计"""
import numpy as np, glbcore as G
D = G.build(); NJ=D["NJ"]; Mraw=D["Mraw"]; W=D["W"]; POS=D["POS"]; Wm=D["Wm"]
tC = np.stack([Mraw[j][:3,3] for j in range(NJ)]); tA = W[:,:3,3]
C,S,N,cov,ROOT,nused = G.centroids(D, True)
fit = np.array([j for j in np.where(cov)[0] if j != ROOT])
def rep(lbl, d): print("   %-42s n=%3d mean=%.4f med=%.4f max=%.4f" % (lbl, len(d), d.mean(), np.median(d), d.max()))
rep("A 逐骨等权 |t-c| (26骨, 干净重心)", np.linalg.norm(tA[fit]-C[fit],axis=1))
wv = S[fit]/S[fit].sum(); rep("A 逐骨 Σw 加权", np.linalg.norm(tA[fit]-C[fit],axis=1))
print("   A 逐骨 Σw 加权 mean=%.4f" % float((wv*np.linalg.norm(tA[fit]-C[fit],axis=1)).sum()))
rep("A 逐骨等权(含根骨 27)", np.linalg.norm(tA[np.where(cov)[0]]-C[np.where(cov)[0]],axis=1))
rep("C 逐骨等权 |t-c| (26骨)", np.linalg.norm(tC[fit]-C[fit],axis=1))
# 顶点-骨 配对统计
pairs=[]
for j in fit:
    w = Wm[:, j]; sel = (w>0) & (Wm.max(1)<=0.999)
    if sel.any():
        d = np.linalg.norm(POS[sel]-tA[j],axis=1)
        pairs.append(np.average(d, weights=w[sel]))
rep("A: 每骨 '加权顶点到骨原点' 距离的均值", np.array(pairs))
dA=[]; 
for j in fit:
    w=Wm[:,j]; sel=(w>0)&(Wm.max(1)<=0.999)
    if sel.any(): dA += list(np.linalg.norm(POS[sel]-tA[j],axis=1)*w[sel]/w[sel])
rep("A: 全部顶点-骨配对(等权)距离", np.array(dA))
print("\n注: 顶点-骨配对统计与逐骨重心统计口径不同, 前者把整段网格顶点都算进来, 数值天然更大。")
