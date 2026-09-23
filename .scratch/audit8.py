# -*- coding: utf-8 -*-
import sqlite3, re, collections, sys, functools
sys.stdout.reconfigure(encoding='utf-8')
PRIM = {}
for l in open('pinyin_map.tsv', encoding='utf-8'):
    a, b = l.rstrip('\n').split('\t'); PRIM[a] = b
SYL = set(PRIM.values())
SEP = re.compile(r'[_\-/. ]')
def norm(s): return SEP.sub('', (s or '').lower())

@functools.lru_cache(maxsize=200000)
def cuts(tok):
    """cut positions (in normalized token) reachable by a full pinyin segmentation"""
    out = set()
    n = len(tok)
    reach = [False]*(n+1); reach[0] = True
    stack = [0]
    # DP over all segmentations
    ways = [[] for _ in range(n+1)]
    ways[0] = [()]
    for i in range(n):
        if not ways[i]: continue
        for L in range(1, min(8, n-i)+1):
            if tok[i:i+L] in SYL:
                ways[i+L].append(i)
                reach[i+L] = True
    if not reach[n]:
        return out
    for i in range(n+1):
        if ways[i]:
            out.add(i)
    return out

def cuts_for(s):
    """absolute cut positions in norm(s)"""
    pos = set([0]); j = 0
    for t in re.split(r'[_\-.]', s):
        t = norm(t)
        if not t:
            continue
        pos.add(j)
        for c in cuts(t):
            pos.add(j+c)
        j += len(t)
    return pos

db = sqlite3.connect('file:resources.db?mode=ro', uri=True)
CACHE = []
for i, k, s, d in db.execute('select id,kind,stem,dir from agroups'):
    leaf = (d or '').rstrip('/').split('/')[-1]
    CACHE.append((i, k, s or '', leaf, norm(s or ''), norm(leaf), cuts_for(s or ''), cuts_for(leaf)))

def match(needle, start_only=True):
    n = norm(needle); out = []
    if not n: return out
    for gid, kind, stem, leaf, hs, hl, cs, cl in CACHE:
        ok = False
        for h, cc in ((hs, cs), (hl, cl)):
            p = h.find(n)
            while p != -1:
                e = p + len(n)
                if p in cc and (not start_only or True) and (e in cc or e == len(h) or h[e].isdigit()):
                    ok = True; break
                p = h.find(n, p+1)
        if ok: out.append((gid, stem, leaf))
    return out
def free(needle):
    n = norm(needle)
    return [(g[0], g[2], g[3]) for g in CACHE if n and (n in g[4] or n in g[5])]

REAL = ['武器','坐骑','结婚','建筑','时装','石门','石头','曹霜','慕容','天山','逍遥','少林','段誉','虚竹','门派','铁匠','无相','高山','白猿','诗他','银近']
JUNK = ['暗椅','的拉','的蓝','魂触','暗触','火要','法触','的了','踢花','踢游','魂打','暗里','树暗','魂魂','气白','剑皮']
tf = ts = jf = js = 0
for w in REAL:
    p = ''.join(PRIM[c] for c in w)
    a, b = free(p), match(p)
    tf += len(a); ts += len(b)
    if len(a) != len(b): print('  REAL %-5s %-11s 自由 %3d 音节对齐 %3d  剩:%s' % (w, p, len(a), len(b), [x[1] for x in b][:2]))
for w in JUNK:
    p = ''.join(PRIM[c] for c in w)
    a, b = free(p), match(p)
    jf += len(a); js += len(b)
print('REAL: %d → %d (保留 %.0f%%)   JUNK: %d → %d (消掉 %.0f%%)' % (tf, ts, 100.0*ts/tf, jf, js, 100.0*(jf-js)/jf))
print(' nv:', len(match('nv')), ' caoshuang:', [x[1] for x in match('caoshuang')], ' yinyuelang:', [x[1] for x in match('yinyue')])
print(' anyi 剩:', [x[1] for x in match('anyi')][:6], ' delan 剩:', [x[1] for x in match('delan')][:4])

# leaf 污染：leaf 与 stem 完全不同名
def related(stem, leaf):
    a, b = norm(stem), norm(leaf)
    return a.startswith(b) or b.startswith(a) or a == b
cont = [g for g in CACHE if g[5] and not related(g[2], g[3])]
print('与 stem 不同名的目录末段组数:', len(cont), '/', len(CACHE))
for w in ['白猿','高山']:
    p = ''.join(PRIM[c] for c in w)
    allh = free(p)
    clean = [g for g in allh if p in norm(g[1]) or related(g[1], g[2])]
    print('  %s: 自由 %d 去掉无关末段后 %d' % (w, len(allh), len(clean)))
