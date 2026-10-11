// 待命钩子：把「静态库里读不到」的两张运行期表一次 dump 出来。
// 目标（2026-10-10 IDA 侧钉住的）：
//   qword_1410B5C38 = 类型注册表桶数组，0x20000 桶 × 16B（[节点指针, lock]），
//                     节点里 +12 是名字长度、+16 是类型 id，名字指针在节点前部（偏移待认）。
//   qword_1410A7DD8 = 工厂对象，虚表 +48 槽 = create(type_id)；mdl 那一支传 55。
// 注册表是首次使用时才建的，所以必须等客户端跑到能显示一只怪之后再按 d。
// 每一次读都单独 try：读不到就记「读到什么」，绝不整批崩掉（失败留现场）。
'use strict';

const IMAGE_BASE_STATIC = 0x140000000; // idb 里的绝对地址按这个基址写
const REG_RVA = 0x1410B5C38 - IMAGE_BASE_STATIC;
const FACTORY_RVA = 0x1410A7DD8 - IMAGE_BASE_STATIC;
// 基址自检的锚：这条版权串在 exe 里只有一处（0x140ef2e90，五个装载函数都引用它）。
// 读出来对不上就说明 ASLR/重定位之外还有别的意外（比如 idb 基址不是 0x140000000），
// 那情况下所有 RVA 推导都不可信，先报出来别往下 dump。
const COPY_RVA = 0x140ef2e90 - IMAGE_BASE_STATIC;
const COPY_HEAD = "Copyright 2013-";
const BUCKETS = 0x20000;

let mod = null;
let base = null;
let createHooked = false;
const log = [];

function say(kind, obj) {
  const rec = Object.assign({ kind: kind }, obj || {});
  log.push(rec);
  send(rec);
}

function readable(p) {
  try { p.readByteArray(1); return true; } catch (e) { return false; }
}

function verifyBase() {
  try {
    const p = base.add(COPY_RVA);
    const got = p.readCString(COPY_HEAD.length + 8);
    return { at: p.toString(), got: got, match: got === COPY_HEAD };
  } catch (e) { return { err: e.message }; }
}

function arm() {
  mod = Process.findModuleByName('tlbbgl_x64.exe');
  if (!mod) return false;
  base = mod.base;
  const chk = verifyBase();
  say('armed', { base: base.toString(), size: mod.size, baseCheck: chk,
    rva_registry: '0x' + REG_RVA.toString(16), rva_factory: '0x' + FACTORY_RVA.toString(16) });
  return true;
}

// 节点：名字长度(+12) + 类型 id(+16) + 名字指针（0 还是 8，两种都试）
function parseNode(node) {
  const out = { node: node.toString(), ok: false };
  try {
    out.len = node.add(12).readU32();
    out.typeId = node.add(16).readU32();
  } catch (e) { out.err = '读 len/id 失败: ' + e.message; return out; }
  if (!(out.len > 0 && out.len < 64)) { out.err = '名字长度不像话: ' + out.len; return out; }
  for (const nameOff of [0, 8, 24, 32]) {
    try {
      const p = node.add(nameOff).readPointer();
      if (p.isNull() || !readable(p)) continue;
      const raw = p.readByteArray(out.len);
      if (!raw) continue;
      const bytes = new Uint8Array(raw);
      // 名字必须是可打印 ASCII（类型名如 mesh / mdl / tex / ani）
      let good = bytes.length > 0;
      for (let i = 0; i < bytes.length; i++) { const c = bytes[i]; if (c < 0x20 || c > 0x7e) { good = false; break; } }
      if (!good) continue;
      out.nameOff = nameOff;
      out.name = String.fromCharCode.apply(null, Array.from(bytes));
      out.ok = true;
      return out;
    } catch (e) { /* 下一个候选偏移 */ }
  }
  out.err = '名字指针四个候选偏移都不像';
  return out;
}

