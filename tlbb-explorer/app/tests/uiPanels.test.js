// 新增 UI 模块的接线防呆：panels.js / relations.js / index.html 三方对齐。
// 跑法（在 app/ 下）：node --test tests/uiPanels.test.js
//
// 与别的测试同一套路：DOM 在 node 里开不了，只能钉源码与 id 对应关系。
// 重点盯两件事：① 新模块 el("x") 引用的 id 在 index.html 里都真有；
// ② 详情标签页的 data-pane 与 HTML 里的 tabpane 一一对上。

import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const web = join(here, "..", "web");

const html = readFileSync(join(web, "index.html"), "utf8");
const panels = readFileSync(join(web, "panels.js"), "utf8");
const relations = readFileSync(join(web, "relations.js"), "utf8");
const detail = readFileSync(join(web, "detail.js"), "utf8");

/// 提取一份源码里所有 el("id") 的静态 id 引用。
function idsIn(src) {
  return [...src.matchAll(/el\("([^"]+)"\)/g)].map((m) => m[1]);
}

const TABS = ["preview", "resource", "relations", "missing", "files", "origin"];

test("panels.js 引用的每个元素 id 都在 index.html 里", () => {
  const used = idsIn(panels);
  assert.ok(used.length > 6, `应能提取到 id 引用，实际 ${used.length}`);
  const missing = [...new Set(used)].filter((id) => !html.includes(`id="${id}"`));
  assert.deepEqual(missing, [], `这些 id 在 index.html 里找不到：${missing.join(", ")}`);
});

test("relations.js 引用的每个元素 id 都在 index.html 里", () => {
  const used = idsIn(relations);
  assert.ok(used.length > 3, `应能提取到 id 引用，实际 ${used.length}`);
  const missing = [...new Set(used)].filter((id) => !html.includes(`id="${id}"`));
  assert.deepEqual(missing, [], `这些 id 在 index.html 里找不到：${missing.join(", ")}`);
});

test("detail.js 引用的每个元素 id 都在 index.html 里", () => {
  const used = idsIn(detail);
  // texSlotPick 是 lib/textureState.js 铺候选卡时动态生成的 <select>，
  // 不在 index.html 里，属于白名单（textureState.test.js 另有断言盯着它）。
  const dynamic = new Set(["texSlotPick"]);
  const missing = [...new Set(used)].filter((id) => !dynamic.has(id) && !html.includes(`id="${id}"`));
  assert.deepEqual(missing, [], `这些 id 在 index.html 里找不到：${missing.join(", ")}`);
});

test("六个标签按钮的 data-tab 与六个面板的 data-pane 一一对上", () => {
  const tabs = [...html.matchAll(/class="tab[^"]*"\s+data-tab="([^"]+)"/g)].map((m) => m[1]);
  // 第一个「预览」标签 class 是 "tab on"，单独补一遍正则匹配
  const allTabs = [...html.matchAll(/data-tab="([^"]+)"/g)].map((m) => m[1]);
  assert.ok(allTabs.length >= TABS.length, `标签数不足：${allTabs.join(",")}`);
  const panes = [...html.matchAll(/data-pane="([^"]+)"/g)].map((m) => m[1]);
  for (const t of TABS) {
    assert.ok(allTabs.includes(t), `缺标签按钮 data-tab=${t}`);
    assert.ok(panes.includes(t), `缺面板 data-pane=${t}`);
  }
  assert.equal(new Set(allTabs).size, allTabs.length, "标签 data-tab 不许重复");
  assert.equal(new Set(panes).size, panes.length, "面板 data-pane 不许重复");
  void tabs;
});

test("切标签只改一处：按钮高亮与面板显隐同源", () => {
  const seg = panels.slice(panels.indexOf("export function showTabPane"), panels.indexOf("let tabsWired"));
  assert.match(seg, /classList\.toggle\("on", b\.dataset\.tab === name\)/);
  assert.match(seg, /p\.hidden = p\.dataset\.pane !== name/);
});

test("换资产回到「预览」标签：不让人对着上一条的缺失清单发懵", () => {
  assert.match(detail, /showTabPane\("preview"\)/);
});

test("失败/未就绪也要把右栏清干净，不留上一条的概况", () => {
  const seg = detail.slice(detail.indexOf("export async function showDetail"));
  assert.ok((seg.match(/paintSide\(null\)/g) || []).length >= 2, "未就绪与失败两条路都要收右栏");
  assert.ok((seg.match(/paintFixBar/g) || []).length >= 2, "修复条也要跟着收");
});

test("修复建议条只在真有缺失时出现，且跳的是「缺失资源」标签", () => {
  const seg = panels.slice(panels.indexOf("export function paintFixBar"));
  assert.match(seg, /if \(!gaps\.length\) \{/, "空列表才收起条子");
  assert.match(seg, /showTabPane\("missing"\)/);
  // 条子挂在滚动容器外面，才能稳在详情栏底边而不是随内容浮动。
  assert.match(seg, /el\("fixBarHost"\)/);
  assert.match(html, /id="fixBarHost"/);
  assert.ok(!/host\.append\(bar\)/.test(seg), "别再往可滚的正文里塞条子");
});

test("关系网浮层：从顶栏与详情都能进，Esc 能退", () => {
  assert.match(relations, /el\("openRelations"\)\.addEventListener/);
  assert.match(relations, /el\("btnRel"\)\.addEventListener/);
  assert.match(relations, /el\("profRelOpen"\)\.addEventListener/);
  assert.match(html, /id="openRelations"/);
  assert.match(html, /id="relations"[^>]*hidden/);
});

test("关系网只画回包里真有的类别，缺的不省略（0 命中本身是结论）", () => {
  const seg = relations.slice(relations.indexOf("function buildGraph"), relations.indexOf("function nodeSvg"));
  assert.match(seg, /for \(const m of insp\.members \|\| \[\]\)/, "成员一律入图");
  assert.match(seg, /for \(const s of b\.textureSlots \|\| \[\]\)/, "材质槽一律入图");
  assert.ok(!/slice\(0, \d+\)/.test(seg), "不许悄悄截断：截了就等于把缺的藏起来");
});

test("关系网的边只在回包里有对应项时才画（命名相似不算引用）", () => {
  const seg = relations.slice(relations.indexOf("const edges = []"));
  assert.match(seg, /pos\.get\(n\.id\)/);
  assert.match(seg, /if \(!p\) continue;/);
});

// ---- 长名字的排版防呆 ----
//
// 曾经的症状：详情大标题「w1351_nan_s_shukuanganxiang_001」折成两截
// （「…shukuanganxiang_」+「001」），右栏「类型：界面资源」也被后面折行的
// 名字顶歪，看着像两行数据串了。数据没错，是排版。三处一起钉住。

test("详情大标题走 titleHtml（下划线后断行），不许退回裸 textContent", () => {
  assert.match(detail, /import \{[^}]*titleHtml[^}]*\} from "\.\/lib\/wording\.js"/s);
  assert.match(detail, /el\("dName"\)\.innerHTML = titleHtml\(/);
  assert.ok(!/el\("dName"\)\.textContent/.test(detail), "退回 textContent 就没有 <wbr> 断点了");
});

test("概况表的 dd 能收缩：min-width:0 与 flex 缺一不可", () => {
  const css = readFileSync(join(web, "style.css"), "utf8");
  const seg = css.slice(css.indexOf(".kv dd {"), css.indexOf(".kv dd.mono"));
  assert.ok(seg.length > 0, "找不到 .kv dd 规则");
  assert.match(seg, /min-width:\s*0/, "不给 min-width:0，长名字会把 dt 挤走");
  assert.match(seg, /flex:\s*1/, "dd 要能吃满剩余宽度");
  assert.match(seg, /overflow-wrap:\s*anywhere/, "长无空格串必须能折");
});

test("长标题不硬折：用 break-word 而不是 everywhere", () => {
  const css = readFileSync(join(web, "style.css"), "utf8");
  const seg = css.slice(css.indexOf(".d-head h2 {"), css.indexOf(".d-head h2 {") + 200);
  assert.ok(!/overflow-wrap:\s*anywhere/.test(seg), "anywhere 会在任意字符处硬折，读者看到半截名字");
  assert.match(seg, /overflow-wrap:\s*break-word/);
});

// ---- 「组成成员」不许再被叫成「引用关系」 ----
//
// 侧栏和标签页那两个数字数的是 members（这组登记的文件），
// 不是 refs（引用边，另一张表，且不在 asset_inspect 回包里）。
// 把成员数标成「引用关系」正是项目纪律里「命名推断 ≠ 引用」禁止的事。

test("详情里数成员的地方一律叫「组成成员」，不许写「引用关系」", () => {
  assert.match(html, /data-tab="relations"[^>]*>组成成员/, "标签名要跟它数的东西对上");
  assert.match(html, /组成成员 <em id="profRefCount"><\/em>/, "侧栏标题同理");
  assert.ok(!/>引用关系 <em id="tabRelCount"/.test(html), "标签不许再写「引用关系」");
  assert.ok(!/>引用关系 <em id="profRefCount"/.test(html), "侧栏不许再写「引用关系」");
});

test("统计函数叫 memberStats：名字本身说明它数的是什么", () => {
  assert.match(panels, /function memberStats\(insp\)/);
  assert.ok(!/function refStats\(/.test(panels), "refStats 这个名字在骗人，已经改名");
  assert.ok(!/refStats\(/.test(panels), "调用点也要一起改名");
  // 数据源必须是 members，不是 refs。
  const seg = panels.slice(panels.indexOf("function memberStats"), panels.indexOf("function paintSide"));
  assert.match(seg, /for \(const m of insp\.members \|\| \[\]\)/);
});

// ---- 地图页画布尺寸：列表一长，画布就被撑到两万像素 ----
//
// 实测（2026-11-03，无量山 w1351_ll_wls_001）：.map-wrap 不写 grid-template-rows
// 时那一行走 auto＝三个栏里最高的内容说了算。地图列表铺满 300 行 ≈ 22,500px，
// 整行被撑到 24,192px；.map-stage 跟着长，canvas{height:100%} 吃不到确定高度就
// 退回位图自带高度，syncViewport 再把量到的尺寸写回位图。俯视取景算在 24,192px
// 高的画布上，地图画在 1.2 万像素以下——读者点「俯视量测」看到的是一块空白，
// 状态栏却写着「2,240 件」。

test("地图页三栏的行高必须钉死，不许被列表撑起来", () => {
  const css = readFileSync(join(web, "style.css"), "utf8");
  const at = css.indexOf(".map-wrap {");
  assert.ok(at >= 0, "找不到 .map-wrap 规则");
  const seg = css.slice(at, css.indexOf("}", at));
  assert.match(seg, /grid-template-rows:\s*minmax\(0/, "行高要钉成 minmax(0,1fr)，否则隐式行走 auto＝最高内容说了算");
  assert.match(seg, /min-height:\s*0/, "父级不收缩，1fr 也吃不到视口高度");
});

test("俯视量测：画布盒变了要按新尺寸重算取景", () => {
  const top = readFileSync(join(web, "topdown.js"), "utf8");
  const map = readFileSync(join(web, "map.js"), "utf8");
  assert.match(top, /applyFit\(\) \{[\s\S]{0,400}tm\.fitView\(this\.fitOn, this\.size\.w, this\.size\.h/, "重算取景要吃当前尺寸");
  assert.match(top, /ensureFit\(\) \{[\s\S]{0,500}this\.applyFit\(\)/, "量出盒子差得远就得重算");
  // 两条入口：窗口缩放、「放大」铺满画布（走 tlbb:viewer-resize，不是 window.resize）
  assert.match(top, /addEventListener\("resize"[\s\S]{0,300}this\.ensureFit\(\)/, "窗口缩放要重算取景");
  assert.match(top, /addEventListener\("tlbb:viewer-resize"[\s\S]{0,300}this\.ensureFit\(\)/, "「放大」改了画布盒也要重算");
  // 同图切回不许退回裸 syncViewport+draw（那样取景还按旧盒子）
  assert.match(map, /t\.ensureFit\(\);/, "切回俯视要走 ensureFit");
  assert.ok(!/t\.syncViewport\(\);\s*\n\s*t\.draw\(\);/.test(map), "裸量尺寸+重画会留着按旧尺寸算出来的取景");
});

test("孤悬格的两句话要各自对得上做得到的事", () => {
  const top = readFileSync(join(web, "topdown.js"), "utf8");
  const map = readFileSync(join(web, "map.js"), "utf8");
  // 俯视那句「缩远可见」是承诺：下限必须真能罩住全体实例（实测某张图孤悬格在 5.5 万单位外，
  // 只按主簇 1/16 缩到底只有 6,153 单位视野，承诺兑现不了）。
  assert.match(top, /fitView\(this\.rects/, "俯视的缩放下限要按全体范围再放宽一次");
  // 立体面的远裁剪按主簇尺寸定，够不到那一格，就不许再说「缩远」。
  const at = map.indexOf("取景对准主簇");
  assert.ok(at >= 0, "立体侧要有取景口径那句");
  const seg = map.slice(at, at + 200);
  assert.match(seg, /这一面够不到/, "立体侧要如实说够不到");
  assert.ok(!/取景对准主簇[^）]*缩远/.test(map), "立体侧不许再承诺缩远");
});

test("地图信息栏不许替查询下结论：非网格那批只说「按名字没查到」", () => {
  const map = readFileSync(join(web, "map.js"), "utf8");
  const at = map.indexOf("本来就不是网格");
  assert.ok(at >= 0, "找不到那句");
  const seg = map.slice(at, at + 420);
  assert.match(seg, /按名字没查到/, "要说这条查询实际做了什么");
  assert.ok(!/文件在客户端里存在/.test(seg), "按名字没查到的东西不能写成「存在」——实测 mobile_maps* 下 .pu 一条都没有");
});

test("立体那一行要说「套上了几件」，不许只讲已贴图", () => {
  const map = readFileSync(join(web, "map.js"), "utf8");
  assert.match(map, /function grayStatus\(s, tex\)/, "状态行要有带实测数的版本");
  assert.match(map, /个模型套上了贴图/);
  assert.match(map, /贴图正在逐件核对/, "数还没数出来，不许先说已贴图");
  assert.ok(!/有材质表的已贴图，地形未解/.test(map), "旧的含糊话（不给分母）已撤");
  assert.match(map, /return \{ total: paths\.length, textured \}/, "套贴图的计数要回给状态行");
  // 数没数完都不能盖掉别的图的状态：回包要先过当前图这道闸。
  assert.match(map, /sceneId !== scene\.id \|\| mode !== "gray"/, "迟到的贴图数不许顶掉当前画面");
});

test("「缺失资源」页签要数这一页里那张表，不许数另一批东西", () => {
  const panels = readFileSync(join(web, "panels.js"), "utf8");
  assert.match(panels, /export function paintTabCounts\(insp, st\)/, "页签要拿到建好的状态（里面才有「缺什么」那张表）");
  assert.match(panels, /st\.gaps\.items\.length/);
  // 只看这两个函数的函数体：别处（文件清单那一栏）用 insp.missing 是它自己的事。
  const body = panels.slice(panels.indexOf("export function paintTabCounts"), panels.indexOf("// ---- 文件清单"));
  assert.ok(!/insp\.missing/.test(body.replace(/\/\/[^\n]*/g, "")), "页签不许再数 insp.missing——这一页没有那张列表");
  const bar = panels.slice(panels.indexOf("export function paintFixBar"));
  assert.match(bar, /st && st\.gaps \? st\.gaps\.items/, "修复建议条也要数同一批");
  assert.match(bar, /num\(\s*gaps\.length,/s, "数的是条数，不是把数组塞进 num()");
  const detail = readFileSync(join(web, "detail.js"), "utf8");
  assert.match(detail, /paintTabCounts\(insp, st\)/, "调用点要一起把状态传进去");
});

test("修复建议条不替缺失猜原因——逐条原因交给「缺失资源」那一页", () => {
  const panels = readFileSync(join(web, "panels.js"), "utf8");
  const seg = panels.slice(panels.indexOf("export function paintFixBar"));
  assert.match(seg, /逐条原因见「缺失资源」这一页/);
  // 注释里会引用被撤掉的那句原话，断言只看代码本体。
  const code = seg.replace(/\/\/[^\n]*/g, "");
  assert.ok(!/检查 pak 是否完整/.test(code), "条目里混着「文件找得到、只是清单没登记路径」那一类，替它们断言 pak 不完整就是猜");
});
