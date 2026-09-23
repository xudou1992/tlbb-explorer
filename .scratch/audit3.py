# -*- coding: utf-8 -*-
"""(b) short-query noise  (c) normalize cross-word false hits  (d) initials inflation"""
import sqlite3, re, collections, sys, random, itertools
sys.stdout.reconfigure(encoding='utf-8')

PRIM = {}
for l in open('pinyin_map.tsv', encoding='utf-8'):
    a, b = l.rstrip('\n').split('\t')
    PRIM[a] = b
SEP = re.compile(r'[_\-/. ]')
def norm(s):
    return SEP.sub('', (s or '').lower())

db = sqlite3.connect('file:resources.db?mode=ro', uri=True)
groups = list(db.execute('select id, kind, stem, dir from agroups'))
GA = []
for gid, kind, stem, dir_ in groups:
    leaf = (dir_ or '').rstrip('/').split('/')[-1]
    GA.append((gid, kind, stem or '', dir_ or '', norm(stem), norm(leaf)))

def name_hits(needles):
    out = []
    for gid, kind, stem, dir_, hs, hl in GA:
        for n in needles:
            if n and (n in hs or n in hl):
                out.append((gid, kind, stem, dir_))
                break
    return out

# ---------- (b) 两字随机词噪声 ----------
COMMON = '的一是不了人我在有他这为之大来以个中上们到说国和地也子时道出会三要于下得可你年生自回其爱着行功去过学加法海米所说者土式好认内应此进主海天天和地平风火水木金土石山cloud'
COMMON = ''.join(sorted(set('的一是不了人我在有他这为之大来以个中上们到说国和地也子时道出会三要于下得可你年生自回其爱着行功去过学加法海米式好认内应此进主平风火水木金土石雨雪花月星日夜明暗长短老少年小大多少几全黑白红绿蓝紫青黄金银铜铁刀剑枪弓甲盾牌城池村寨镇庙殿楼阁台塔桥路街口门房屋窗床桌椅琴棋书画诗酒茶饭鱼肉果花草树木根枝叶果实种子壳皮毛骨肉筋骨血脉气灵魂鬼神妖魔仙佛道法术符阵功夫武勇猛烈轻便快慢迟速远近高低上下左右前后内外里中远游行走立坐卧睡醒见闻尝嗅触摸抓拿打踢推拉扯扔掷抛飞跳跃跑爬滚翻旋转弯曲伸直')))
random.seed(20260922)
words = []
while len(words) < 30:
    w = random.choice(COMMON) + random.choice(COMMON)
    if w not in words and all(c in PRIM for c in w):
        words.append(w)
stat = []
for w in words:
    p = ''.join(PRIM[c] for c in w)
    h = name_hits([w, p])
    stat.append((len(h), w, p))
stat.sort(reverse=True)
tot = sum(s[0] for s in stat)
print('=== (b) 30 个随机两字中文词：名称命中数 (共 %d 组 / %d) ===' % (tot, len(GA)))
for n, w, p in stat[:12]:
    print('   %-4s %-12s %5d' % (w, p, n))
