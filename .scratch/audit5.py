# -*- coding: utf-8 -*-
import sqlite3, re, collections, sys, itertools
sys.stdout.reconfigure(encoding='utf-8')
PRIM = {}
for l in open('pinyin_map.tsv', encoding='utf-8'):
    a, b = l.rstrip('\n').split('\t'); PRIM[a] = b
ALL = collections.defaultdict(list)
T = str.maketrans('āáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜ','aaaaeeeeiiiioooouuuuuuuu')
for l in open('pinyin-data-pinyin.txt', encoding='utf-8'):
    l = l.strip()
    if not l or l.startswith('#'): continue
    code, rest = l.split(':', 1); rest = rest.split('#')[0].strip()
    rs = []
    for r in rest.split(','):
        r = r.strip().translate(T)
        if r and r not in rs: rs.append(r)
    try: ALL[chr(int(code[1:], 16))] = rs
    except ValueError: pass
SEP = re.compile(r'[_\-/. ]')
def norm(s): return SEP.sub('', (s or '').lower())
db = sqlite3.connect('file:resources.db?mode=ro', uri=True)
G = list(db.execute('select id, kind, stem, dir from agroups'))
GA = [(i, k, s or '', d or '', norm(s), norm((d or '').rstrip('/').split('/')[-1])) for i, k, s, d in G]
def hits(n):
    n = norm(n); return [g for g in GA if n and (n in g[4] or n in g[5])]
def only_leaf(n):
    n = norm(n); return [g for g in GA if n and n not in g[4] and n in g[5]]

print('=== 单字 ü 查询 ===')
for w in ['女','男','绿','吕','侣','略','虐','铝']:
    p = PRIM[w]; fx = p.replace('ü', 'v')
    print('  %s key=%-6s 现命中 %4d  ü→v 命中 %4d  真实茎名样例 %s' % (w, p, len(hits(p)), len(hits(fx)), [g[2] for g in hits(fx)][:2]))

print('\n=== 定向多音字复核（主读 vs 变体，附茎名） ===')
for w, guess in [('重楼','chonglou'),('五行','wuxing'),('五行旗','wuhangqi'),('乐游','leyou'),('乐游原','yueyou'),
                 ('六脉','lumai'),('独乐','dule'),('龟兹','qiuci'),('无崖','wuya'),('无相劫','wuxiangjie'),
                 ('星宿','xingxiu'),('音乐','yinyue'),('弹指','tanzhi'),('参合','shenhe'),('大宛','dayuan'),
                 ('单于','chanyu'),('招集','qiaoji'),('大夏','daxia'),('且末','qielu'),('大月氏','dayuezhi'),
                 ('破虏','polu'),('强中','qiangzhong'),('强大','changda'),('费话','feihua'),('刀郎','daolang')]:
    p = ''.join(PRIM[c] for c in w)
    print('  %-6s 主读 %-12s %4d   猜测变体 %-12s %4d  %s' % (w, p, len(hits(p)), guess, len(hits(guess)), [g[2] for g in hits(guess)][:2]))

print('\n=== 只命中目录末段（stem 未命中）的污染 ===')
for w in ['白猿','常碧元','高山','曹霜','慕容','兵器','少林','宠物','段誉','刀客','恶人','女子','石头']:
    if any(c not in PRIM for c in w): continue
    p = ''.join(PRIM[c] for c in w)
    ol = only_leaf(p)
    if ol:
        print('  %-5s key=%-10s 仅末段命中 %3d  例: stem=%s  leaf=%s' % (w, p, len(ol), ol[0][2], ol[0][3].rstrip('/').split('/')[-1]))
tot_ol = collections.Counter()
for g in GA:
    if g[4] != g[5] and g[5]:
        tot_ol[1] += 1
print('  stem 与目录末段不同的组数: %d / %d' % (tot_ol[1], len(GA)))
diff = [(g[2], g[3].rstrip('/').split('/')[-1]) for g in GA if g[4] != g[5] and g[5]]
print('  例:', diff[:6])

print('\n=== 数字/段位 needle 的命中面 ===')
for n in ['1351','001','01','b0','t','h','w','s','z','c','00','x0','p','m','a','e']:
    print('   %-5s %5d' % (n, len(hits(n))))
print('\n=== 全角/空格：query 里保留的 ASCII 会进 key ===')
def keys(q):
    out=[]; t=q.strip().lower()
    if t: out.append(t)
    j=''
    for c in t:
        m=PRIM.get(c)
        if m: j+=m
        elif c.isascii(): j+=c
    if j and j!=t and j not in out: out.append(j)
    return [k for k in out if k]
for q in ['曹 霜','曹霜','ＥＮ','ｎｐｃ','boss３','１３５１','曹霜ＥＮ','曹　霜','nv','ＮＰＣ']:
    ks = keys(q)
    h = set()
    for k in ks:
        for g in hits(k): h.add(g[0])
    print('   %-10r -> %s  命中 %d' % (q, ks, len(h)))

print('\n=== 未覆盖/无声调字符 ===')
print('   query "龘" ->', keys('龘'), ' ；"〇" ->', keys('〇'), '；"•" ->', keys('•'))
PY = re.compile(r'[^a-z0-9]', re.I)
print('\n=== 茎名里含非 ascii（应无）的组数 ===', sum(1 for g in GA if any(ord(ch)>127 for ch in g[2])))