function dumpRegistry(limit) {
  const arr = base.add(REG_RVA).readPointer();
  const res = { arr: arr.toString(), nonEmpty: 0, parsed: 0, samples: [], offHits: {} };
  if (arr.isNull() || !readable(arr)) { res.err = '桶数组还没分配（表还没被首次使用建起来）'; return res; }
  for (let i = 0; i < BUCKETS; i++) {
    let node;
    try { node = arr.add(16 * i).readPointer(); } catch (e) { res.err = '第 ' + i + ' 桶读断: ' + e.message; break; }
    if (node.isNull()) continue;
    res.nonEmpty++;
    if (!readable(node)) { res.samples.push({ bucket: i, err: '节点不可读' }); continue; }
    const n = parseNode(node);
    if (n.ok) {
      res.parsed++;
      res.offHits[n.nameOff] = (res.offHits[n.nameOff] || 0) + 1;
      if (res.samples.length < (limit || 40)) res.samples.push({ bucket: i, name: n.name, typeId: n.typeId, nameOff: n.nameOff });
    } else if (res.samples.length < (limit || 40)) {
      res.samples.push({ bucket: i, err: n.err, len: n.len, typeId: n.typeId });
    }
  }
  return res;
}

function dumpFactory() {
  const res = {};
  try {
    const obj = base.add(FACTORY_RVA).readPointer();
    res.obj = obj.toString();
    if (obj.isNull() || !readable(obj)) { res.err = '工厂对象还没建（或基址对不上）'; return res; }
    const vt = obj.readPointer();
    res.vtable = vt.toString();
    res.slot48 = vt.add(48).readPointer().toString();
    res.slot40 = vt.add(40).readPointer().toString();
    res.slot56 = vt.add(56).readPointer().toString();
    res.slot64 = vt.add(64).readPointer().toString();
  } catch (e) { res.err = '读工厂失败: ' + e.message; }
  return res;
}

function hookCreate() {
  const f = dumpFactory();
  if (!f.slot48 || f.err) return { hooked: false, why: f.err || '没拿到 +48 槽' };
  if (createHooked) return { hooked: true, note: '已经挂过了' };
  try {
    Interceptor.attach(ptr(f.slot48), {
      onEnter: function (a) { try { this.id = a[1].toUInt32(); } catch (e) { this.id = null; } },
      onLeave: function (r) { try { say('create', { typeId: this.id, obj: r.toString(), looksReadable: !r.isNull() && readable(r) }); } catch (e) {} }
    });
    createHooked = true;
    return { hooked: true, at: f.slot48 };
  } catch (e) { return { hooked: false, why: e.message }; }
}

rpc.exports = {
  status: function () {
    return { armed: !!mod, base: base ? base.toString() : null,
      registryPtr: mod ? base.add(REG_RVA).readPointer().toString() : null,
      factoryPtr: mod ? base.add(FACTORY_RVA).readPointer().toString() : null,
      createHooked: createHooked };
  },
  dump: function (limit) {
    if (!mod && !arm()) return { err: '还没找到 tlbbgl_x64.exe 模块' };
    const chk = verifyBase();
    if (!chk.match) {
      return { err: '基址自检没过（版权串对不上），RVA 推导不可信，先不 dump：' + JSON.stringify(chk) };
    }
    return { baseCheck: chk, registry: dumpRegistry(limit || 40), factory: dumpFactory() };
  },
  // 只数非空桶，用来判断「表建起来了没有」，代价比整表 dump 小得多
  probe: function () {
    if (!mod && !arm()) return { err: '还没找到模块' };
    const arr = base.add(REG_RVA).readPointer();
    if (arr.isNull()) return { built: false, note: '桶数组还是空指针' };
    let n = 0;
    for (let i = 0; i < BUCKETS; i += 1) { try { if (!arr.add(16 * i).readPointer().isNull()) n++; } catch (e) { break; } }
    return { built: n > 0, nonEmpty: n };
  },
  hookCreate: hookCreate,
};

if (!arm()) {
  const t = setInterval(function () { if (arm()) { clearInterval(t); } }, 200);
}
