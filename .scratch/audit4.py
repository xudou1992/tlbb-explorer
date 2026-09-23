# -*- coding: utf-8 -*-
"""item1 polyphone(all readings)+umlaut miss, item3 crossing, item4 initials, item5 variants"""
import sqlite3, re, collections, sys, random, itertools
sys.stdout.reconfigure(encoding='utf-8')

PRIM = {}
for l in open('pinyin_map.tsv', encoding='utf-8'):
    a, b = l.rstrip('\n').split('\t')
    PRIM[a] = b

# full heteronym list from the crate's own data file
ALL = collections.defaultdict(list)
for l in open('pinyin-data-pinyin.txt', encoding='utf-8'):
    l = l.strip()
    if not l or l.startswith('#'):
        continue
    code, rest = l.split(':', 1)
    rest = rest.split('#')[0].strip()
    readings = []
    for r in rest.split(','):
        r = r.strip()
        if not r:
            continue
        # drop tone marks -> plain, keep ü as the crate does
        r = (r.replace('ā', 'a').replace('á', 'a').replace('ǎ', 'a').replace('à', 'a')
             .replace('ē', 'e').replace('é', 'e').replace('ě', 'e').replace('è', 'e')
             .replace('ī', 'i').replace('í', 'i').replace('ǐ', 'i').replace('ì', 'i')
             .replace('ō', 'o').replace('ó', 'o').replace('ǒ', 'o').replace('ò', 'o')
             .replace('ū', 'u').replace('ú', 'u').replace('ǔ', 'u').replace('ù', 'u')
             .replace('ǖ', 'ü').replace('ǘ', 'ü').replace('ǚ', 'ü').replace('ǜ', 'ü')
             .replace('ń', 'n').replace('ň', 'n').replace('ê', 'e').replace('ḿ', 'm'))
        if r not in readings:
            readings.append(r)
    try:
        ALL[chr(int(code[1:], 16))] = readings
    except ValueError:
        pass
print('heteronym chars with >1 reading:', sum(1 for v in ALL.values() if len(v) > 1))

SEP = re.compile(r'[_\-/. ]')
def norm(s):
    return SEP.sub('', (s or '').lower())

db = sqlite3.connect('file:resources.db?mode=ro', uri=True)
groups = list(db.execute('select id, kind, stem, dir from agroups'))
GA = []
for gid, kind, stem, dir_ in groups:
    leaf = (dir_ or '').rstrip('/').split('/')[-1]
    GA.append((gid, kind, stem or '', dir_ or '', norm(stem), norm(leaf)))

def hits(needle):
    n = norm(needle)
    return [g for g in GA if n and (n in g[4] or n in g[5])]

def name_hits(needles):
    s = set()
    for n in needles:
        for g in hits(n):
            s.add(g[0])
    return s

# ---------------- 1a umlaut ----------------
print('\n=== ü 泄漏：拼音库输出带 ü，茎名是 ASCII，永不命中 ===')
for w in ['女人', '女性', '美女', '女儿', '伴侣', '旅行', '绿色', '绿茶', '战略', '侵略', '频率', '细节']:
    p = ''.join(PRIM[c] for c in w)
    fixed = p.replace('ü', 'v').replace('ü', 'u')
    print('   %-4s key=%-12s 现方案命中 %3d   把 ü 归一为 v 后命中 %4d' % (w, p, len(name_hits([p])), len(name_hits([fixed]))))
print('   茎名/目录里含 nv 段的组数:', len(name_hits(['nv'])), ' 含 lv:', len(name_hits(['lv'])), ' 含 lü 的组数(应为0):', len(name_hits(['lü'])))

# ---------------- 1b polyphone with full readings ----------------
WORDS = ('无相 无邪 星宿 重楼 重庆 重复 音乐 乐园 朝阳 朝拜 参合 参加 海参 行星 行走 银行 长城 长歌 长枪 单于 简单 传奇 传说 弹指 弹药 藏经 西藏 曾经 招摇 禅宗 那拉 开拓 湖泊 薄弱 弹琴 奇门 冠军 弄堂 六脉 石氏 吐蕃 大夫 员外 血战 巷子 省亲 乘胜 数量 效率 提防 尉迟 邪恶 将星 将军 相信 丞相 华山 萧峰 mongodb 女子 男子 伴侣 旅行 绿色 战略 恶人 恶心 好人 独立 独处 单独 独乐寺 蓟 伽蓝 迦楼罗 般若 菩提 涅槃 阎罗 卤簿 大宛 龟兹 月氏 单于 阏氏 大夏 于阗 疏勒 天竺 身毒 康居 奄蔡 难楼 苏仆延 轲比能 拓跋 慕容 宇文 尉迟 长孙 万俟 呼延 司徒 司空 司马 东方 独孤 南宫 西门 第五 言 函夏 寒暑 会稽 会盟 计数 齿数 核数 人数 人数 主角 配角 角色 角斗 头角 角逐 觝 尖角 直角 角度 手角 角落 名角'
         ).split()
