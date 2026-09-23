"""Evidence-grade HTML reports: one asset, or a fleet-wide overview.

HTML rather than PDF because the point is the evidence chain — expandable structure,
inline preview, and a click back into the running browser — not print layout.

usage:
  python report.py --overview                 # out/reports/资产总览.html
  python report.py --asset 23                 # one asset report
  python report.py --top 40                   # the 40 richest assets
  python report.py --all                      # every asset (large!)
"""
import argparse
import base64
import datetime
import html
import json
import os
import sqlite3

import explorer as ex
import identity

HERE = os.path.dirname(os.path.abspath(__file__))
OUTD = os.path.join(HERE, 'out', 'reports')


def zh(group, key):
    return ex.LABELS[group].get(key, key) if key else '—'


REL = {'use-mtl': '用到它的材质', 'use-ske': '用到它的骨骼', 'use-mesh': '用到它的模型',
       'use-ani': '用到它的动作', 'use-tex': '用到它的贴图', 'use-pu': '用到它的特效',
       'use-scene': '用到它的场景', 'model-part': '与它同属一个模型',
       'same-stem': '同名配套文件', 'ref': '文件里写着它的名字'}


def esc(v):
    return html.escape(str(v if v is not None else ''))


def human(n):
    n = n or 0
    for unit, lim in (('GB', 1e9), ('MB', 1e6), ('KB', 1e3)):
        if n >= lim:
            return '%.1f %s' % (n / lim, unit)
    return '%d 字节' % n


def thumb_b64(gid):
    p = os.path.join(ex.PREV, '%d.png' % gid)
    if not os.path.isfile(p):
        return ''
    with open(p, 'rb') as f:
        return 'data:image/png;base64,' + base64.b64encode(f.read()).decode()


CSS = """
:root{--bg:#f6f7f9;--fg:#1b1f27;--dim:#6b7381;--line:#dfe3ea;--acc:#1f5fa8}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.65 "Microsoft YaHei",
 "PingFang SC",system-ui,sans-serif}
header{background:#101318;color:#eef1f6;padding:16px 26px}
header b{font-size:17px}header span{color:#98a2b3;font-size:12px;margin-left:12px}
main{max-width:1000px;margin:0 auto;padding:22px 26px 60px}
section{background:#fff;border:1px solid var(--line);border-radius:10px;padding:16px 18px;margin:14px 0}
h2{font-size:13px;color:var(--dim);margin:0 0 10px;font-weight:600;letter-spacing:.05em}
h1{font-size:22px;margin:0 0 4px}
.kv{display:grid;grid-template-columns:110px 1fr;gap:3px 12px;font-size:13px}
.kv b{color:var(--dim);font-weight:400}
.head{display:flex;gap:18px;align-items:flex-start}
.head img{width:132px;height:132px;border-radius:8px;border:1px solid var(--line);object-fit:cover;background:#12141a}
.tag{display:inline-block;background:#eef2f8;border:1px solid var(--line);border-radius:20px;
 padding:1px 10px;font-size:12px;margin:2px 5px 2px 0;color:#33415c}
.mono{font-family:Consolas,Menlo,monospace;font-size:12px}
.tree{list-style:none;margin:0;padding-left:0;font-size:13px}
.tree ul{list-style:none;margin:2px 0 10px;padding-left:22px;border-left:1px dashed var(--line)}
.tree li{padding:1px 0}
.tree>li>b{color:#33415c}
.mut{color:var(--dim);font-size:12px}
.bad{color:#a1401e}
.ok{color:#1c6b3f}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line)}
th{color:var(--dim);font-weight:500;font-size:12px}
td.r{text-align:right;font-variant-numeric:tabular-nums}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(158px,1fr));gap:12px}
.card{background:#fff;border:1px solid var(--line);border-radius:10px;overflow:hidden;
 text-decoration:none;color:inherit;display:block}
.card img{width:100%;height:118px;object-fit:cover;background:#12141a;display:block}
.card div{padding:7px 9px}.card b{display:block;font-size:13px;overflow:hidden;
 text-overflow:ellipsis;white-space:nowrap}
details{margin-top:10px}summary{color:var(--dim);cursor:pointer;font-size:12px}
footer{color:var(--dim);font-size:12px;padding:18px 26px;max-width:1000px;margin:0 auto}
a{color:var(--acc)}
"""