print('   mean %.1f  median %d  max %d  zero-hit %d/30' % (tot / 30, stat[len(stat)//2][0], stat[0][0], sum(1 for s in stat if s[0] == 0)))
print('   top10 平均 %.1f' % (sum(s[0] for s in stat[:10]) / 10))

# syllable-length driver
syl_hits = {}
for n, w, p in stat:
    pass
print('\n--- 短拼音子串的“意外命中”面（needle 在归一化茎名里出现的组数） ---')
for needle in ['an', 'li', 'zi', 'yi', 'wu', 'er', 'yu', 'ai', 'en', 'ing', 'ng', 'lu', 'ba', 'ma', 'da',
               'xian', 'shou', 'hua', 'le', 'de', 'shi', 'zhi', 'chang', 'san', 'yue', 'long', 'men', 'yun']:
    print('   %-7s %5d' % (needle, len(name_hits([needle]))))

# real two-char words that are noisy (semantic, not random)
print('\n--- 常用词里最容易误命中的 ---')
real = ['宠物','特效','建筑','武器','坐骑','时装','石头','人口','大山','木门','火人','工人','天地','小门',
        '立正','一半','大人','白天','月光','风云','山水','金花','银月','木门','石门','土人','火舞','水龙']
rr = []
for w in real:
    p = ''.join(PRIM[c] for c in w)
    rr.append((len(name_hits([w, p])), w, p))
rr.sort(reverse=True)
for n, w, p in rr[:12]:
    ex = name_hits([w, p])[:2]
    print('   %-6s %-10s %5d  e.g. %s' % (w, p, n, [e[2] for e in ex]))

# ---------- (c) normalize 跨词假命中 ----------
print('\n=== (c) 归一化后跨 token 边界的假命中 ===')
def crossing(needle, s):
    h = norm(s)
    idx = []
    m = {}
    j = 0
    for i, ch in enumerate(s):
        if ch not in '_-/. ':
            m[j] = i
            j += 1
    res = []
    for mo in re.finditer(re.escape(needle), h):
        a, b = mo.start(), mo.end() - 1
        seg = s[m[a]:m[b] + 1]
        if '_' in seg or '-' in seg or ' ' in seg or '/' in seg:
            res.append(seg)
    return res

tot_cross = 0
tot_all = 0
samples = []
for w in ['曹霜','宠物','武器','天山','慕容','逍遥','星宿','无相','音乐','少林','大理','建造','帮派','江湖','帮主','女子','男子','石头','花园','门口','山上','水月','白云','风雪','江湖侠']:
    if any(c not in PRIM for c in w):
        continue
    p = ''.join(PRIM[c] for c in w)
    hs = name_hits([p])
    for gid, kind, stem, dir_ in hs:
        for src in (stem, dir_.rstrip('/').split('/')[-1]):
            cr = crossing(p, src)
            if cr:
                tot_cross += 1
                if len(samples) < 25:
                    samples.append((w, p, src, cr))
                break
    tot_all += len(hs)
print('   命中总数 %d，其中 needle 跨越分隔符 %d (%.1f%%)' % (tot_all, tot_cross, 100.0 * tot_cross / max(tot_all, 1)))
for s in samples[:20]:
    print('   ', s)

# ---------- (d) 首字母膨胀 ----------
print('\n=== (d) 加首字母 key 的膨胀 ===')
random.seed(7)
ws = []
while len(ws) < 20:
    w = random.choice(COMMON) + random.choice(COMMON) + random.choice(COMMON)
    if w not in ws and all(c in PRIM for c in w):
        ws.append(w)
ratio = []
for w in ws:
    p = ''.join(PRIM[c] for c in w)
    ini = ''.join(PRIM[c][0] for c in w)
    a = len(name_hits([p]))
    b = len(name_hits([ini]))
    ratio.append((w, p, ini, a, b))
for w, p, ini, a, b in ratio:
    print('   %-5s %-12s ini=%-6s 拼音命中 %4d 首字母命中 %5d  x%.0f' % (w, p, ini, a, b, (b / max(a, 1))))
print('   平均膨胀 x%.1f  最大 x%.0f' % (sum(r[4] / max(r[3], 1) for r in ratio) / len(ratio), max(r[4] / max(r[3], 1) for r in ratio)))
# 曹霜 case
p = 'caoshuang'; ini = 'cs'
hp = name_hits([p]); hi = name_hits([ini])
print('   曹霜: 全拼音 %d 命中 %s | 首字母 cs %d 命中 %s' % (len(hp), [x[2] for x in hp][:4], len(hi), [x[2] for x in hi][:8]))
# upside of initials: stems that ARE abbreviations
abbr = [(gid, kind, stem, dir_) for gid, kind, stem, dir_, hs, hl in GA if re.search(r'(^|_)([a-z]{2,4})(_|$)', hs) and re.match(r'^w1351', stem or '')]
print('   茎名里含 2-4 字母缩写段的组数: %d' % len(abbr))
tok = collections.Counter()
for gid, kind, stem, dir_ in abbr:
    for t in re.split(r'[_\-.]', (stem or '').lower()):
        if 2 <= len(t) <= 4 and t.isalpha() and all(ch in 'abcdefghijklmnopqrstuvwxyz' for ch in t):
            tok[t] += 1
print('   最常见缩写段:', tok.most_common(25))

# ---------- (e) agroup_names / resources.name 扩召回 ----------
print('\n=== (e) 只搜 stem/leaf vs 追加 agroup_names ===')
gn = collections.defaultdict(list)
for gid, name in db.execute('select gid, name from agroup_names'):
    gn[gid].append(norm(name))
for w in ['曹霜','慕容','天山','宠物','武器','星宿','音乐','逍遥','帮派','结婚']:
    p = ''.join(PRIM[c] for c in w)
    a = len(name_hits([p]))
    b = sum(1 for gid, kind, stem, dir_, hs, hl in GA if p in hs or p in hl or any(p in x for x in gn.get(gid, [])))
    print('   %-4s %-12s stem/leaf %4d  +成员文件名 %5d  (+%.0f%%)' % (w, p, a, b, 100.0 * (b - a) / max(a, 1)))
res_names = [norm(n) for (n,) in db.execute('select name from resources') if n]
print('   resources.name 归一化后 distinct:', len(set(res_names)))