seen = set()
rows = []
for w in WORDS:
    if w in seen or any(c not in PRIM for c in w) or not all('一' <= c <= '鿿' for c in w):
        continue
    seen.add(w)
    p = ''.join(PRIM[c] for c in w)
    hp = name_hits([p])
    variants = []
    for combo in itertools.product(*[ALL.get(c, [PRIM[c]]) for c in w]):
        v = ''.join(combo)
        if v != p:
            variants.append(v)
    alt = [(v, len(name_hits([v]))) for v in dict.fromkeys(variants)]
    alt = [(v, n) for v, n in alt if n]
    rows.append((w, p, len(hp), alt))
miss = [r for r in rows if r[2] == 0 and r[3]]
print('\n=== 多音字：主读法 0 命中但库里确有该词其它读法（%d 个） ===' % len(miss))
for w, p, n, alt in miss:
    ex = hits(alt[0][0])[0]
    print('   %-6s 主读 %-12s 0   变体 %-12s %3d  例茎名 %s' % (w, p, alt[0][0], alt[0][1], ex[2]))
tot_p = sum(r[2] for r in rows)
tot_a = sum(max(r[2], r[2] + max([a[1] for a in r[3]], default=0)) for r in rows)
print('   抽测 %d 个常用词：现方案名称命中合计 %d，展开多音字后 %d  (+%.0f%%)' % (len(rows), tot_p, tot_a, 100.0 * (tot_a - tot_p) / max(tot_p, 1)))

# ---------------- 3 crossing false hits ----------------
print('\n=== 归一化跨 token 假命中 ===')
def crossing_info(needle, s):
    idx = [i for i, ch in enumerate(s) if ch not in '_-/. ']
    h = norm(s)
    out = []
    for mo in re.finditer(re.escape(needle), h):
        seg = s[idx[mo.start()]:idx[mo.end() - 1] + 1]
        out.append(seg)
    return out

tot = cross = 0
samp = []
random.seed(11)
COMMON = ''.join(sorted(set('的一是不了人在有为之大来以个中上到说国和地也子时道会要于下得可年生自回其爱着行功过学加法海式好认内应此进主平风火水木金土石雨雪花月星日夜明暗长短老少年小多少全黑白红绿蓝紫青黄金银铜铁刀剑枪弓甲盾牌城池村寨镇庙殿楼阁台塔桥路街口门房屋窗床桌椅琴棋书画诗酒茶饭鱼肉果花草树木根枝叶果实种子壳皮毛骨肉筋骨血脉气灵魂鬼神妖魔仙佛道法术符阵功夫武勇猛烈轻便快慢迟速远近高低上下左右前后内外里中游行走立坐卧睡醒见闻触摸抓拿打踢推拉扯扔抛飞跳跃跑爬滚翻旋转弯曲直')))
ws = []
while len(ws) < 30:
    w = random.choice(COMMON) + random.choice(COMMON)
    if w not in ws:
        ws.append(w)
for w in ws:
    p = ''.join(PRIM[c] for c in w)
    for g in hits(p):
        tot += 1
        ci = crossing_info(p, g[2]) + crossing_info(p, g[3].rstrip('/').split('/')[-1])
        if any(ch in '_-/. ' for ch in ''.join(ci)):
            cross += 1
            if len(samp) < 12:
                samp.append((w, p, g[2], g[3].rstrip('/').split('/')[-1]))
print('   随机 30 两字词命中 %d 组，其中 needle 跨过分隔符 %d 组 (%.0f%%)' % (tot, cross, 100.0 * cross / max(tot, 1)))
for s in samp:
    print('     ', s)