def con():
    c = sqlite3.connect('file:%s?mode=ro' % ex.DB, uri=True)
    c.row_factory = sqlite3.Row
    return c


def nice(s):
    return (str(s or '')).replace('w1351_', '', 1)


def asset_report(db, gid, gen):
    g = db.execute('SELECT * FROM agroups WHERE id=?', (gid,)).fetchone()
    if not g:
        return None
    g = dict(g)
    mem = [dict(r) for r in db.execute(
        'SELECT m.role, x.* FROM amembers m JOIN resources x ON x.hash=m.hash '
        'WHERE m.gid=? ORDER BY m.role, x.path', (gid,))]
    ids = db.execute('SELECT * FROM asset_identity WHERE gid=?', (gid,)).fetchone()
    ids = dict(ids) if ids else {}
    dup = db.execute('SELECT COUNT(*)-1 FROM asset_identity WHERE id_asset=?',
                     (ids.get('id_asset'),)).fetchone()[0] if ids else 0
    tags = [r[0] for r in db.execute(
        'SELECT tag FROM asset_tags WHERE gid=? ORDER BY confidence, tag', (gid,))]
    names = [dict(r) for r in db.execute(
        'SELECT name, cls FROM agroup_names WHERE gid=? ORDER BY cls, name', (gid,))]
    usedby = [dict(r) for r in db.execute(
        'SELECT DISTINCT r.rel, x.name, x.path FROM relations r '
        'JOIN resources x ON x.hash=r.from_hash '
        'WHERE r.to_hash IN (SELECT hash FROM amembers WHERE gid=?) '
        'AND r.from_hash NOT IN (SELECT hash FROM amembers WHERE gid=?) '
        'ORDER BY x.path LIMIT 40', (gid, gid))]
    byrole = {}
    for m in mem:
        byrole.setdefault(m['role'], []).append(m)
    ver = versions_for(db, gid, g, ids)
    t = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    body = ['<header><b>天龙资源浏览器 · 资源报告</b><span>生成于 %s · 报告编号 %s</span></header>'
            % (t, esc(gid)), '<main>']
    body.append('<section class=head><img src="%s"><div><h1>%s</h1><div class=mut>%s · 由 %d 个文件组成 · %s</div>'
                '<div>%s</div><div class="mut mono" style="margin-top:6px">%s</div></div></section>' % (
                    thumb_b64(gid), esc(nice(g['stem']) or ('未命名资源 %d' % gid)),
                    esc(zh('kind', g['kind'])), g['n'],
                    esc('贴图齐全' if g['n_tex'] else ('缺贴图' if g['names'] else '仅文件')),
                    ''.join('<span class=tag>%s</span>' % esc(x) for x in tags),
                    esc(g['dir'])))
    if ids:
        body.append('<section><h2>资源身份证</h2><div class=kv>'
                    '<b>身份证</b><span class=mono>%s</span>'
                    '<b>内容层</b><span class=mono>%s</span>'
                    '<b>结构层</b><span class=mono>%s</span>'
                    '<b>打包层</b><span class=mono>%s</span>'
                    '<b>引用名层</b><span class=mono>%s</span>'
                    '<b>重复情况</b><span>%s</span></div></section>' % (
                        esc(ids.get('id_asset')), esc(ids.get('id_content')),
                        esc(ids.get('id_struct')), esc(ids.get('id_pack')),
                        esc(ids.get('id_names')),
                        ('另有 %d 项资源与它内容完全相同' % dup) if dup else '无重复'))
    tree = ['<section><h2>资源组成</h2><ul class=tree>']
    for role in identity.ROLES:
        ms = byrole.get(role) or []
        if not ms:
            continue
        tree.append('<li><b>%s · %d 个</b><ul>%s</ul></li>' % (
            esc(zh('role', role)), len(ms),
            ''.join('<li>%s <span class=mut>%s · %s</span></li>' % (
                esc(nice(m['name']) or m['hash']), esc(zh('type', m['type'])),
                esc(human(m['original']))) for m in ms[:60])))
        if len(ms) > 60:
            tree[-1] += '<li class=mut>…另有 %d 个未列出</li>' % (len(ms) - 60)
    tree.append('</ul></section>')
    body.append(''.join(tree))
    if names:
        body.append('<section><h2>引用了但没找到对应文件 · %d 个</h2><div>%s</div>'
                    '<div class=mut>这些名字来自资源内部的文件名表：包内确实没有对应的可定位文件，'
                    '属于安装缺失，不是解析失败。</div></section>' % (
                        len(names),
                        ' · '.join('<span class="%s">%s</span>' % (
                            'bad' if x['cls'] == 'shared' else '', esc(x['name']))
                            for x in names)))
    if usedby:
        body.append('<section><h2>谁在使用它 · %d 项</h2><ul class=tree>%s</ul></section>' % (
            len(usedby), ''.join(
                '<li>%s <span class=mut>%s</span></li>' % (
                    esc(nice(os.path.basename(u['path']))), esc(REL.get(u['rel'], u['rel'])))
                for u in usedby[:30])))
    if ver:
        body.append('<section><h2>版本比较</h2><table><tr><th>对照快照</th><th>判定</th>'
                    '<th>变化内容</th></tr>%s</table></section>' % ''.join(
                        '<tr><td>%s</td><td class="%s">%s</td><td class=mut>%s</td></tr>' % (
                            esc(v[0]), 'ok' if v[1] == '相同' else 'bad', esc(v[1]), esc(v[2]))
                        for v in ver))
    body.append('<section><details><summary>技术信息（给程序看的）</summary><div class=kv>'
                '<b>资源编号</b><span class=mono>%s</span>'
                '<b>成员清单</b><span class=mono>%s</span>'
                '</div></details></section>' % (
                    esc(g['hub']),
                    esc(''.join('%s=%s;' % (m['hash'], m['filecrc']) for m in mem[:200]))))
    body.append('</main><footer>数据来源：只读解析 data*.pak（未修改任何包文件）；'
                '图片解码与结构识别由本工具完成。查看原资源：<a href="%s/api/group/%d">资源浏览器</a>'
                '</footer>' % ('http://127.0.0.1:8765', gid))
    return '\n'.join(body)


