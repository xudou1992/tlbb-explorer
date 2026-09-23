"""Build a plain-language material wall from the decoded UI textures.

Input:  .scratch/wall/texture_preview/*.png|webp  (produced by preview-scan --named)
        .scratch/resources.db                     (names, sizes, directories)
Output: .scratch/wall/wall.html                   (self-contained page, images by relative path)

Deliberately no internal vocabulary on screen: no hashes, no codecs, no grades.
"""
import collections
import json
import os
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'wall')
IMG = os.path.join(OUT, 'texture_preview')

# Longest prefix wins; anything unmapped falls back to its own folder name.
CATEGORY = [
    ('ui/icon/skill', '技能图标'),
    ('ui/icon/item', '物品图标'),
    ('ui/icon/wardrobe', '外观衣柜'),
    ('ui/icon/buff', '状态图标'),
    ('ui/icon/activity', '活动图标'),
    ('ui/icon/role', '角色信息图标'),
    ('ui/icon/chat', '聊天图标'),
    ('ui/icon/task', '任务图标'),
    ('ui/icon/store', '商店图标'),
    ('ui/icon/team', '队伍图标'),
    ('ui/icon/fight', '战斗图标'),
    ('ui/icon', '其他图标'),
    ('ui/login', '登录与启动界面'),
    ('ui/texture/monsterhead', '怪物头像'),
    ('ui/texture/head', '头像框'),
    ('ui/texture/font', '文字与数字'),
    ('ui/texture/base', '界面底图与边框'),
    ('ui/texture/button', '按钮'),
    ('ui/texture/scroll', '卷轴与背景'),
    ('ui/texture/task', '任务界面件'),
    ('ui/texture', '界面贴图'),
    ('mobile_maps', '地图与场景贴图'),
    ('data/effect', '特效贴图'),
    ('ui', '界面其他'),
]


def category_of(path):
    low = path.lower()
    for prefix, name in CATEGORY:
        if low.startswith(prefix + '/'):
            return name
    d = path.rsplit('/', 1)[0]
    return d.split('/')[-1] if d else '未归类'


def title_of(path):
    """File stem minus the project prefix, so the caption reads less like a machine id."""
    base = path.rsplit('/', 1)[-1]
    base = base.rsplit('.', 1)[0]
    parts = [p for p in base.split('_') if p]
    if parts and parts[0].lower().startswith('w1351'):
        parts = parts[1:]
    return '_'.join(parts) or base


def main():
    con = sqlite3.connect('file:%s?mode=ro' % os.path.join(HERE, 'resources.db'), uri=True)
    rows = con.execute(
        "select path, width, height, original, props from resources "
        "where type='texture' and named=1 order by path").fetchall()

    items, missing = [], 0
    for path, w, h, size, props in rows:
        stem = path.replace('/', '_')
        file = next((f'{stem}{ext}' for ext in ('.png', '.webp')
                     if os.path.exists(os.path.join(IMG, f'{stem}{ext}'))), None)
        if not file:
            missing += 1
            continue
        items.append({
            '图': 'texture_preview/' + file,
            '名称': title_of(path),
            '分类': category_of(path),
            '宽': w, '高': h,
            '原文件': path,
            '大小KB': round((size or 0) / 1024.0, 1),
        })

    dist = collections.Counter(i['分类'] for i in items)
    order = [n for _, n in CATEGORY]
    cats = [c for c in order if dist.get(c)] + sorted(set(dist) - set(order))
    doc = {
        '总数': len(items),
        '分类': [{'名': c, '数': dist[c]} for c in cats],
        '素材': items,
    }
    html = TEMPLATE.replace('__DATA__', json.dumps(doc, ensure_ascii=False))
    with open(os.path.join(OUT, 'wall.html'), 'w', encoding='utf-8') as f:
        f.write(html)
    print('素材 %d 张，未能出图 %d 张，分类 %d 个' % (len(items), missing, len(cats)))
    for c in cats:
        print('  %-14s %5d' % (c, dist[c]))
    print('页面: %s' % os.path.join(OUT, 'wall.html'))


