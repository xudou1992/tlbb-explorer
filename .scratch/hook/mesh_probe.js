'use strict';
// 运行时取证第一版：只观察、不预设字段含义。
// 用法：frida -p <PID> -l mesh_probe.js  （REPL 里可调 rpc.exports 的同名函数）
// 1) 记录客户端打开了哪些 .mesh、读了多少字节；2) 提供按字节模式在进程内存里找位置的工具，
//    用来把「我们静态看到的 r×16 + u92 那段」在客户端里的副本找出来；3) 提供 hexdump 与指针反查。
// 不写内存、不改指令，只挂读路径与暴露只读工具。

function exp(name) {
  try { return Module.getGlobalExportByName(name); } catch (e) {}
  try { return Module.getExportByName(null, name); } catch (e) {}
  return null;
}

const handles = new Map(); // HANDLE 数值 -> 路径
const meshReads = [];      // 最近的 .mesh 读取记录

const CreateFileW = exp('CreateFileW');
if (CreateFileW) {
  Interceptor.attach(CreateFileW, {
    onEnter(args) {
      try { this.path = args[0].readUtf16String(); } catch (e) { this.path = null; }
    },
    onLeave(ret) {
      const h = ret.toUInt32 ? ret : ret;
      const hv = h.toString();
      if (hv === '4294967295' || hv === '-1' || hv === '0xffffffffffffffff') return;
      if (this.path && /\.mesh$/i.test(this.path)) {
        handles.set(hv, this.path);
        console.log('[open] ' + this.path + '  handle=' + hv);
      }
    }
  });
  console.log('[hook] CreateFileW ok');
} else {
  console.log('[hook] CreateFileW NOT FOUND');
}

const ReadFile = exp('ReadFile');
if (ReadFile) {
  Interceptor.attach(ReadFile, {
    onEnter(args) {
      this.h = args[0].toString();
      this.buf = args[1];
      this.len = args[2].toInt32();
      this.mesh = handles.get(this.h) || null;
    },
    onLeave(ret) {
      if (!this.mesh) return;
      if (ret.toInt32() === 0) return; // 失败
      let n = this.len;
      try { n = this.len > 0 ? this.len : 0; } catch (e) {}
      const rec = { path: this.mesh, at: Date.now(), len: n, buf: this.buf.toString() };
      meshReads.push(rec);
      if (meshReads.length > 200) meshReads.shift();
      console.log('[read] ' + this.mesh + '  req=' + n + '  buf=' + this.buf);
    }
  });
  console.log('[hook] ReadFile ok');
} else {
  console.log('[hook] ReadFile NOT FOUND');
}

rpc.exports = {
  // 最近的 .mesh 读取（不 dump 内容，避免卡死客户端）
  meshes() {
    return meshReads;
  },
  // 在可读区里找一段字节（hex 字符串），返回命中地址（最多 maxHits 个）
  findBytes(hex, maxHits) {
    const pat = hex.replace(/\s+/g, '');
    const ranges = Process.enumerateRanges('r--').concat(Process.enumerateRanges('rw-'));
    const hits = [];
    const lim = maxHits || 8;
    for (const r of ranges) {
      if (hits.length >= lim) break;
      if (r.size > 512 * 1024 * 1024) continue; // 跳过超大区，避免扫爆
      try {
        const m = Memory.scanSync(r.base, r.size, pat);
        for (const x of m) {
          hits.push(x.address.toString());
          if (hits.length >= lim) break;
        }
      } catch (e) {}
    }
    return hits;
  },
  // 反查：哪些可读页里出现了指向 addr 的 8 字节指针
  refs(addrStr, maxHits) {
    const addr = ptr(addrStr);
    const ranges = Process.enumerateRanges('r--').concat(Process.enumerateRanges('rw-'));
    const hits = [];
    const lim = maxHits || 8;
    for (const r of ranges) {
      if (hits.length >= lim) break;
      if (r.size > 512 * 1024 * 1024) continue;
      try {
        const m = Memory.scanSync(r.base, r.size, addr.toMatchPattern());
        for (const x of m) {
          hits.push(x.address.toString());
          if (hits.length >= lim) break;
        }
      } catch (e) {}
    }
    return hits;
  },
  dump(addrStr, len) {
    return hexdump(ptr(addrStr), { length: len || 256, ansi: false });
  },
  modules(filter) {
    return Process.enumerateModules()
      .filter(m => !filter || new RegExp(filter, 'i').test(m.name))
      .map(m => ({ name: m.name, base: m.base.toString(), size: m.size }));
  }
};

console.log('[ready] 等待客户端读取 .mesh；可用 meshes()/findBytes()/refs()/dump()/modules()');