# ---------------- 4 initials: junk share + abbreviation upside ----------------
print('\n=== 首字母 key ===')
tok_counter = collections.Counter()
abbr_groups = set()
for gid, kind, stem, dir_, hs, hl in GA:
    for t in re.split(r'[_\-.]', (stem or '').lower()):
        if 2 <= len(t) <= 4 and t.isalpha():
            tok_counter[t] += 1
            if t not in ('nan', 'nv', 'he', 'hei', 'bai', 'red', 'big', 'new', 't', 'a', 'an', 'ba', 'bi', 'bo', 'bu', 'c', 'de'):
                pass
print('   2-4 字母独立段的出现次数 top20:', tok_counter.most_common(20))
junk = 0
ini_hits_total = 0
for w in ['曹霜', '慕容', '天山', '逍遥', '宠物', '武器', '结婚', '少林', '大理', '星宿', '主角', '女人', '绿色', '战略', '门派']:
    p = ''.join(PRIM[c] for c in w)
    ini = ''.join(PRIM[c][0] for c in w)
    hs = [g for g in hits(ini)]
    ini_hits_total += len(hs)
    for g in hs:
        ci = crossing_info(ini, g[2]) + crossing_info(ini, g[3].rstrip('/').split('/')[-1])
        if any(ch in '_-/. ' for ch in ''.join(ci)) or len(ini) <= 2:
            junk += 1
    print('   %-4s 全拼 %-11s %4d | 首字母 %-4s %5d' % (w, p, len(hits(p)), ini, len(hs)))
print('   首字母命中合计 %d，其中跨段/2 字母退化 = %d (%.0f%%)' % (ini_hits_total, junk, 100.0 * junk / max(ini_hits_total, 1)))

# ---------------- 5 form variants ----------------
print('\n=== 词形变体 ===')
print('   茎名以 w1351_ 开头:', sum(1 for g in GA if g[2].startswith('w1351_')), '/', len(GA))
print('   茎名以 _NNN 结尾:', sum(1 for g in GA if re.search(r'_\d{3}$', g[2] or '')))
print('   茎名以 _bN 结尾:', sum(1 for g in GA if re.search(r'_b\d$', g[2] or '')))
print('   含 w1351 的组:', len(name_hits(['w1351'])), ' 含 001 的组:', len(name_hits(['001'])), ' 含 b0 的组:', len(name_hits(['b0'])), ' 含 _t_ 段的组:', len(name_hits(['t'])))
gn = 0
print('   查询 "曹 霜" 的 joined key 会保留空格再被 normalize 去掉 -> 等价 "caoshuang"; 全角 "ＥＮ" 非 ASCII 亦非汉字 -> 被丢弃, key 只剩原文 "ｅｎ", 命中 0')

# ---------------- 6 tags ----------------
print('\n=== 标签 ===')
tags = [r[0] for r in db.execute('select distinct tag from asset_tags order by tag')]
ZH = {"pet":"宠物","monster":"怪物","boss":"首领","npc":"NPC","building":"建筑","tileset":"地表贴图组","map-props":"地图摆件","effect":"特效","animation-set":"动作集","player-part":"角色部件","player-male":"男性角色","player-female":"女性角色","mask":"遮罩","ui":"界面","weapon":"武器","mount":"坐骑","accessory":"配饰","item-icon":"物品图标","scene-effect":"场景特效","skill-effect":"技能特效","shared-material":"共享材质","unknown":"未分类"}
print('   distinct tag', len(tags), ' 已译', sum(1 for t in tags if t in ZH), ' 漏译', [t for t in tags if t not in ZH], ' 多余', [t for t in ZH if t not in tags])
gids_with_tags = db.execute('select count(distinct gid) from asset_tags').fetchone()[0]
print('   有标签的组 %d / 8537，无任何标签的组 %d' % (gids_with_tags, len(GA) - gids_with_tags))
notag = [(gid, stem) for gid, kind, stem, dir_, hs, hl in GA if db.execute('select 1 from asset_tags where gid=? limit 1', (gid,)).fetchone() is None]
print('   无标签示例:', [s for _, s in notag[:12]])
# 分类词命中不到名称的
for w, t in [('宠物', 'pet'), ('怪物', 'monster'), ('特效', 'effect'), ('建筑', 'building'), ('坐骑', 'mount'), ('武器', 'weapon')]:
    p = ''.join(PRIM[c] for c in w)
    n = len(name_hits([p]))
    k = db.execute('select count(distinct gid) from asset_tags where tag=?', (t,)).fetchone()[0]
    print('   %-3s 名称命中 %4d  标签 %s=%4d' % (w, n, t, k))