TEMPLATE = r"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>天龙界面素材库</title><style>
:root{color-scheme:dark}body{margin:0;padding:18px 22px;background:#14161a;color:#e8eaed;
font:14px/1.5 "Microsoft YaHei",system-ui,sans-serif}
h1{font-size:20px;margin:0 0 2px}.tip{color:#9aa0a6;font-size:12px;margin-bottom:12px}
.bar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:12px}
input{padding:8px 11px;background:#1d2025;border:1px solid #2c313a;border-radius:7px;color:#e8eaed;width:220px}
.cat{padding:5px 12px;background:#1d2025;border:1px solid #2c313a;border-radius:20px;cursor:pointer;
font-size:13px;color:#9aa0a6}.cat.on{background:#2f4364;color:#fff;border-color:#4a6da8}
.cat b{font-weight:400;opacity:.65;margin-left:4px;font-size:11px}
.cnt{color:#8ab4f8;font-size:12px;margin:-4px 0 10px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(128px,1fr));gap:10px}
.cell{background:#1a1d22;border:1px solid #262b33;border-radius:8px;padding:7px;cursor:pointer;
display:flex;flex-direction:column;gap:5px}
.cell:hover{border-color:#4a6da8;background:#1e222a}
.box{height:88px;display:flex;align-items:center;justify-content:center;
background:repeating-conic-gradient(#1b1e23 0 25%,#171a1e 0 50%) 0 0/16px 16px;border-radius:5px;overflow:hidden}
.box img{max-width:100%;max-height:88px;object-fit:contain}
.nm{font-size:11px;color:#c8ccd2;word-break:break-all;line-height:1.3;max-height:2.6em;overflow:hidden}
.mask{position:fixed;inset:0;background:rgba(8,9,11,.86);display:none;align-items:center;
justify-content:center;padding:24px;z-index:9}
.mask.on{display:flex}.panel{background:#1a1d22;border:1px solid #2c313a;border-radius:12px;
padding:18px;max-width:min(860px,94vw);max-height:90vh;overflow:auto}
.panel img{max-width:100%;max-height:56vh;background:repeating-conic-gradient(#20242a 0 25%,#1a1d22 0 50%) 0 0/18px 18px;
border-radius:8px;display:block;margin-bottom:12px}
.kv{display:grid;grid-template-columns:88px 1fr;gap:4px 10px;font-size:13px;margin-top:8px}
.kv span:nth-child(odd){color:#9aa0a6}.mono{font-family:consolas,monospace;font-size:12px;color:#c8ccd2;word-break:break-all}
.close{float:right;cursor:pointer;color:#9aa0a6;font-size:20px;line-height:1}
.tech{margin-top:10px;font-size:12px;color:#9aa0a6}
</style></head><body>
<h1>天龙界面素材库</h1>
<div class="tip">从客户端资源包里直接解出来的图片，全部可以看。点任意一张看大图和它的位置。</div>
<div class="cnt" id="cnt"></div>
<div class="bar"><input id="q" placeholder="搜名字，比如 icon_buff"><span id="cats"></span></div>
<div class="grid" id="g"></div>
<div class="mask" id="m"><div class="panel" id="p"></div></div>
<script>
const D=__DATA__;let cat='全部',kw='';
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
function show(){
 const list=D["素材"].filter(x=>(cat==='全部'||x["分类"]===cat)&&
   (!kw||x["名称"].toLowerCase().includes(kw)||x["原文件"].toLowerCase().includes(kw)));
 g.innerHTML=list.map((x,i)=>`<div class=cell data-i="${D["素材"].indexOf(x)}">
  <div class=box><img loading=lazy src="${esc(x["图"])}"></div><div class=nm>${esc(x["名称"])}</div></div>`).join('');
 cnt.textContent=`显示 ${list.length} / ${D["总数"]} 张`+(cat!=='全部'?`（分类：${cat}）`:'');
}
cats.innerHTML=['<span class="cat on" data-c="全部">全部<b>'+D["总数"]+'</b></span>']
 .concat(D["分类"].map(c=>`<span class=cat data-c="${esc(c["名"])}">${esc(c["名"])}<b>${c["数"]}</b></span>`)).join('');
cats.onclick=e=>{const s=e.target.closest('.cat');if(!s)return;cat=s.dataset.c;
 [...cats.children].forEach(x=>x.classList.toggle('on',x===s));show();};
q.oninput=e=>{kw=e.target.value.trim().toLowerCase();show();};
g.onclick=e=>{const c=e.target.closest('.cell');if(!c)return;const x=D["素材"][+c.dataset.i];
 p.innerHTML=`<span class=close onclick="m.classList.remove('on')">×</span>
  <img src="${esc(x["图"])}"><div style="font-size:16px;font-weight:600">${esc(x["名称"])}</div>
  <div class=kv><span>在哪一类</span><div>${esc(x["分类"])}</div>
  <span>画面尺寸</span><div>${x["宽"]} × ${x["高"]}</div>
  <span>文件多大</span><div>${x["大小KB"]} KB</div>
  <span>在包里的位置</span><div class=mono>${esc(x["原文件"])}</div></div>
  <div class=tech>这个位置就是游戏里读取它时用的名字，改图要放回同一个位置才会被读到。</div>`;
 m.classList.add('on');};
m.onclick=e=>{if(e.target.id==='m')m.classList.remove('on');};
show();
</script></body></html>"""

if __name__ == '__main__':
    main()