def versions_for(db, gid, g, ids):
    """Compare this single asset against every snapshot in versions/."""
    base = os.path.join(HERE, 'out', 'versionA.json')
    if not (os.path.isfile(base) and os.path.isdir(ex.VER)):
        return []
    A = json.load(open(base, encoding='utf-8'))
    a = next((x for x in A['assets'] if x['gid'] == gid), None)
    if not a:
        return []
    out = []
    for f in sorted(os.listdir(ex.VER)):
        if not f.endswith('.json'):
            continue
        B = json.load(open(os.path.join(ex.VER, f), encoding='utf-8'))
        b = next((x for x in B['assets'] if (x['dir'], x['stem']) == (a['dir'], a['stem'])
                  and a['stem']), None) \
            or next((x for x in B['assets'] if x['id_asset'] == a['id_asset']), None)
        if b is None:
            out.append((f, '资产消失', '%d 个文件' % len(a['members'])))
            continue
        cnt, lines = identity.compare({'assets': [a]}, {'assets': [b]})
        out.append((f, cnt.most_common(1)[0][0],
                    lines[0][3] if lines else '内容完全一致'))
    return out


def overview(db, gen):
    one = lambda q: db.execute(q).fetchone()[0]
    n_assets = one('SELECT COUNT(*) FROM agroups')
    files = one('SELECT COUNT(*) FROM resources')
    dup_assets = n_assets - one('SELECT COUNT(DISTINCT id_asset) FROM asset_identity')
    kinds = db.execute('SELECT kind, COUNT(*) FROM agroups GROUP BY 1 ORDER BY 2 DESC').fetchall()
    top_dup = db.execute(
        'SELECT id_asset, COUNT(*) c, MIN(stem) s, MIN(kind) k FROM asset_identity '
        'GROUP BY id_asset HAVING c>1 ORDER BY c DESC LIMIT 30').fetchall()
    missing = db.execute(
        'SELECT name, n_src, cls FROM dangling ORDER BY n_src DESC LIMIT 30').fetchall()
    richest = db.execute(
        'SELECT id, stem, kind, n, n_mtl, n_ani, names FROM agroups '
        'ORDER BY names DESC, n DESC LIMIT 24').fetchall()
    t = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    b = ['<header><b>天龙资源浏览器 · 资产总览</b><span>生成于 %s · 只读解析，未修改任何 pak</span></header>' % t,
         '<main>',
         '<section><h2>总览</h2><div class=kv>'
         '<b>资源项数</b><span>%s</span>'
         '<b>文件数</b><span>%s</span>'
         '<b>引用关系</b><span>%s</span>'
         '<b>内容重复的资源</b><span>%s 项（同一份内容被 %s 组资源使用）</span>'
         '<b>引用名无法定位</b><span>%s 个</span>'
         '</div></section>' % (
             f'{n_assets:,}', f'{files:,}', f"{one('SELECT COUNT(*) FROM relations'):,}",
             f'{dup_assets:,}', f'{one("SELECT COUNT(*) FROM (SELECT id_asset FROM asset_identity GROUP BY 1 HAVING COUNT(*)>1)"):,}',
             f"{one('SELECT COUNT(*) FROM dangling'):,}")]
    b.append('<section><h2>分类分布</h2><table><tr><th>分类</th><th class=r>资源数</th></tr>%s</table></section>'
             % ''.join('<tr><td>%s</td><td class=r>%s</td></tr>' % (esc(zh('kind', k)), f'{n:,}')
                       for k, n in kinds))
    b.append('<section><h2>内容完全相同的资源排行（前 30）</h2>'
             '<div class=mut>同一份内容被打包成多项资源，是资源瘦身与去重的直接依据。</div>'
             '<table><tr><th>代表资源</th><th>分类</th><th class=r>重复份数</th></tr>%s</table></section>'
             % ''.join('<tr><td class=mono>%s</td><td>%s</td><td class=r>%d</td></tr>'
                       % (esc(nice(s) or '(无名)'), esc(zh('kind', k)), c) for _, c, s, k in top_dup))
    b.append('<section><h2>被最多资源引用、却找不到文件的资源名（前 30）</h2>'
             '<table><tr><th>名字</th><th class=r>被多少资源引用</th><th>类型</th></tr>%s</table></section>'
             % ''.join('<tr><td class=mono>%s</td><td class=r>%d</td><td>%s</td></tr>'
                       % (esc(nm), ns, '公共' if cl == 'shared' else '私有') for nm, ns, cl in missing))
    b.append('<section><h2>信息量最大的资源（前 24）</h2><div class=grid>%s</div></section>'
             % ''.join('<a class=card href="%s"><img src="%s"><div><b>%s</b>'
                       '<span class=mut>%s · %d 文件 · %d 贴图名</span></div></a>'
                       % (os.path.basename(gen(int(i))), thumb_b64(int(i)),
                          esc(nice(st) or ('未命名 %d' % i)), esc(zh('kind', k)), n, nm)
                       for i, st, k, n, _, _, nm in richest))
    b.append('</main><footer>由 resources.db 生成；单资源报告与本页同目录。</footer>')
    return '\n'.join(b)


