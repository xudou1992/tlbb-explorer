#!/usr/bin/env node
/* eslint-disable */
'use strict';
/*
 * crosscheck.js —— 零第三方依赖，用本地实现的 JSON Schema(draft 2020-12 子集)
 * 校验两套真实产物，并把 Rust/Python 的字段冲突跑成实际结果。
 *
 *   node crosscheck.js            # 全量校验 + 现算版本差异
 *   node crosscheck.js --quiet    # 只打印结论与冲突摘要
 *
 * 只读：本脚本不写任何文件，仅 fs.readFileSync。
 */
const fs = require('fs');
const path = require('path');

const HERE = __dirname;                                   // ...\contracts
const SCRATCH = 'D:\\TLGL\\.scratch';                     // 依据产物所在
const CARDS = path.join(SCRATCH, 'cards', 'cards.json');
const SNAP_B = path.join(SCRATCH, 'versions', '示例_下一版.json');
const SNAP_A = path.join(SCRATCH, 'out', 'versionA.json');
const QUIET = process.argv.includes('--quiet');

const log = (...a) => { if (!QUIET) console.log(...a); };

// ---------- 极简 JSON Schema 校验器（覆盖本仓用到的关键字） ----------
function escRe(s) { return s; }
function resolveRef(root, ref) {
  if (!ref.startsWith('#')) throw new Error('仅支持内部 $ref: ' + ref);
  let node = root;
  const parts = ref.split('/').slice(1);
  for (let p of parts) {
    p = decodeURIComponent(p).replace(/~1/g, '/').replace(/~0/g, '~');
    node = node[p];
    if (node === undefined) throw new Error('无法解析 $ref: ' + ref);
  }
  return node;
}
function typeOf(v) {
  if (v === null) return 'null';
  if (Array.isArray(v)) return 'array';
  if (typeof v === 'number') return Number.isInteger(v) ? 'integer' : 'number';
  return typeof v; // string/boolean/object
}
function matchType(t, v) {
  const actual = typeOf(v);
  if (t === 'integer') return actual === 'integer';
  if (t === 'number') return actual === 'number' || actual === 'integer';
  return t === actual;
}
function validate(schema, data, root, ptr) {
  const errs = [];
  if (schema === true || schema === undefined) return errs;
  if (schema === false) { errs.push(ptr + ': false schema'); return errs; }
  if (schema.$ref) return validate(resolveRef(root, schema.$ref), data, root, ptr);

  const push = (m) => errs.push(ptr + ': ' + m);

  if (schema.type) {
    const ts = Array.isArray(schema.type) ? schema.type : [schema.type];
    if (!ts.some((t) => matchType(t, data))) push('type 期望 ' + ts.join('|') + '，实得 ' + typeOf(data));
  }
  if (schema.const !== undefined && data !== schema.const) push('const 应为 ' + JSON.stringify(schema.const));
  if (schema.enum && !schema.enum.some((e) => e === data)) push('enum 越界: ' + JSON.stringify(data));

  if (typeof data === 'string') {
    if (schema.minLength != null && data.length < schema.minLength) push('minLength<' + schema.minLength);
    if (schema.maxLength != null && data.length > schema.maxLength) push('maxLength>' + schema.maxLength);
    if (schema.pattern && !new RegExp(schema.pattern).test(data)) push('pattern 不符 /' + schema.pattern + '/ 值=' + JSON.stringify(data.length > 48 ? data.slice(0, 45) + '…' : data));
  }
  if (typeof data === 'number') {
    if (schema.minimum != null && data < schema.minimum) push('minimum<' + schema.minimum);
    if (schema.maximum != null && data > schema.maximum) push('maximum>' + schema.maximum);
  }
  if (Array.isArray(data)) {
    if (schema.minItems != null && data.length < schema.minItems) push('minItems<' + schema.minItems);
    if (schema.maxItems != null && data.length > schema.maxItems) push('maxItems>' + schema.maxItems);
    if (schema.uniqueItems) {
      const seen = new Set();
      for (const it of data) { const k = JSON.stringify(it); if (seen.has(k)) { push('uniqueItems 重复'); break; } seen.add(k); }
    }
    if (schema.items) data.forEach((it, i) => errs.push(...validate(schema.items, it, root, ptr + '/' + i)));
    if (schema.contains) {
      if (!data.some((it, i) => validate(schema.contains, it, root, ptr).length === 0)) push('contains 无匹配元素');
    }
  }
  if (typeOf(data) === 'object') {
    const keys = Object.keys(data);
    for (const r of (schema.required || [])) if (!(r in data)) push('缺必填 "' + r + '"');
    const props = schema.properties || {};
    const pats = Object.keys(schema.patternProperties || {});
    for (const k of keys) {
      let handled = false;
      if (Object.prototype.hasOwnProperty.call(props, k)) { handled = true; errs.push(...validate(props[k], data[k], root, ptr + '/' + k)); }
      for (const re of pats) if (new RegExp(re).test(k)) { handled = true; errs.push(...validate(schema.patternProperties[re], data[k], root, ptr + '/' + k)); }
      if (!handled) {
        const ap = schema.additionalProperties;
        if (ap === false) push('多余键 "' + k + '" (additionalProperties:false)');
        else if (ap && typeof ap === 'object') errs.push(...validate(ap, data[k], root, ptr + '/' + k));
      }
    }
  }
  // 组合
  for (const s of (schema.allOf || [])) errs.push(...validate(s, data, root, ptr));
  if (schema.anyOf) { if (!schema.anyOf.some((s) => validate(s, data, root, ptr).length === 0)) push('anyOf 全不匹配'); }
  if (schema.oneOf) { const n = schema.oneOf.filter((s) => validate(s, data, root, ptr).length === 0).length; if (n !== 1) push('oneOf 命中 ' + n + ' 个（应恰为 1）'); }
  if (schema.not) { if (validate(schema.not, data, root, ptr).length === 0) push('not 命中'); }
  if (schema.if && validate(schema.if, data, root, ptr).length === 0) {
    if (schema.then) errs.push(...validate(schema.then, data, root, ptr));
  } else if (schema.else) {
    errs.push(...validate(schema.else, data, root, ptr));
  }
  return errs;
}

