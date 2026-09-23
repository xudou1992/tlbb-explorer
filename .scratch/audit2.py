# -*- coding: utf-8 -*-
"""Polyphone / reading audit: primary vs alternate readings measured against the corpus."""
import sqlite3, re, collections, sys, itertools
sys.stdout.reconfigure(encoding='utf-8')

PRIM = {}
for l in open('pinyin_map.tsv', encoding='utf-8'):
    a, b = l.rstrip('\n').split('\t')
    PRIM[a] = b

db = sqlite3.connect('file:resources.db?mode=ro', uri=True)
groups = list(db.execute('select id, kind, stem, dir from agroups'))
SEP = re.compile(r'[_\-/. ]')
def norm(s):
    return SEP.sub('', (s or '').lower())
HAYS = []
for gid, kind, stem, dir_ in groups:
    leaf = (dir_ or '').rstrip('/').split('/')[-1]
    HAYS.append((gid, kind, norm(stem), norm(leaf)))

def hits(needle):
    n = norm(needle)
    return [g for g in HAYS if n and (n in g[2] or n in g[3])]

# alternate readings actually used by the artists (char -> other readings worth testing)
ALT = {
 '相':['xiang','xing','xjiang'], '无':['wu','mo'], '重':['zhong','chong','tong'],
 '乐':['le','yue','lao'], '朝':['chao','zhao'], '参':['can','shen','sen','ceng'],
 '将':['jiang','qiang','yang'], '行':['xing','hang','heng','xiang'], '长':['zhang','chang'],
 '单':['dan','shan','chan'], '邪':['xie','ye','yu'], '传':['chuan','zhuan'],
 '藏':['cang','zang'], '曾':['ceng','zeng'], '盖':['gai','ge','he'], '招':['zhao','shao'],
 '禅':['chan','shan'], '那':['na','nuo','ne'], '拓':['tuo','ta','zhi'], '泊':['bo','po'],
 '薄':['bao','bo','bu'], '弹':['dan','tan'], '奇':['qi','ji'], '冠':['guan','guang'],
 '弄':['nong','long'], '六':['liu','lu'], '石':['shi','dan'], '氏':['shi','zhi'],
 '不':['bu','fou'], '番':['fan','pan','bo'], '大':['da','dai','tai'], '员':['yuan','yun'],
 '员2':['yun'], '阏':['yan'], '于':['yu','xu'], '於':['yu','wu'], '泽':['ze','shi'],
 '什':['shi','za'], '摩':['mo','ma'], '磨':['mo','ma'], '落':['luo','la','lao'],
 '笼':['long','lao'], '露':['lu','lou'], '熟':['shu','shou'], '血':['xue','xie'],
 '地':['di','de'], '得':['de','dei','de'], '斗':['dou','dou3'], '勾':['gou','gou4'],
 '给':['gei','ji'], '过':['guo'], '汗':['han','han2'], '巷':['xiang','hang'],
 '些':['xie'], '兴':['xing','xing4'], '省':['sheng','xing'], '乘':['cheng','sheng'],
 '盛':['sheng','cheng'], '数':['shu','shuo','shu4'], '率':['shuai','lu'],
 '思':['si','sai'], '台':['tai'], '汤':['tang','shang'], '提':['ti','shi','di'],
 '田':['tian'], '条':['tiao'], '挑':['tiao','zhao'], '帖':['tie','tie4','tian'],
 '尉':['wei','yu'], '义乌':['yi'], '否':['fou','pi'], '夫':['fu','fu2'],
 '父':['fu','ba'], '嘎':['ga','ga2'], '皋':['gao','hao'], '圭':['gui'],
 '国':['guo'], '浩':['hao'], '郝':['hao','shi'], '汗诺':['nuo'],
}
WORDS = [
 '无相','无邪','重楼','重庆','重复','音乐','乐园','朝阳','朝拜','参合','参加','海参',
 '行星','行走','银行','长城','长歌','长枪','单于','简单','传奇','传说','弹指','弹药',
 '藏经','西藏','曾经','招摇','禅宗','少林','那拉','开拓','湖泊','薄弱','弹琴','奇门',
 '冠军','弄堂','六脉','石氏','氏姓','吐蕃','大夫','员外','血战','巷子','省亲','乘胜',
 '数量','效率','提防','尉迟','皋兰','浩大','邪恶','将星','将军','将士','无名','无间',
 '相州','相信','真相','丞相','天下','天龙','八部','逍遥','峨眉','武当','天山','星宿',
 '大理','明教','丐帮','华山','慕容','萧峰','段誉','虚竹','王语嫣','木婉清','钟灵',
 '宠物','特效','建筑','坐骑','武器','时装','场景','怪物','首领','任务','副本','阵营',
]

def variants(w):
    per = []
    for c in w:
        alts = ALT.get(c)
        if alts:
            per.append(list(dict.fromkeys(alts)))
        else:
            per.append([PRIM.get(c, c)])
    out = []
    for combo in itertools.product(*per):
        out.append(''.join(combo))
    return list(dict.fromkeys(out))

rows = []
for w in WORDS:
    if any(c not in PRIM for c in w):
        rows.append((w, 'MISSING-CHAR', None, None, 0))
        continue
    p = ''.join(PRIM[c] for c in w)
    hp = hits(p)
    alt_hits = []
    for v in variants(w):
        if v == p:
            continue
        h = hits(v)
        if h:
            alt_hits.append((v, len(h), h[0][1], [x[2] for x in h[:2]]))
    rows.append((w, p, len(hp), alt_hits, len(hp)))

print('%-8s %-14s %6s  %s' % ('词', '拼音库读法', '名称命中', '非主读法在库里的命中'))
bad = []
for w, p, n, alt, _ in rows:
    if n == 0 and alt:
        bad.append((w, p, alt))
    print('%-8s %-14s %6d  %s' % (w, p, n, '; '.join('%s=%d %s' % (a[0], a[1], a[3][:1]) for a in alt[:3])))

print('\n=== 主读法 0 命中、但变体在库里真实存在（=搜不到） ===')
for w, p, alt in bad:
    print(' ', w, p, '->', [(a[0], a[1], a[3]) for a in alt[:2]])
