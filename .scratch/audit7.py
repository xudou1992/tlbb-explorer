# -*- coding: utf-8 -*-
import sqlite3, re, collections, sys
sys.stdout.reconfigure(encoding='utf-8')
PRIM = {}
for l in open('pinyin_map.tsv', encoding='utf-8'):
    a, b = l.rstrip('\n').split('\t'); PRIM[a] = b
SEP = re.compile(r'[_\-/. ]')
def norm(s): return SEP.sub('', (s or '').lower())
db = sqlite3.connect('file:resources.db?mode=ro', uri=True)
G = list(db.execute('select id, kind, stem, dir from agroups'))
GA = []
for i, k, s, d in G:
    leaf = (d or '').rstrip('/').split('/')[-1]
    GA.append((i, k, s or '', leaf, norm(s or ''), norm(leaf)))
def tokstarts(s):
    """positions in norm(s) where a token begins"""
    pos = set(); j = 0
    for t in re.split(r'[_\-.]', s):
        if t:
            pos.add(j); j += len(norm(t))
        else:
            j += 0
    return pos
CACHE = [(gid, kind, stem, leaf, hs, hl, tokstarts(stem), tokstarts(leaf)) for gid, kind, stem, leaf, hs, hl in GA]
def free(n):
    n = norm(n); return [g for g in CACHE if n and (n in g[4] or n in g[5])]
def anchored(n):
    n = norm(n)
    out = []
    if not n: return out
    for g in CACHE:
        ok = False
        for idx, h, st in ((2, g[4], g[6]), (3, g[5], g[7])):
            p = h.find(n)
            while p != -1:
                if p in st or p == 0:
                    ok = True; break
                p = h.find(n, p + 1)
        if ok: out.append(g)
    return out
REAL = ['武器','坐骑','结婚','建筑','时装','石门','石头','天地','曹霜','慕容','天山','逍遥','少林','大理','段誉','虚竹','星宿','音乐','弹指','长枪','门派','恶人','药师','铁匠','守卫','无相','刀客','白猿','高山','女子','银近','剑皮','暗椅','的蓝','魂触','火要','诗他','美女','少女','绿']
JUNK = ['暗椅','的拉','的蓝','魂触','暗触','火要','法触','的了','踢花','踢游','魂打','暗里','树暗','魂魂','气白','银近','剑皮']
print('%-6s %8s %8s' % ('词', '自由子串', '段首锚定'))
f = a = 0
for w in REAL:
    if any(c not in PRIM for c in w):
        print('  %-5s (缺字)' % w); continue
    p = ''.join(PRIM[c] for c in w)
    nf = len(free(p)); na = len(anchored(p))
    f += nf; a += na
    print('  %-6s %8d %8d' % (w, nf, na))
print('  REAL 合计 自由 %d → 锚定 %d (保留 %.0f%%)' % (f, a, 100.0*a/max(f,1)))
jf = ja = 0
for w in JUNK:
    p = ''.join(PRIM[c] for c in w)
    jf += len(free(p)); ja += len(anchored(p))
print('  已知假命中词 合计 自由 %d → 锚定 %d (消掉 %.0f%%)' % (jf, ja, 100.0*(jf-ja)/max(jf,1)))
for w in JUNK[:6]:
    p = ''.join(PRIM[c] for c in w)
    print('    %-4s %-8s 自由 %3d 锚定 %3d  %s' % (w, p, len(free(p)), len(anchored(p)), [g[2] for g in anchored(p)][:2]))
print('\n女/绿 ü: free("nü")=%d free("nv")=%d anchored("nv")=%d  例:%s' % (len(free('nü')), len(free('nv')), len(anchored('nv')), [g[2] for g in anchored('nv')][:2]))
print('例: anchored("caoshuang")=%s  anchored("yinyue")=%s  anchored("wuqi")=%d' % ([g[2] for g in anchored('caoshuang')], [g[2] for g in anchored('yinyue')], len(anchored('wuqi'))))