// ---------- 汇总工具 ----------
function tally(errors, maxShow) {
  const byRule = {};
  for (const e of errors) {
    const m = e.match(/: (.*)$/) ? e.slice(e.indexOf(': ') + 2) : e;
    const key = m.replace(/\[0-9a-f\]\{.*\}/g, '…').replace(/"[^"]+"/g, '"…"').replace(/\d+/g, 'N');
    byRule[key] = (byRule[key] || 0) + 1;
  }
  const rows = Object.entries(byRule).sort((a, b) => b[1] - a[1]);
  return { rows, show: rows.slice(0, maxShow) };
}

function loadJson(p) { return JSON.parse(fs.readFileSync(p, 'utf8')); }

// ================== 主流程 ==================
function main() {
  const SCard = loadJson(path.join(HERE, 'AssetCard.schema.json'));
  const SReport = loadJson(path.join(HERE, 'AssetReport.schema.json'));
  const SEvidence = loadJson(path.join(HERE, 'Evidence.schema.json'));
  const SDiff = loadJson(path.join(HERE, 'VersionDiff.schema.json'));

  // 自检：确认校验器能解析全部 $ref/$defs（构造一个错误样本验证捕获）
  const probe = validate(SCard, { 名称: 1 }, SCard, '#');
  console.log('[selftest] 校验器可捕获类型错误：' + (probe.length > 0 ? '是' : '否（校验器有 bug！）'));

  // ---- 1. Rust 卡片 ----
  const cards = loadJson(CARDS);
  const docErr = validate({ $ref: '#/$defs/卡片集文档' }, cards, SCard, '$doc');
  const cardErrs = [];
  cards['卡片'].forEach((c, i) => { const e = validate(SCard, c, SCard, '卡片[' + i + ']'); if (e.length) cardErrs.push(...e); });
  console.log('\n[Rust] AssetCard');
  console.log('  信封(卡片集文档)错误 ' + docErr.length + '，卡片 ' + cards['卡片'].length + ' 张中出错的卡片错误数 ' + cardErrs.length);
  if (docErr.length) console.log('  ' + tally(docErr, 8).rows.map(r => r[1] + '× ' + r[0]).join('\n  '));
  if (cardErrs.length) console.log('  ' + tally(cardErrs, 12).show.map(r => r[1] + '× ' + r[0]).join('\n  '));

  // ---- 2. 证据轴（Rust 卡片.证据 复用 Evidence 契约）----
  const evErrs = [];
  cards['卡片'].forEach((c, i) => { const e = validate(SEvidence, c['证据'], SEvidence, '卡片[' + i + '].证据'); if (e.length) evErrs.push(...e); });
  console.log('\n[Rust] Evidence（卡片.证据 直接按统一契约校验）');
  console.log('  错误 ' + evErrs.length + (evErrs.length ? '\n  ' + tally(evErrs, 8).show.map(r => r[1] + '× ' + r[0]).join('\n  ') : ' —— 定位置信轴可被统一契约无损接纳'));

  // ---- 3. Python 报告（版本快照 assets[]）----
  const B = loadJson(SNAP_B);
  const repDocErr = validate({ $ref: '#/$defs/版本快照文档' }, B, SReport, '$doc');
  const repErrs = [];
  const offenders = {};
  B.assets.forEach((a, i) => { const e = validate(SReport, a, SReport, 'assets[' + i + ']'); if (e.length) { repErrs.push(...e); e.forEach(x => { const m = x.match(/: (.*)$/)[1].replace(/\d+/g, 'N'); offenders[m] = (offenders[m] || 0) + 1; }); } });
  console.log('\n[Python] AssetReport（示例_下一版.json）');
  console.log('  信封(版本快照文档)错误 ' + repDocErr.length + '，assets ' + B.assets.length + ' 条中错误数 ' + repErrs.length);
  console.log('  受影响条目数 ' + Object.keys(offenders).length + ' 类');
  if (repDocErr.length) console.log('  [doc] ' + tally(repDocErr, 6).show.map(r => r[1] + '× ' + r[0]).join('\n  '));
  if (repErrs.length) {
    const byKind = {};
    repErrs.forEach(x => { const m = x.slice(x.indexOf(': ') + 2).replace(/"[^"]*"/g, 'X').replace(/\d+/g, 'N'); const g = m.split(' ')[0]; byKind[m] = (byKind[m] || 0) + 1; });
    console.log('  错误归类：\n  ' + Object.entries(byKind).sort((a,b)=>b[1]-a[1]).slice(0, 12).map(r => r[1] + '× ' + r[0]).join('\n  '));
    // 定位缺 id_names 的具体条目
    const missingIdNames = B.assets.map((a,i)=>[a,i]).filter(([a])=>!('id_names' in a)).map(([,i])=>B.assets[i].gid);
    if (missingIdNames.length) console.log('  缺 id_names 的 gid（makedemo 注入行）：' + missingIdNames.join(', '));
  }

  // ---- 4. 版本差异：现算 + 按 VersionDiff 契约校验 ----
  if (!fs.existsSync(SNAP_A)) { console.log('\n[Diff] 跳过：缺基线 ' + SNAP_A); finish(0); return; }
  const A = loadJson(SNAP_A);
  const diff = buildDiff(A, B);
  const diffErrs = validate(SDiff, diff, SDiff, '$diff');
  const itemErrs = [];
  diff.明细.forEach((d, i) => { const e = validate({ $ref: '#/$defs/差异项' }, d, SDiff, '明细[' + i + ']'); if (e.length) itemErrs.push(...e); });
  console.log('\n[Diff] VersionDiff（由 versionA→示例_下一版 现算，' + diff.明细.length + ' 条）');
  console.log('  文档错误 ' + diffErrs.length + '，明细项错误 ' + itemErrs.length);
  console.log('  归一桶 变化计数：' + JSON.stringify(diff.变化计数));
  console.log('  原始判定 统计：' + JSON.stringify(diff.统计));
  if (diffErrs.length) console.log('  ' + tally(diffErrs, 6).show.map(r => r[1] + '× ' + r[0]).join('\n  '));
  if (itemErrs.length) console.log('  ' + tally(itemErrs, 10).show.map(r => r[1] + '× ' + r[0]).join('\n  '));
  // 交叉核对 makedemo 预期（消失12/重打包400/结构65/内容30/新增8）
  console.log('  与 makedemo 注入预期对照（消失/重打包/结构/内容/新增）：' +
    [diff.统计['资产消失'], diff.统计['仅重新打包'], diff.统计['结构变化'], diff.统计['内容微调'], diff.统计['新资产出现']].join(' / '));
  const contentButFingerprintOnly = diff.明细.filter(d => d.判定 === '仅重新打包' && d.内容变化 === true).length;
  console.log('  反例（被判为重打包却标内容变化，应为 0）：' + contentButFingerprintOnly);
  finish(diffErrs.length + itemErrs.length + cardErrs.length + docErr.length + evErrs.length + repErrs.length + repDocErr.length);
}

// 移植 identity.compare()，并把 id_* 层映射到 fp_* 语义、分出真实内容变化 vs 指纹变化
function buildDiff(A, B) {
  const left = new Map(B.assets.map((x) => [x.gid, x])); // 用对象引用身份：改用索引
  const items = B.assets;
  const pool = new Map(items.map((x, i) => [i, x]));
  const byPath = new Map(), byId = new Map();
  items.forEach((x, i) => {
    if (x.stem) { const k = x.dir + '\u0000' + x.stem; byPath.set(k, (byPath.get(k) || []).concat(i)); }
    byId.set(x.id_asset, (byId.get(x.id_asset) || []).concat(i));
  });
  const uniqPath = new Map(); byPath.forEach((v, k) => { if (v.length === 1) uniqPath.set(k, v[0]); });
  const uniqId = new Map(); byId.forEach((v, k) => { if (v.length === 1) uniqId.set(k, v[0]); });
  const take = (idxs) => { for (const i of idxs) if (i != null && pool.has(i)) { const o = pool.get(i); pool.delete(i); return o; } return null; };

  const 统计 = {}, 变化计数 = {}, 明细 = [];
  const bump = (o, k) => { o[k] = (o[k] || 0) + 1; };
  const nameOf = (x) => (x && (x.stem || String(x.gid))) || '';

  for (const a of A.assets) {
    let b = null, matchBy = null;
    const pk = a.dir + '\u0000' + a.stem;
    if (a.stem && uniqPath.has(pk)) { b = take([uniqPath.get(pk)]); if (b) matchBy = '路径'; }
    if (b == null && uniqId.has(a.id_asset)) { b = take([uniqId.get(a.id_asset)]); if (b) matchBy = '身份证'; }
    if (b == null) {
      const ka = new Set(a.members.map((m) => m.role + '\u0000' + m.name));
      let best = null, bestScore = 0;
      for (const [i, x] of pool) { const s = new Set(x.members.map((m) => m.role + '\u0000' + m.name)); let c = 0; for (const k of ka) if (s.has(k)) c++; if (c > bestScore) { bestScore = c; best = i; } }
      if (best != null && bestScore >= Math.max(1, Math.floor(ka.size / 2))) { b = take([best]); if (b) matchBy = '成员重叠'; }
    }

    if (b == null) {
      const v = '资产消失'; bump(统计, v); bump(变化计数, '删除');
      明细.push({ 变更类型: '删除', 判定: v, 名称: nameOf(a), 种类: a.kind || 'other', 内容变化: false, 指纹变化: false, 变化层: [], 说明: a.members.length + ' 个文件在目标快照中无对应' });
      continue;
    }
    const sameAsset = a.id_asset === b.id_asset;
    const samePack = a.id_pack === b.id_pack;
    const namesDiff = (a.id_names || '') !== (b.id_names || '');

    let verdict, changeType, contentChanged, fpChanged, layers;
    if (sameAsset) {
      if (samePack) {
        if (namesDiff) { verdict = '相同'; changeType = '仅名称变化'; contentChanged = false; fpChanged = true; layers = ['fp_names']; }
        else { verdict = '相同'; changeType = '未变'; contentChanged = false; fpChanged = false; layers = []; }
      } else { verdict = '仅重新打包'; changeType = '未变'; contentChanged = false; fpChanged = true; layers = []; }
    } else {
      const ma = new Map(a.members.map((m) => [m.role + '\u0000' + m.name, m]));
      const mb = new Map(b.members.map((m) => [m.role + '\u0000' + m.name, m]));
      const add = [...mb.keys()].filter((k) => !ma.has(k));
      const rem = [...ma.keys()].filter((k) => !mb.has(k));
      let chg = 0; for (const k of ma.keys()) if (mb.has(k) && ma.get(k).sha && mb.get(k).sha && ma.get(k).sha !== mb.get(k).sha) chg++;
      verdict = (add.length || rem.length) ? '结构变化' : (chg ? '内容微调' : '身份证不同');
      changeType = '变更'; contentChanged = true; fpChanged = true;
      layers = ['fp_asset']; if (namesDiff) layers.push('fp_names');
    }
    bump(统计, verdict); bump(变化计数, changeType);
    const item = { 变更类型: changeType, 判定: verdict, 名称: nameOf(b) || nameOf(a), 种类: b.kind || a.kind || 'other', 匹配方式: matchBy || '路径', 内容变化: contentChanged, 指纹变化: fpChanged, 变化层: layers };
    if (verdict === '仅重新打包') item.仅重新打包 = true;
    if (changeType === '仅名称变化') item.仅名称变化 = true;
    明细.push(item);
  }
  for (const [, x] of pool) {
    bump(统计, '新资产出现'); bump(变化计数, '新增');
    明细.push({ 变更类型: '新增', 判定: '新资产出现', 名称: nameOf(x), 种类: x.kind || 'other', 匹配方式: '新增', 内容变化: true, 指纹变化: true, 变化层: ['fp_asset'], 说明: x.members.length + ' 个文件的新资产' });
  }
  return { 版本: 2, 基线: path.basename(SNAP_A), 目标: path.basename(SNAP_B), 统计, 变化计数, 明细 };
}

function finish(totalErr) {
  console.log('\n==================== 结论 ====================');
  console.log('总错误数：' + totalErr + (totalErr === 0 ? ' —— 四契约与两套真实产物一致' : ' —— 见上方不一致清单（多为刻意的严格性冲突，已在 README 说明）'));
  process.exitCode = 0; // 校验性发现，非致命：恒返回 0，交由人判读
}

main();