def page(inner, title):
    return ('<!doctype html><html lang=zh><head><meta charset=utf-8>'
            '<meta name=viewport content="width=device-width,initial-scale=1">'
            '<title>%s</title><style>%s</style></head><body>%s</body></html>'
            % (esc(title), CSS, inner))


def write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--asset', type=int)
    ap.add_argument('--top', type=int)
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--overview', action='store_true')
    a = ap.parse_args()
    db = con()
    if not (a.asset or a.top or a.all or a.overview):
        a.overview = True

    def gen(gid):
        return '资源报告_%d.html' % gid

    made = []
    ids = []
    if a.asset:
        ids = [a.asset]
    elif a.top:
        ids = [r[0] for r in db.execute(
            'SELECT id FROM agroups ORDER BY names DESC, n DESC LIMIT ?', (a.top,))]
    elif a.all:
        ids = [r[0] for r in db.execute('SELECT id FROM agroups ORDER BY id')]
    for gid in ids:
        htmltxt = asset_report(db, gid, gen)
        if htmltxt:
            made.append(write(os.path.join(OUTD, gen(gid)), page(
                htmltxt, '资源报告 · %s' % gid)))
    if a.overview or ids:
        p = write(os.path.join(OUTD, '资产总览.html'),
                  page(overview(db, gen), '天龙资源浏览器 · 资产总览'))
        made.append(p)
    print('生成 %d 个文件：' % len(made))
    for p in made[:6]:
        print('   %s (%.1f KB)' % (p, os.path.getsize(p) / 1024))
    if len(made) > 6:
        print('   …共 %d' % len(made))


if __name__ == '__main__':
    main()
