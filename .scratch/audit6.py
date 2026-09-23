# -*- coding: utf-8 -*-
import sqlite3, re, collections, sys, itertools
sys.stdout.reconfigure(encoding='utf-8')
PRIM = {}
for l in open('pinyin_map.tsv', encoding='utf-8'):
    a, b = l.rstrip('\n').split('\t'); PRIM[a] = b
SEP = re.compile(r'[_\-/. ]')
def norm(s): return SEP.sub('', (s or '').lower())
db = sqlite3.connect('file:resources.db?mode=ro', uri=True)
G = list(db.execute('select id, kind, stem, dir from agroups'))
GA = [(i, k, s or '', d or '', norm(s), norm((d or '').rstrip('/').split('/')[-1])) for i, k, s, d in G]
def hits(n):
    n = norm(n); return [g for g in GA if n and (n in g[4] or n in g[5])]

# (iii) 整段命中 vs 仅子串命中
COMMON = ''.join(sorted(set('的一是不了人在有为之大来以个中上到说国和地也子时道会要于下得可年生自回其爱着行功过学加法海式好认内应此进主平风火水木金土石雨雪花月星日夜明暗长短老少年小多少全黑白红绿蓝紫青黄金银铜铁刀剑枪弓甲盾牌城池村寨镇庙殿楼阁台塔桥路街口门房屋窗床桌椅琴棋书画诗酒茶饭鱼肉果花草树木根枝叶果实种子壳皮毛骨肉筋骨血脉气灵魂鬼神妖魔仙佛道法术符阵功夫武勇猛烈轻便快慢迟速远近高低上下左右前后内外里中游行走立坐卧睡醒见闻触摸抓拿打踢推拉扯扔抛飞跳跃跑爬滚翻旋转直')))
def tokens(s):
    return [norm(t) for t in re.split(r'[_\-.]', s) if t]
print('=== (iii) 命中质量：needle 是否为完整段 ===')
def classify(ws):
    full = sub = 0
    ex = []
    for w in ws:
        if any(c not in PRIM for c in w): continue
        p = ''.join(PRIM[c] for c in w)
        for g in hits(p):
            toks = tokens(g[2]) + tokens(g[3].rstrip('/').split('/')[-1])
            if p in toks:
                full += 1
            else:
                sub += 1
                if len(ex) < 6: ex.append((w, p, g[2]))
    return full, sub, ex
real = ['武器','坐骑','结婚','建筑','时装','石门','石头','天地','女人','少女','美女','绿色','星宿','音乐','弹指','曹霜','慕容','天山','逍遥','少林','大理','段誉','虚竹','王语嫣','木婉清','钟灵','萧峰','门派','恶人','刀客','弓手','药师','铁匠','商人','守卫','首领','帮主']
f, s, ex = classify(real)
print('   30+ 个真实词: 整段命中 %d, 仅子串命中 %d (%.0f%% 可能是误报) 例:%s' % (f, s, 100.0*s/(f+s+1e-9), ex[:4]))
import random
random.seed(20260922)
rw = [random.choice(COMMON) + random.choice(COMMON) for _ in range(200)]
f, s, ex = classify(rw)
print('   200 个随机两字: 整段命中 %d, 仅子串命中 %d (%.0f%%) 例:%s' % (f, s, 100.0*s/(f+s+1e-9), ex[:5]))
print('   诗他 shita 命中:', [(g[2], g[3].rstrip('/').split('/')[-1]) for g in hits('shita')][:6])
print('   美女 meinü/meinv:', len(hits('meinü')), len(hits('meinv')), [g[2] for g in hits('meinv')])
print('   少女:', len(hits('shaonü')), len(hits('shaonv')), [g[2] for g in hits('shaonv')][:3])

# (i) 跨段 junction 假命中（穷举 2 字常见词）
print('\n=== (i) 只在跨 _ 边界才成立的 2 字查询 ===')
needles = {}
for a in COMMON:
    for b in COMMON:
        needles[PRIM[a] + PRIM[b]] = a + b
junction = collections.defaultdict(set)
for gid, kind, stem, dir_, hs, hl in GA:
    for src in (stem, dir_.rstrip('/').split('/')[-1]):
        tk = tokens(src)
        joined = norm(src)
        toks_set = set(tk)
        for i in range(len(tk) - 1):
            A, B = tk[i], tk[i + 1]
            for x in range(1, min(len(A), 5) + 1):
                for y in range(1, min(len(B), 5) + 1):
                    if x + y > 7: continue
                    cand = A[-x:] + B[:y]
                    if cand in needles and cand not in toks_set and cand in joined:
                        junction[cand].add(gid)
bad = sorted(junction.items(), key=lambda kv: -len(kv[1]))
print('   存在跨段假命中的查询词数: %d  合计假命中组数: %d' % (len(bad), sum(len(v) for _, v in bad)))
for cand, gs in bad[:15]:
    w = needles[cand]
    g = [x for x in GA if x[0] == list(gs)[0]][0]
    print('     %-5s needle=%-8s %3d 组  例 %s' % (w, cand, len(gs), g[2]))

# (ii) 首字母的真实收益：茎名缩写段是否等于后一段的首字母
print('\n=== (ii) 茎名缩写段 = 相邻段首字母？（首字母方案的收益上界） ===')
hit = 0
tot = 0
exl = []
for gid, kind, stem, dir_, hs, hl in GA:
    tk = tokens(stem)
    for i, t in enumerate(tk):
        if 2 <= len(t) <= 4 and t.isalpha() and i + 1 < len(tk) and tk[i + 1].isalpha():
            tot += 1
            ini = ''.join(x[0] for x in tk[i + 1:]) if len(tk[i + 1]) > 1 else ''
            if t == ini:
                hit += 1
            elif t == tk[i + 1][:len(t)]:
                hit += 1
            elif len(exl) < 12:
                exl.append((stem, t, tk[i + 1]))
print('   相邻缩写段 %d 个，其中能由后段拼出的 %d (%.1f%%)；样例（缩写段,后段）: %s' % (tot, hit, 100.0*hit/max(tot,1), exl[:8]))
