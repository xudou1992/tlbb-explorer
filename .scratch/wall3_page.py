#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
图片考古墙 · 第三步：生成墙面 HTML。

设计取舍（都为了"人能真的用起来"）：

1. **图片不 inline、不用 base64**（24,261 张 base64 会让 HTML 涨到几百 MB）。
   用 `<img src="thumb/xxx.png" loading="lazy">`，浏览器自己管加载。
   缩略图是本地相对路径，所以这个 HTML 必须和 thumb/ 目录一起放。

2. **数据分片加载**。24,261 条记录的 JSON 约 5 MB，一次性塞进 HTML 会让页面
   首屏等待明显。这里把元数据切成每 2000 张一个 `.json` 分片，
   滚动到哪加载哪——首屏只加载第一片。

3. **族/单张两种视图**。默认按族看（这是"考古"的核心），
   但孤图太多（见聚族报告），所以单张平铺视图也要在，两个都要能用。

4. **标签打族上**。人看一排图说"这是峨眉装备"，说的是这一堆。
   标签存 localStorage 并能导出 JSON——不写回 resources.db（那是只读事实层）。
"""

import os
import sys
import json
import time
import sqlite3
import argparse
from collections import defaultdict, Counter


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=r"D:\TLGL\.scratch\wall3\wall.db")
    ap.add_argument("--out", default=r"D:\TLGL\.scratch\wall3\考古墙.html")
    ap.add_argument("--shard", type=int, default=2000)
    # 缩略图相对/绝对路径前缀。默认 `thumb/`（与 HTML 同目录）。
    # 之所以要这个开关：本机沙箱下往工程盘写海量小文件极慢
    # （实测 21ms/张 vs 系统盘 0.22ms/张），所以缩略图落在 TEMP，
    # 而 HTML 留在工程目录——两者不在同一棵树里，必须能指过去。
    ap.add_argument("--thumb-rel", default="thumb/",
                    help="缩略图路径前缀，如 file:///C:/.../tlbb_wall_thumbs/")
    a = ap.parse_args()

    con = sqlite3.connect("file:%s?mode=ro" % a.db.replace("\\", "/"), uri=True)
    con.row_factory = sqlite3.Row
    q = lambda s, *p: [dict(r) for r in con.execute(s, p)]

    meta = {r["k"]: r["v"] for r in con.execute("SELECT k,v FROM wall_meta")}

    # ---- 族摘要（含每个族的成员 hash 列表，用来在墙上展开）
    fams = q("SELECT fid,n,rep_hash,mean_d,dia,codec,w,h,tightness FROM wall_family ORDER BY n DESC, fid")
    members = defaultdict(list)
    for r in con.execute("SELECT fam,hash FROM wall_tex WHERE fam>=0 ORDER BY fam, hash"):
        members[r[0]].append(r[1])
    for f in fams:
        f["members"] = members.get(f["fid"], [])

    # ---- 图片行（分片）
    texs = q("""SELECT hash,pak,gen,offset,original,catalog_codec,declared_w,declared_h,mips,
                       dhash,dec_w,dec_h,mean_r,mean_g,mean_b,mean_a,lum_sd,edge,alpha_cov,
                       decoded,fail_reason,fam
                FROM wall_tex ORDER BY fam>=0 DESC, fam, hash""")
    ntex = len(texs)
    keys = ["h", "pk", "g", "of", "or", "cc", "dw", "dh", "mi", "dh2",
            "w", "ht", "mr", "mg", "mb", "ma", "ls", "eg", "ac", "ok", "fr", "f"]
    shards = []
    outdir = os.path.dirname(a.out)
    sharddir = os.path.join(outdir, "meta")
    os.makedirs(sharddir, exist_ok=True)
    for si in range(0, ntex, a.shard):
        part = texs[si:si + a.shard]
        arr = [[t["hash"], t["pak"], t["gen"], t["offset"], t["original"],
                t["catalog_codec"], t["declared_w"], t["declared_h"], t["mips"],
                t["dhash"], t["dec_w"], t["dec_h"],
                round(t["mean_r"], 1), round(t["mean_g"], 1), round(t["mean_b"], 1),
                round(t["mean_a"], 1), round(t["lum_sd"], 2), round(t["edge"], 3),
                round(t["alpha_cov"], 3), t["decoded"], t["fail_reason"] or "", t["fam"]]
               for t in part]
        fn = "meta/shard_%04d.json" % (si // a.shard)
        with open(os.path.join(outdir, fn), "w", encoding="utf-8") as f:
            json.dump({"keys": keys, "rows": arr}, f, ensure_ascii=False, separators=(",", ":"))
        shards.append({"f": fn, "n": len(arr), "from": si})

    # ---- 统计
    #
    # ⚠ 口径踩过坑：早先这里用 `fam < 0` 判孤图，结果只数出 1 张
    # （那唯一一张解不出的图）。因为聚族给**每一张**图都分配了族号——
    # 找不到伙伴的也各成一个单成员族，所以 `fam` 永远是 >= 0。
    #
    # 正确的口径是看**族的规模**：`n == 1` 的族里的那张图才是孤图。
    # 同理"族数"要分开说：20,743 里 19,228 个是单成员族，
    # 把它当成"分出了 2 万个组"会让人对成果产生错误印象。
    n_orphan = sum(1 for f in fams if f["n"] == 1)
    n_grouped = sum(1 for f in fams if f["n"] > 1)
    n_grouped_imgs = sum(f["n"] for f in fams if f["n"] > 1)
    stats = {
        "总图": ntex,
        "解出": sum(1 for t in texs if t["decoded"] == 1),
        "解不出": sum(1 for t in texs if t["decoded"] != 1),
        "族数": len(fams),
        "有伴族": n_grouped,          # 真正"分出了组"的族
        "有伴图": n_grouped_imgs,     # 落在这些族里的图
        "孤图": n_orphan,             # 独占一个族
    }
    codec_dist = Counter((t["catalog_codec"] or "?") for t in texs if t["decoded"] == 1)
    size_dist = Counter("%dx%d" % (t["declared_w"], t["declared_h"]) for t in texs if t["decoded"] == 1)
    fam_hist = Counter()
    for f in fams:
        n = f["n"]
        b = ("1" if n == 1 else "2" if n == 2 else "3-4" if n <= 4 else
             "5-9" if n <= 9 else "10-24" if n <= 24 else "25-49" if n <= 49 else
             "50-99" if n <= 99 else "100-199" if n <= 199 else "200+")
        fam_hist[b] += 1

    payload = {
        "meta": meta,
        "stats": stats,
        "fams": fams,
        "shards": shards,
        "keys": keys,
        "codec": codec_dist.most_common(12),
        "size": size_dist.most_common(16),
        "famHist": [kv for kv in fam_hist.items()],
        "thumb": a.thumb_rel,
        "gen": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    html = TEMPLATE.replace("/*__DATA__*/", json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(html)

    print("墙面已生成 %s（%.2f MB）" % (a.out, os.path.getsize(a.out) / 1048576.0))
    print("分片 %d 个 → %s" % (len(shards), os.path.join(outdir, "meta")))
    print("图片 %d 张 · 解出 %d / 解不出 %d"
          % (stats["总图"], stats["解出"], stats["解不出"]))
    print("族 %d 个，其中真分出组的 %d 个（覆盖 %d 张）；孤图 %d 张（%.1f%%）"
          % (stats["族数"], stats["有伴族"], stats["有伴图"],
             stats["孤图"], 100.0 * stats["孤图"] / max(1, stats["总图"])))


TEMPLATE = r"""<!doctype html>
<html lang="zh-CN"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>无名贴图考古墙</title>
<style>
:root{
  --bg:#f6f7f9; --panel:#fff; --line:#e3e6ea; --ink:#1f2328; --dim:#6b7280;
  --acc:#2563eb; --accbg:#eef3fe; --warn:#b45309; --warnbg:#fef7ec;
  --ok:#047857; --okbg:#ecfdf5;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font:13px/1.55 "Microsoft YaHei",system-ui,-apple-system,sans-serif}
header{position:sticky;top:0;z-index:20;background:rgba(255,255,255,.94);
  backdrop-filter:blur(8px);border-bottom:1px solid var(--line);padding:11px 18px}
h1{margin:0 0 3px;font-size:16px;font-weight:600;letter-spacing:.2px}
.sub{color:var(--dim);font-size:12px}
.sub b{color:var(--ink);font-weight:600}
.bar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-top:9px}
input,select{padding:6px 10px;background:#fff;border:1px solid var(--line);border-radius:7px;
  color:var(--ink);font-size:12.5px;font-family:inherit}
input:focus,select:focus{outline:2px solid var(--accbg);border-color:var(--acc)}
input#q{width:230px}
button{padding:6px 12px;background:#fff;border:1px solid var(--line);border-radius:7px;
  cursor:pointer;font-size:12.5px;color:var(--ink);font-family:inherit}
button:hover{border-color:var(--acc);color:var(--acc)}
button.on{background:var(--accbg);border-color:var(--acc);color:var(--acc);font-weight:600}
.tabs{display:flex;gap:6px}
.cnt{color:var(--dim);font-size:12px;margin-left:auto}

main{padding:14px 18px 60px}
.tip{background:var(--warnbg);border:1px solid #f3dcb8;color:var(--warn);
  border-radius:8px;padding:9px 12px;font-size:12.5px;margin-bottom:14px}
.tip b{color:#8a4708}

/* 族卡片 */
.fam{background:var(--panel);border:1px solid var(--line);border-radius:10px;
  margin-bottom:12px;overflow:hidden}
.fh{display:flex;align-items:center;gap:10px;padding:9px 12px;cursor:pointer;
  border-bottom:1px solid transparent;user-select:none}
.fh:hover{background:#fafbfc}
.fam.open .fh{border-bottom-color:var(--line)}
.fn{font-weight:600;font-size:13px}
.badge{font-size:11px;padding:2px 7px;border-radius:20px;border:1px solid var(--line);
  color:var(--dim);background:#fbfcfd;white-space:nowrap}
.badge.tight{background:var(--okbg);color:var(--ok);border-color:#bfe8d6}
.badge.loose{background:var(--warnbg);color:var(--warn);border-color:#f3dcb8}
.badge.n1{background:#f3f4f6;color:#6b7280}
.fm{color:var(--dim);font-size:11.5px;font-family:consolas,monospace}
.fh .sp{margin-left:auto}
.tagbox{display:flex;gap:5px;align-items:center}
.taginput{padding:3px 8px;font-size:11.5px;width:130px}
.grow{padding:10px 12px 12px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(104px,1fr));gap:7px}
.cell{position:relative;background:#f0f2f5;border:1px solid var(--line);border-radius:7px;
  padding:4px;cursor:pointer;display:flex;flex-direction:column;gap:3px}
.cell:hover{border-color:var(--acc);box-shadow:0 1px 5px rgba(37,99,235,.14)}
.box{height:78px;display:flex;align-items:center;justify-content:center;overflow:hidden;
  border-radius:5px;background:
   repeating-conic-gradient(#e8ebef 0 25%,#f2f4f7 0 50%) 0 0/12px 12px}
.box img{max-width:100%;max-height:78px;object-fit:contain;display:block}
.hs{font-size:9.5px;color:var(--dim);font-family:consolas,monospace;text-align:center;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.grey{display:flex;flex-direction:column;align-items:center;justify-content:center;
  height:100%;color:#9aa0a6;font-size:10.5px;text-align:center;line-height:1.3;padding:2px}
.cell.greyed .box{background:#eceef1}
.tagmark{position:absolute;top:5px;right:5px;background:var(--acc);color:#fff;
  font-size:9px;padding:1px 5px;border-radius:8px;max-width:70px;overflow:hidden;
  text-overflow:ellipsis;white-space:nowrap}

/* 大图面板 */
.mask{position:fixed;inset:0;background:rgba(17,20,24,.72);display:none;
  align-items:center;justify-content:center;padding:20px;z-index:50}
.mask.on{display:flex}
.panel{background:#fff;border-radius:12px;max-width:min(900px,95vw);max-height:92vh;
  overflow:auto;padding:18px;box-shadow:0 12px 40px rgba(0,0,0,.3)}
.panel .big{width:100%;max-height:52vh;object-fit:contain;display:block;margin:0 auto 14px;
  background:repeating-conic-gradient(#eef1f4 0 25%,#f7f9fb 0 50%) 0 0/16px 16px;border-radius:8px}
.kv{display:grid;grid-template-columns:74px 1fr;gap:5px 12px;font-size:12.5px}
.kv .k{color:var(--dim)}
.mono{font-family:consolas,monospace;font-size:12px;word-break:break-all}
.close{float:right;cursor:pointer;color:var(--dim);font-size:22px;line-height:1;
  padding:0 4px}
.close:hover{color:var(--ink)}
.pn{display:flex;gap:8px;margin-top:14px;align-items:center;flex-wrap:wrap}
.pn .sp{margin-left:auto;color:var(--dim);font-size:12px}
footer{color:var(--dim);font-size:11.5px;padding:0 18px 30px}
.loadmore{text-align:center;padding:18px}
</style></head>
<body>
<header>
  <h1>无名贴图考古墙</h1>
  <div class="sub" id="sub"></div>
  <div class="bar">
    <div class="tabs">
      <button id="tFam" class="on">按族看</button>
      <button id="tAll">单张平铺</button>
      <button id="tTag">只看有标签</button>
    </div>
    <input id="q" placeholder="搜 hash / 尺寸 / 编码">
    <select id="fcodec"><option value="">全部编码</option></select>
    <select id="fsize"><option value="">全部尺寸</option></select>
    <!-- 族规模筛选。默认"≥2 张"：全库 20,743 个族里 19,228 个是单成员族，
         若默认全列，真正分出组的 1,515 个族会被 1.9 万条孤图埋掉，
         人打开页面看到的就是一片"孤图"，误以为聚族失败。
         孤图当然也要能看——选"全部"或"只看孤图"即可。 -->
    <select id="fnum">
      <option value="ge2" selected>成组（≥2 张）</option>
      <option value="all">全部（含孤图）</option>
      <option value="only1">只看孤图</option>
    </select>
    <select id="fsort">
      <option value="fam">族大小</option>
      <option value="n">族序号</option>
    </select>
    <button id="expTags">导出标签</button>
    <span class="cnt" id="cnt"></span>
  </div>
</header>
<div class="tip">
  <b>这是「考古墙」，不是「自动识别」。</b>
  这 <b id="tN"></b> 张图在客户端里本来就没有名字（打包时就剥掉了，不是解析器漏了）。
  这里做的只是：<b>按内容把它们摆到一起</b>，让人用眼睛看一眼说「这一堆像什么」。
  标签打在<b>族</b>上，因为人认的是「这一堆」，不是某一张。
  没解出像素的图显示灰卡并写明原因——<b>绝不拿别的图冒充</b>。
</div>
<main id="main"></main>
<footer id="foot"></footer>
<div class="mask" id="mask"><div class="panel" id="panel"></div></div>

<script>
const D = /*__DATA__*/;
const LSKEY = "tlbb_wall_tags_v1";

/* ---------------- 数据访问：分片懒加载 ---------------- */
const shardCache = new Map();
let allRows = null;          // 全部加载后的扁平数组（搜索时才全量加载）
let loadedShards = 0;

async function loadShard(s){
  if(shardCache.has(s.f)) return shardCache.get(s.f);
  const r = await fetch(s.f).then(x=>x.json());
  shardCache.set(s.f, r.rows);
  loadedShards++;
  return r.rows;
}
const K = D.keys;
const gi = k => K.indexOf(k);
function rowObj(a){
  const o = {};
  for(let i=0;i<K.length;i++) o[K[i]] = a[i];
  return o;
}
async function ensureAll(){
  if(allRows) return allRows;
  const parts = [];
  for(const s of D.shards) parts.push(await loadShard(s));
  allRows = [];
  for(const p of parts) for(const a of p) allRows.push(rowObj(a));
  return allRows;
}

/* ---------------- 标签 ---------------- */
let TAGS = {};
try{ TAGS = JSON.parse(localStorage.getItem(LSKEY) || "{}"); }catch(e){ TAGS = {}; }
function saveTags(){
  localStorage.setItem(LSKEY, JSON.stringify(TAGS));
}
function tagOf(fid){ return TAGS[fid] || null; }
function setTag(fid, txt){
  if(txt && txt.trim()) TAGS[fid] = {t: txt.trim(), at: new Date().toISOString().slice(0,16).replace("T"," ")};
  else delete TAGS[fid];
  saveTags();
}

/* ---------------- 工具 ---------------- */
const fmt = n => n.toLocaleString("zh-CN");
const esc = s => String(s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const kb = n => n < 1024 ? n+" B" : n < 1048576 ? (n/1024).toFixed(1)+" KB" : (n/1048576).toFixed(2)+" MB";

const THUMB = (DATA.thumb || "thumb/");
function thumbHtml(r){
  if(r.ok != 1){
    return '<div class="grey">解不出像素<br>' + esc(shortReason(r.fr)) + '</div>';
  }
  return '<img loading="lazy" src="' + THUMB + r.h + '.png" alt="">';
}
function shortReason(s){
  s = s || "未记录原因";
  const map = [
    ["WEBP 内嵌流（未解码）", "WEBP 内嵌"],
    ["pak 索引里没有这条", "pak 无此条"],
    ["偏移与目录不符", "偏移不符"],
  ];
  for(const [a,b] of map) if(s.indexOf(a) >= 0) return b;
  if(s.indexOf("JMT1 解码失败") >= 0) return "JMT1 解码失败";
  return s.slice(0, 14);
}

/* ---------------- 渲染：族视图 ---------------- */
let state = { mode:"fam", q:"", codec:"", size:"", num:"ge2", sort:"fam", limit:60 };

function famCodec(f){
  const c = {};
  for(const h of f.members.slice(0, 200)){
    // 成员编码从行数据取，但族视图可能还没加载该片；用族摘要的多数编码即可
  }
  return f.codec;
}
function matchFam(f){
  // 族规模：孤图（n==1）默认不列，避免把真正成组的族埋掉
  if(state.num === "ge2" && f.n < 2) return false;
  if(state.num === "only1" && f.n !== 1) return false;
  if(state.codec && f.codec !== state.codec) return false;
  if(state.size && (f.w + "x" + f.h) !== state.size) return false;
  if(state.q){
    const q = state.q.toLowerCase();
    if(f.members.some(h => h.indexOf(q) >= 0)) return true;
    if((f.rep_hash||"").indexOf(q) >= 0) return true;
    if(String(f.n) === q) return true;
    return false;
  }
  return true;
}

function renderFam(){
  const main = document.getElementById("main");
  let fams = D.fams.filter(matchFam);
  if(state.sort === "n") fams = fams.slice().sort((a,b)=>a.fid-b.fid);
  const shown = fams.slice(0, state.limit);
  const total = fams.reduce((s,f)=>s+f.n, 0);

  document.getElementById("cnt").textContent =
    "族 " + fmt(fams.length) + " 个 · 覆盖 " + fmt(total) + " 张" +
    (state.num === "ge2" ? "（孤图已隐藏，可在右上切换）" : "");

  let h = "";
  for(const f of shown){
    const tg = tagOf(f.fid);
    const cls = f.n === 1 ? "n1" : (f.tightness === "tight" ? "tight" : f.tightness === "loose" ? "loose" : "");
    const lab = f.n === 1 ? "孤图" : (f.tightness === "tight" ? "紧族" : f.tightness === "loose" ? "松族" : "混族");
    h += '<div class="fam' + (tg ? ' open' : '') + '" data-fid="' + f.fid + '">';
    h += '<div class="fh">';
    h += '<span class="fn">族 ' + f.fid + '</span>';
    h += '<span class="badge ' + cls + '">' + lab + '</span>';
    h += '<span class="badge">' + fmt(f.n) + ' 张</span>';
    if(f.n > 1) h += '<span class="badge">族内均距 ' + f.mean_d + '</span>';
    h += '<span class="badge">' + esc(f.codec||"?") + ' ' + f.w + '×' + f.h + '</span>';
    h += '<span class="fm">' + (f.rep_hash||"").slice(0,16) + '</span>';
    h += '<span class="sp"></span>';
    h += '<span class="tagbox">';
    h += '<input class="taginput" placeholder="打标签…" value="' + (tg ? esc(tg.t) : "") + '" data-tag="' + f.fid + '">';
    h += '</span>';
    h += '</div>';
    if(tg || f.n <= 24){
      h += '<div class="grow"><div class="grid">';
      const mem = f.members.slice(0, 240);
      for(const mh of mem){
        h += cellHtml(mh, tg ? tg.t : "", f.fid);
      }
      h += '</div>';
      if(f.members.length > 240)
        h += '<div class="loadmore">…本族还有 ' + fmt(f.members.length-240) + ' 张，用搜索按 hash 定位</div>';
      h += '</div>';
    }
    h += '</div>';
  }
  if(fams.length > state.limit){
    h += '<div class="loadmore"><button onclick="moreFam()">继续加载（还有 ' +
         fmt(fams.length - state.limit) + ' 个族）</button></div>';
  }
  main.innerHTML = h;
  bindCells();
  bindTags();
  bindFamToggle();
}

let CELL_ROWS = new Map();
async function ensureCellRows(hashList){
  // 族视图按需把该批 hash 的行元数据拉出来
  const need = hashList.filter(h => !CELL_ROWS.has(h));
  if(!need.length) return;
  const want = new Set(need);
  for(const s of D.shards){
    if(want.size === 0) break;
    const rows = await loadShard(s);
    for(const a of rows){
      const h = a[0];
      if(want.has(h)){ CELL_ROWS.set(h, rowObj(a)); want.delete(h); }
    }
  }
}

function cellHtml(h, tag, fid){
  return '<div class="cell" data-h="' + h + '" data-fid="' + fid + '">' +
    (tag ? '<div class="tagmark">' + esc(tag) + '</div>' : '') +
    '<div class="box" data-box="' + h + '"></div>' +
    '<div class="hs">' + h.slice(0,12) + '</div></div>';
}

async function fillBoxes(){
  // 先把需要的行拉齐，再统一填图，避免一格子一次网络
  const boxes = document.querySelectorAll(".box[data-box]");
  const list = [...boxes].map(b => b.getAttribute("data-box"));
  if(!list.length) return;
  await ensureCellRows(list);
  for(const b of boxes){
    const h = b.getAttribute("data-box");
    if(b.dataset.done) continue;
    const r = CELL_ROWS.get(h);
    b.innerHTML = r ? thumbHtml(r) : '<div class="grey">…</div>';
    b.dataset.done = "1";
  }
}

function bindCells(){
  fillBoxes();
  document.querySelectorAll(".cell").forEach(c => {
    c.onclick = () => openBig(c.getAttribute("data-h"), Number(c.getAttribute("data-fid")));
  });
}
function bindTags(){
  document.querySelectorAll("input[data-tag]").forEach(inp => {
    inp.onclick = e => e.stopPropagation();
    const commit = () => {
      setTag(Number(inp.getAttribute("data-tag")), inp.value);
      renderFam();
    };
    inp.onblur = commit;
    inp.onkeydown = e => { if(e.key === "Enter"){ inp.blur(); } e.stopPropagation(); };
  });
}
function bindFamToggle(){
  document.querySelectorAll(".fam .fh").forEach(fh => {
    fh.onclick = e => {
      if(e.target.tagName === "INPUT") return;
      const f = fh.parentElement;
      f.classList.toggle("open");
      if(f.classList.contains("open")) fillBoxes();
    };
  });
}
function moreFam(){ state.limit += 80; renderFam(); }

/* ---------------- 渲染：单张平铺 ---------------- */
let flatIdx = 0;
async function renderAll(){
  const main = document.getElementById("main");
  main.innerHTML = '<div class="loadmore">正在载入全部元数据…</div>';
  const rows = await ensureAll();
  let list = rows;
  if(state.codec) list = list.filter(r => (r.cc||"") === state.codec);
  if(state.size) list = list.filter(r => (r.dw + "x" + r.dh) === state.size);
  if(state.q){
    const q = state.q.toLowerCase();
    list = list.filter(r => r.h.indexOf(q) >= 0);
  }
  document.getElementById("cnt").textContent = fmt(list.length) + " 张";
  let h = '<div class="grid">';
  const cap = 600;
  for(const r of list.slice(0, cap))
    h += '<div class="cell' + (r.ok==1?'':' greyed') + '" data-h="' + r.h + '">' +
         '<div class="box">' + thumbHtml(r) + '</div>' +
         '<div class="hs">' + r.h.slice(0,12) + '</div></div>';
  h += '</div>';
  if(list.length > cap)
    h += '<div class="loadmore">只画了前 ' + cap + ' 张。用上面的搜索框按 hash 精确定位，或切回「按族看」。</div>';
  main.innerHTML = h;
  document.querySelectorAll(".cell").forEach(c => {
    c.onclick = () => openBig(c.getAttribute("data-h"), -1);
  });
}

/* ---------------- 渲染：只看有标签 ---------------- */
function renderTagged(){
  const ids = Object.keys(TAGS).map(Number);
  if(!ids.length){
    document.getElementById("main").innerHTML =
      '<div class="tip">还没有任何标签。回到「按族看」，在族标题右边输入框里打上第一笔。</div>';
    document.getElementById("cnt").textContent = "0";
    return;
  }
  const fams = D.fams.filter(f => TAGS[f.fid]);
  document.getElementById("cnt").textContent = fams.length + " 个族有标签";
  let h = "";
  for(const f of fams){
    const tg = TAGS[f.fid];
    h += '<div class="fam open"><div class="fh">' +
      '<span class="fn">族 ' + f.fid + '</span>' +
      '<span class="badge">' + fmt(f.n) + ' 张</span>' +
      '<span class="badge tight">' + esc(tg.t) + '</span>' +
      '<span class="fm">' + tg.at + '</span>' +
      '<span class="sp"></span>' +
      '<span class="tagbox"><button onclick="delTag(' + f.fid + ')">删标签</button></span>' +
      '</div><div class="grow"><div class="grid">';
    for(const mh of f.members.slice(0, 240)) h += cellHtml(mh, "", f.fid);
    h += '</div></div></div>';
  }
  document.getElementById("main").innerHTML = h;
  bindCells();
}
function delTag(fid){
  setTag(fid, "");
  renderTagged();
}

/* ---------------- 大图面板 ---------------- */
let curHash = null, curFam = -1;
async function openBig(h, fid){
  curHash = h; curFam = fid;
  let r = CELL_ROWS.get(h);
  if(!r){
    await ensureCellRows([h]);
    r = CELL_ROWS.get(h);
  }
  if(!r){
    const all = await ensureAll();
    r = all.find(x => x.h === h);
  }
  const p = document.getElementById("panel");
  const tg = fid >= 0 ? tagOf(fid) : null;
  let hh = '<span class="close" onclick="closeBig()">×</span>';
  hh += '<div style="font-size:14px;font-weight:600;margin-bottom:10px">' +
        (fid >= 0 ? "族 " + fid : "单张") + '</div>';
  if(r && r.ok == 1){
    hh += '<img class="big" src="' + THUMB + h + '.png" alt="">';
  } else {
    hh += '<div class="big grey" style="height:160px">解不出像素<div style="margin-top:6px;color:#b45309">' +
          esc(r ? r.fr : "无记录") + '</div></div>';
  }
  hh += '<div class="kv">';
  const row = (k,v,mono) => '<div class="k">' + k + '</div><div class="' + (mono?'mono':'') + '">' + v + '</div>';
  hh += row("哈希", h, true);
  if(r){
    hh += row("所在包", esc(r.pk||"?"));
    hh += row("偏移", fmt(r.of) + "（gen " + r.g + "）");
    hh += row("原始大小", kb(r.or) + "（" + fmt(r.or) + " B）");
    hh += row("目录编码", esc(r.cc || "?"));
    hh += row("目录尺寸", r.dw + " × " + r.dh);
    if(r.ok == 1){
      hh += row("实测尺寸", r.w + " × " + r.ht);
      hh += row("mip 层数", r.mi);
      hh += row("dHash", '<span class="mono">' + r.dh2 + '</span>');
      hh += row("平均色", "R" + r.mr + " G" + r.mg + " B" + r.mb + " A" + r.ma);
      hh += row("亮度标准差", r.ls + (r.ls < 3 ? '  <span style="color:#b45309">（近似纯色，dHash 参考价值低）</span>' : ""));
      hh += row("边缘能量", r.eg);
      hh += row("不透明占比", (r.ac*100).toFixed(1) + "%");
    } else {
      hh += row("状态", '<span style="color:#b45309">解不出像素</span>');
      hh += row("原因", esc(r.fr));
    }
    hh += row("所属族", fid >= 0 ? ("族 " + fid + "（" + (tg?esc(tg.t):"未打标签") + "）") : "—");
  }
  hh += '</div>';
  hh += '<div class="pn">';
  if(fid >= 0) hh += '<input class="taginput" id="pTag" placeholder="给这一族打标签…" value="' + (tg?esc(tg.t):"") + '" style="width:200px">';
  if(fid >= 0) hh += '<button onclick="saveBigTag()">保存标签</button>';
  hh += '<span class="sp">' + (r && r.ok==1 ? "缩略图由客户端字节实解，非替换" : "") + '</span>';
  hh += '</div>';
  p.innerHTML = hh;
  if(fid >= 0){
    const inp = document.getElementById("pTag");
    inp.onkeydown = e => { if(e.key === "Enter") saveBigTag(); };
  }
  document.getElementById("mask").classList.add("on");
}
function saveBigTag(){
  const inp = document.getElementById("pTag");
  if(!inp) return;
  setTag(curFam, inp.value);
  closeBig();
  if(state.mode === "tag") renderTagged(); else renderFam();
}
function closeBig(){
  document.getElementById("mask").classList.remove("on");
}
document.getElementById("mask").onclick = e => { if(e.target.id === "mask") closeBig(); };
document.addEventListener("keydown", e => { if(e.key === "Escape") closeBig(); });

/* ---------------- 交互 ---------------- */
function setMode(m){
  state.mode = m;
  state.limit = 60;
  for(const [id,v] of [["tFam","fam"],["tAll","all"],["tTag","tag"]])
    document.getElementById(id).classList.toggle("on", v === m);
  if(m === "fam") renderFam();
  else if(m === "all") renderAll();
  else renderTagged();
}
document.getElementById("tFam").onclick = () => setMode("fam");
document.getElementById("tAll").onclick = () => setMode("all");
document.getElementById("tTag").onclick = () => setMode("tag");

let qtimer = null;
document.getElementById("q").oninput = e => {
  state.q = e.target.value.trim();
  clearTimeout(qtimer);
  qtimer = setTimeout(() => setMode(state.mode), 260);
};
document.getElementById("fcodec").onchange = e => { state.codec = e.target.value; setMode(state.mode); };
document.getElementById("fsize").onchange = e => { state.size = e.target.value; setMode(state.mode); };
document.getElementById("fsort").onchange = e => { state.sort = e.target.value; setMode(state.mode); };
document.getElementById("fnum").onchange = e => { state.num = e.target.value; setMode(state.mode); };

document.getElementById("expTags").onclick = () => {
  const out = {
    生成时间: new Date().toISOString(),
    说明: "无名贴图考古墙的人工标签。标签打在族(fid)上。",
    基库: D.meta,
    标签: TAGS,
  };
  const blob = new Blob([JSON.stringify(out, null, 2)], {type:"application/json"});
  const a2 = document.createElement("a");
  a2.href = URL.createObjectURL(blob);
  a2.download = "考古墙标签.json";
  a2.click();
  setTimeout(() => URL.revokeObjectURL(a2.href), 3000);
};

/* ---------------- 启动 ---------------- */
(function init(){
  const s = D.stats;
  document.getElementById("tN").textContent = fmt(s.总图);
  document.getElementById("sub").innerHTML =
    "共 <b>" + fmt(s.总图) + "</b> 张无名贴图 ｜ " +
    "解出像素 <b>" + fmt(s.解出) + "</b> ｜ " +
    "解不出 <b>" + fmt(s.解不出) + "</b>（灰卡，不冒充） ｜ " +
    "聚出有伴的族 <b>" + fmt(s.有伴族) + "</b> 个（覆盖 <b>" + fmt(s.有伴图) + "</b> 张） ｜ " +
    "孤图 <b>" + fmt(s.孤图) + "</b> 张";
  const fc = document.getElementById("fcodec");
  for(const [c,n] of D.codec){
    const o = document.createElement("option");
    o.value = c; o.textContent = c + "（" + fmt(n) + "）";
    fc.appendChild(o);
  }
  const fs = document.getElementById("fsize");
  for(const [z,n] of D.size){
    const o = document.createElement("option");
    o.value = z; o.textContent = z + "（" + fmt(n) + "）";
    fs.appendChild(o);
  }
  let fh = "族大小分布：";
  for(const [b,n] of D.famHist) fh += b + " 张的族 <b>" + fmt(n) + "</b> 个 ｜ ";
  fh += "聚族阈值来自标定：≤8 位孪生 / ≤16 位同族。";
  document.getElementById("foot").innerHTML = fh +
    "<br>生成于 " + D.gen + " ｜ 数据源 wall.db ｜ 缩略图由客户端字节实解，未做任何替换或美化。";
  renderFam();
})();
</script>
</body></html>
"""


if __name__ == "__main__":
    main()
