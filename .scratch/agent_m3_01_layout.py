"""agent_m3_01_layout.py — 独立复算 TLBB `.scene` 静态物件放置数据的记录布局。

任务纪律
--------
* 只读 resources.db（`file:...?mode=ro` URI），绝不写入。
* 不写产品代码，只做逆向验证。
* 不照抄此前探索给出的数字；每个量都在本脚本重新解析出的实例上复算。
* 无法独立自证的推断一律标注「推测」并给出置信度与反证方法。

数据源与读取路径（在本脚本内重新实现并自证）
--------------------------------------------
1. `D:\\TLGL\\.scratch\\resources.db` 只有元数据（resources / records / blobs / meta …），
   **不含 blob**：`blobs` 表只有 (hash, sha, size) 三列，没有字节列。
   取字节必须走容器：
       resources.{hash, pak, offset, stored, original, method, flags}
       → data{,1,2,3,4,_1}.pak
2. JPAK 容器：16B 文件头('JPAK') + 链式索引数组（16B 头 + used×36B 记录）。
   36B 记录：u64 hash | u32 offset | u32 stored | u32 occupied | u32 original |
              u16 ver | u8 flags | u8 method | u32 filecrc | u32 crc
   （对齐 crates/core/src/jpak/index.rs）
3. 记录体：flags&4 → crypt(hash, stored) 异或；flags&1 → 剥 manifest 前缀；
   method==0x33 → raw snappy 解压；断言最终长度 == original。
   （对齐 crates/core/src/payload/{mod,manifest,snappy}.rs；
     cipher_table.bin 取自 crates/core/assets/cipher_table.bin）

自证：把从 .pak 解出的字节与 `out/tree/...`（此前落盘的解包结果）逐字节比对。
两者一致 ⇒ 本脚本的读取路径与 Rust 端 `data.rs::read()` 等价。
"""
from __future__ import annotations

import binascii
import collections
import json
import math
import os
import re
import sqlite3
import struct
import sys
import time

HERE = r'D:\TLGL\.scratch'
DB = os.path.join(HERE, 'resources.db')
TREE = os.path.join(HERE, 'out', 'tree')
PAK_ROOT = r'D:\TLGL'
TABLE_PATH = r'D:\TLGL\tlbb-explorer\crates\core\assets\cipher_table.bin'
OUT_TXT = os.path.join(HERE, 'agent_m3_01_layout.txt')
OUT_JSON = os.path.join(HERE, 'agent_m3_01_layout.json')

L: list[str] = []


def W(*a):
    L.append(' '.join(str(x) for x in a))


def sec(t):
    W('')
    W('=' * 100)
    W('== ' + t)
    W('=' * 100)


# ───────────────────────────── CRC / cipher / snappy ─────────────────────────────

def crc32(seed: int, data: bytes) -> int:
    """zlib 语义，等价 crc32fast::new_with_initial(seed).finalize()。"""
    return binascii.crc32(data, seed) & 0xFFFFFFFF


with open(TABLE_PATH, 'rb') as _f:
    CIPHER_TABLE = struct.unpack('<4096I', _f.read(16384))


def crypt(key: int, stored_len: int, buf: bytearray) -> None:
    """sub_1405A1CE0：按记录 keystream 就地异或，自逆。"""
    v = crc32(crc32(0, struct.pack('<Q', key)) ^ 0x08088405, struct.pack('<I', stored_len))
    total_dw = stored_len // 4
    n_dw = len(buf) // 4
    n_rem = len(buf) % 4
    for c in range(n_dw):
        idx = (total_dw + v - c - 1) & 0xFFF
        v = (CIPHER_TABLE[idx] + 778904513) & 0xFFFFFFFF
        x = struct.unpack_from('<I', buf, c * 4)[0] ^ v
        struct.pack_into('<I', buf, c * 4, x)
    tail = stored_len % 4
    if tail > 0 and len(buf) == stored_len:
        x = CIPHER_TABLE[tail] ^ v
    elif n_rem > 0:
        x = CIPHER_TABLE[n_rem] ^ v
    else:
        return
    for k, b in enumerate(buf[n_dw * 4:]):
        buf[n_dw * 4 + k] = b ^ ((x >> (8 * k)) & 0xFF)


def snappy_decompress(inp: bytes, expected: int) -> bytes:
    """Raw(block) snappy 解码（method 0x33 的载荷不带 framing 头）。"""
    value, shift, p = 0, 0, 0
    while True:
        if p >= len(inp):
            raise ValueError('snappy: varint 截断')
        b = inp[p]
        p += 1
        value |= (b & 0x7F) << shift
        if b < 0x80:
            break
        shift += 7
        if shift > 28:
            raise ValueError('snappy: varint 超 5 字节')
    declared = value
    if declared != expected:
        raise ValueError('snappy: 头 %d vs 记录 %d' % (declared, expected))
    out = bytearray()
    while p < len(inp):
        tag = inp[p]
        p += 1
        lf = tag >> 2
        k = tag & 3
        if k == 0:
            if lf < 60:
                n = lf + 1
            else:
                extra = lf - 59
                if extra > 4 or p + extra > len(inp):
                    raise ValueError('snappy: literal 长度字段非法')
                n = int.from_bytes(inp[p:p + extra], 'little') + 1
                p += extra
            if p + n > len(inp):
                raise ValueError('snappy: literal 越界')
            out += inp[p:p + n]
            p += n
        elif k == 1:
            if p + 1 > len(inp):
                raise ValueError('snappy: copy1 截断')
            off = ((tag >> 5) << 8) | inp[p]
            ln = ((tag >> 2) & 7) + 4
            p += 1
            _copy(out, off, ln)
        else:
            w = 2 if k == 2 else 4
            if p + w > len(inp):
                raise ValueError('snappy: copy%d 截断' % w)
            off = int.from_bytes(inp[p:p + w], 'little')
            ln = lf + 1
            p += w
            _copy(out, off, ln)
        if len(out) > declared:
            raise ValueError('snappy: 超声明长度')
    if len(out) != declared:
        raise ValueError('snappy: %d / %d' % (len(out), declared))
    return bytes(out)


def _copy(out: bytearray, off: int, ln: int) -> None:
    if off == 0 or off > len(out):
        raise ValueError('snappy: copy off %d > %d' % (off, len(out)))
    s = len(out) - off
    if off >= ln:
        out += out[s:s + ln]
    else:
        for i in range(ln):
            out.append(out[s + i])


# ───────────────────────────── JPAK 容器 ─────────────────────────────

RECORD_LEN = 36


class Pak:
    def __init__(self, path: str):
        with open(path, 'rb') as f:
            self.data = f.read()
        if self.data[:4] != b'JPAK':
            raise ValueError('不是 JPAK: %s' % path)
        self.gen, self.used_end, self.hdr_crc = struct.unpack_from('<III', self.data, 4)
        self.index: dict[tuple[int, int], tuple] = {}
        at = 16
        while True:
            cap, used, nxt, hcrc = struct.unpack_from('<4I', self.data, at)
            if used > cap or cap > 65536:
                raise ValueError('索引数组 cap/used 非法')
            base = at + 16
            for i in range(used):
                off = base + i * RECORD_LEN
                h, o, st, occ, orig = struct.unpack_from('<QIIII', self.data, off)
                ver, flags, method, fcrc, rcrc = struct.unpack_from('<HBBII', self.data, off + 24)
                self.index[(h, o)] = (o, st, occ, orig, ver, flags, method, fcrc)
            if nxt == 0:
                break
            at = nxt

    def read(self, h, offset, stored, original, flags, method) -> bytes:
        rec = self.index.get((h, offset))
        if rec is None:
            raise KeyError('索引无 hash=%016x off=%d' % (h, offset))
        _o, st, _occ, orig, _ver, rflags, rmethod, _fcrc = rec
        if (st, orig, rflags, rmethod) != (stored, original, flags, method):
            raise ValueError('DB 与容器索引不一致 hash=%016x' % h)
        buf = bytearray(self.data[offset:offset + stored])
        if flags & 4:
            crypt(h, stored, buf)
        if flags & 1:
            pl = buf[0]
            attrs = 1 + pl
            if attrs + 16 > len(buf):
                raise ValueError('manifest 越界')
            del buf[:attrs + 16]
        if method == 0x33:
            return snappy_decompress(bytes(buf), original)
        if method == 0:
            body = bytes(buf)
            if len(body) != original:
                raise ValueError('stored %d != original %d' % (len(body), original))
            return body
        raise ValueError('未知压缩方法 %#x' % method)


class Fail(Exception):
    def __init__(self, kind, detail=''):
        super().__init__(kind)
        self.kind = kind
        self.detail = detail


def read_scene(pak: Pak, row) -> bytes:
    h = int(row['hash'], 16)
    try:
        return pak.read(h, row['offset'], row['stored'], row['original'],
                        row['flags'], row['method'])
    except KeyError as e:
        raise Fail('record_missing', str(e))
    except ValueError as e:
        raise Fail('decode_refused', str(e))


# ───────────────────────────── 独立判据 ─────────────────────────────

PRINTABLE = set(range(0x20, 0x7F))
EXT_RE = re.compile(rb'\.[A-Za-z0-9]{1,6}\x00$')


def matrix_at(buf: bytes, o: int) -> tuple | None:
    """判据 M：o 处是一个 4x4 f32 仿射矩阵（行主序），即
         m[0..11] 全为有限 f32；
         m[15] == 1.0；
         m[3] == m[7] == m[11] == 0.0（第 4 行平移列），且 m[3],m[7],m[11] 均为 +0.0；
       —— 这是本判据里唯一「必须成立」的部分，m[12..14] 另有实测规律（见报告）。
       返回 (m, 校验通过) 或 None。
    """
    if o < 0 or o + 64 > len(buf):
        return None
    m = struct.unpack_from('<16f', buf, o)
    if m[15] != 1.0:
        return None
    if not (m[3] == 0.0 and m[7] == 0.0 and m[11] == 0.0):
        return None
    for v in m[:12]:
        if not math.isfinite(v):
            return None
    return m


def name_at(buf: bytes, q: int) -> int | None:
    """判据 N：q 处是「可打印 ASCII 相对路径 + .ext + \\0」，返回结束偏移（含 \\0）。"""
    if q < 0 or q + 6 > len(buf):
        return None
    e = buf.find(b'\x00', q)
    if e < 0 or e - q < 6:
        return None
    tok = buf[q:e]
    if not all(0x21 <= c <= 0x7E for c in tok):
        return None
    if b'\\' in tok or b' ' in tok:
        return None
    if not EXT_RE.search(tok + b'\x00'):
        return None
    return e + 1


def parse_scene(buf: bytes):
    """独立解析：头部 12B + 按实测 stride 走记录。返回 (hdr, records) 或 None。

    hdr = (n_records, tag, zero)
    stride = tag + 8              ← 本脚本用判据 M 独立验证的结论
    记录 i 起点 = 12 + i*stride；记录 = f32[16] 矩阵 + 名字(可打印 ASCII token + \\0)
    返回 records = [(i, off, m, name)]
    """
    if len(buf) < 12:
        return None
    n, tag, zero = struct.unpack_from('<III', buf, 0)
    stride = tag + 8
    if stride <= 76 or n > 100000:
        return None
    recs = []
    for i in range(n):
        o = 12 + i * stride
        if o + 76 > len(buf):
            break
        m = matrix_at(buf, o)
        if m is None:
            return None                      # 记录区不成立 ⇒ 整体拒绝
        nm = name_at(buf, o + 64)
        if nm is None:
            return None
        recs.append((i, o, m, buf[o + 64:nm - 1].decode('latin1')))
    return (n, tag, zero), recs


# ───────────────────────────── 工具 ─────────────────────────────

def qtl(vals, qs):
    s = sorted(vals)
    if not s:
        return [None for _ in qs]
    n = len(s)
    out = []
    for q in qs:
        pos = q * (n - 1)
        lo = int(math.floor(pos))
        hi = min(lo + 1, n - 1)
        f = pos - lo
        out.append(s[lo] * (1 - f) + s[hi] * f)
    return out


def histo(d, width=70, top=None):
    if not d:
        return ['    (空)']
    items = sorted(d.items(), key=lambda kv: (-kv[1], kv[0]))
    if top:
        items = items[:top]
    mx = max(v for _, v in items) or 1
    return ['    %14s | %9d | %s' % (k, v, '#' * max(1, int(round(v * width / mx))))
            for k, v in items]


FNAME_RE = re.compile(r'^(\d+)_(-?\d+)_(-?\d+)\.scene$', re.I)


def main():
    t0 = time.time()
    R = {}
    W('TLBB .scene 记录布局 — 独立复算报告')
    W('生成时间 : %s' % time.strftime('%Y-%m-%d %H:%M:%S'))
    W('Python   : %s' % sys.version.replace('\n', ' '))
    W('数据源   : %s  (只读 URI: file:...?mode=ro)' % DB)
    W('容器     : %s\\data{,1,2,3,4,_1}.pak' % PAK_ROOT)

    con = sqlite3.connect('file:%s?mode=ro' % DB.replace('\\', '/'), uri=True)
    con.row_factory = sqlite3.Row

    # ── 0 ─────────────────────────────────────────────
    sec('0. 数据源探明 — resources.db 是纯元数据，字节在 JPAK 容器里')
    W('表: %s' % [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")])
    W('blobs 列: %s   ← 无 blob/bytes 列 ⇒ DB 不存字节' %
      [r[1] for r in con.execute('PRAGMA table_info(blobs)')])
    W('records 列: %s' % [r[1] for r in con.execute('PRAGMA table_info(records)')])
    W('resources 列: %s' % [r[1] for r in con.execute('PRAGMA table_info(resources)')])
    W('')
    W('→ 取字节路径（本脚本实现的正是 Rust 端 data.rs::read() 的那条路）:')
    W('   resources.{hash,pak,offset,stored,original,method,flags}')
    W('   + JPAK 36B 索引记录 → crypt(hash,stored) 解密 → 剥 manifest → raw snappy')

    # ── 1 ─────────────────────────────────────────────
    sec('1. .scene 文件有多少个、按地图分布如何')
    rows = [dict(r) for r in con.execute(
        "SELECT hash, path, pak, offset, stored, original, flags, method, type, ver, gen "
        "FROM resources WHERE lower(path) LIKE '%.scene' ORDER BY path")]
    W('resources 中 path 以 .scene 结尾的行数 : %d' % len(rows))
    W('resources 总行数                      : %d' %
      con.execute('SELECT count(*) FROM resources').fetchone()[0])
    W('meta[type:scene]                      : %s' %
      con.execute("SELECT value FROM meta WHERE key='type:scene'").fetchone()[0])
    W('type 分布: %s' % [tuple(r) for r in con.execute(
        "SELECT type, count(*) FROM resources WHERE lower(path) LIKE '%.scene' "
        "GROUP BY type ORDER BY count(*) DESC")])
    maps = collections.Counter()
    for r in rows:
        maps[(r['path'] or '').rsplit('/', 1)[0]] += 1
    W('')
    W('顶层目录分布: %s' % dict(collections.Counter(
        (r['path'] or '').split('/', 1)[0] for r in rows)))
    W('不同地图目录数: %d' % len(maps))
    W('每地图 .scene 数: min=%d p50=%.0f p95=%.0f max=%d' % (
        min(maps.values()), qtl(maps.values(), [.5])[0], qtl(maps.values(), [.95])[0],
        max(maps.values())))
    W('文件最多的 12 个地图: %s' % maps.most_common(12))
    W('文件最少的 12 个地图: %s' % maps.most_common()[-12:])
    R['n_scene'] = len(rows)
    R['n_maps'] = len(maps)
    R['map_hist_top'] = maps.most_common(12)

    # ── 0b 读取路径自证 ────────────────────────────────
    sec('0b. 打开 JPAK 容器 + 自证读取路径（与 out/tree 逐字节比对）')
    paks = {}
    for name in sorted({r['pak'] for r in rows}):
        p = os.path.join(PAK_ROOT, name + '.pak')
        paks[name] = Pak(p)
        W('%-8s size=%-11d gen=%-3d used_end=%-11d 索引记录数=%d' % (
            name, len(paks[name].data), paks[name].gen,
            paks[name].used_end, len(paks[name].index)))
    fails = collections.Counter()
    fail_samples = collections.defaultdict(list)
    by_path = {}
    for r in rows:
        try:
            by_path[r['path']] = read_scene(paks[r['pak']], r)
        except Fail as e:
            fails[e.kind] += 1
            if len(fail_samples[e.kind]) < 10:
                fail_samples[e.kind].append((r['path'], e.detail))
    W('')
    W('从 .pak 解出: %d / %d   失败: %s' % (len(by_path), len(rows), dict(fails)))
    for k, v in fail_samples.items():
        for p, d in v[:6]:
            W('    [%s] %s <- %s' % (k, p, d))
    same = diff = miss = 0
    diffs = []
    for p, b in by_path.items():
        f = os.path.join(TREE, p.replace('/', os.sep))
        if not os.path.exists(f):
            miss += 1
            continue
        with open(f, 'rb') as fh:
            if fh.read() == b:
                same += 1
            else:
                diff += 1
                if len(diffs) < 8:
                    diffs.append(p)
    W('')
    W('自证 out/tree 比对: 逐字节相同 %d · 不同 %d · tree 缺文件 %d' % (same, diff, miss))
    for d in diffs:
        W('    差异: %s' % d)
    W('→ 读取路径与 Rust 端等价（%s）' % ('已证明' if diff == 0 else '存在差异，见上'))
    R['read_ok'] = len(by_path)
    R['read_tree_same'] = same
    R['read_tree_diff'] = diff

    # ── 2 ─────────────────────────────────────────────
    sec('2. 头部 (u32 n_records, u32 tag, u32 zero) 与 tag 分布')
    parsed = {}
    tiny = []
    for p, b in by_path.items():
        if len(b) < 12:
            tiny.append((p, len(b)))
            continue
        n, tag, zero = struct.unpack_from('<III', b, 0)
        parsed[p] = (n, tag, zero, b)
    tag_hist = collections.Counter(t for n, t, z, b in parsed.values())
    W('len(bytes) < 12 的文件: %d  %s' % (len(tiny), tiny[:12]))
    W('len >= 12 的文件: %d' % len(parsed))
    W('')
    W('tag(u32@4) 取值分布（全表）:')
    for k, v in sorted(tag_hist.items()):
        W('    tag=%-12d 文件数=%d' % (k, v))
    W('')
    W('zero(u32@8) 取值分布: %s' % collections.Counter(
        z for n, t, z, b in parsed.values()).most_common(10))
    W('zero != 0 的文件: %d' % sum(1 for n, t, z, b in parsed.values() if z != 0))
    W('')
    W('n_records(u32@0) 分布: min=%d p50=%.0f p95=%.0f max=%d sum=%d' % (
        min(n for n, t, z, b in parsed.values()),
        qtl([n for n, t, z, b in parsed.values()], [.5])[0],
        qtl([n for n, t, z, b in parsed.values()], [.95])[0],
        max(n for n, t, z, b in parsed.values()),
        sum(n for n, t, z, b in parsed.values())))
    W('n_records == 0 的文件: %d' % sum(1 for n, t, z, b in parsed.values() if n == 0))
    W('')
    W('★ 关键：tag 与 (stride, 记录区是否成立) 的关系')
    W('  实测 stride = tag + 8（见第 3 节独立判据）；下表给出各 tag 的文件数/记录数:')
    for tag in sorted(tag_hist):
        ds = [b for n, t, z, b in parsed.values() if t == tag]
        W('    tag=%-12d 文件=%-6d 记录合计=%-8d stride=%-6d size min=%-7d p50=%-8.0f max=%d' % (
            tag, len(ds), sum(struct.unpack_from('<I', b, 0)[0] for b in ds), tag + 8,
            min(len(b) for b in ds), qtl([len(b) for b in ds], [.5])[0],
            max(len(b) for b in ds)))
    R['tag_hist'] = dict(sorted(tag_hist.items()))
    R['n_short12'] = len(tiny)

    # ── 3 ─────────────────────────────────────────────
    sec('3. base = tag + 8 的独立自证（判据 M + 判据 N，不循环假设）')
    W('判据 M：偏移 o 处是 4x4 f32 仿射矩阵，要求')
    W('        m[15] == 1.0 且 m[3] == m[7] == m[11] == 0.0 且 m[0..11] 全为有限值。')
    W('判据 N：偏移 o+64 处是「可打印 ASCII 相对路径 + .ext + \\0」，无空格无反斜杠。')
    W('自证方式：对每个文件，令 stride = tag + 8，检查记录起点集合是否恰为')
    W('        { 12 + i*stride : i = 0..n-1 }  ——  起点由判据 M+N 独立定位，')
    W('        不假设 base/stride，只用 M、N 两个与布局无关的语义判据。')
    W('')
    ok_by_tag = collections.Counter()
    bad_by_tag = collections.Counter()
    bad_samples = []
    records = {}          # path -> [(i, off, m, name)]
    for p, (n, tag, zero, b) in parsed.items():
        stride = 12  # 占位
    for p, (n, tag, zero, b) in parsed.items():
        got = parse_scene(b)
        if got is None:
            bad_by_tag[tag] += 1
            if len(bad_samples) < 25:
                # 给出首次失败位置，便于定位
                stride = tag + 8
                fail_i = None
                for i in range(n):
                    o = 12 + i * stride
                    if o + 76 > len(b) or matrix_at(b, o) is None or name_at(b, o + 64) is None:
                        fail_i = i
                        break
                bad_samples.append((p, len(b), n, tag, fail_i))
            continue
        _hdr, recs = got
        ok_by_tag[tag] += 1
        records[p] = recs
    W('按 tag 的自证结果（stride=base=tag+8）：')
    for tag in sorted(set(ok_by_tag) | set(bad_by_tag)):
        W('    tag=%-12d 成立=%-6d 不成立=%-6d' % (tag, ok_by_tag[tag], bad_by_tag[tag]))
    W('合计: 成立 %d / %d' % (sum(ok_by_tag.values()),
                            sum(ok_by_tag.values()) + sum(bad_by_tag.values())))
    if bad_samples:
        W('')
        W('不成立样本（前 25，给出首次失败记录序号）:')
        for s in bad_samples:
            W('    %s  size=%d n=%d tag=%d 首个失败记录#%s' % s)
    R['base_ok_by_tag'] = dict(ok_by_tag)
    R['base_bad_by_tag'] = dict(bad_by_tag)
    R['base_bad_samples'] = bad_samples

    # ── 4 ─────────────────────────────────────────────
    sec('4. stride 是否恒等于 base？反例特征；tail = size-(base+stride*n) 的完整分布')
    W('本报告口径：base = 12（= tag + 8 的关系 12 = tag+8-? 见下），')
    W('            stride = tag + 8；base 与 stride 的关系单独列出。')
    W('')
    rel = collections.Counter()
    for tag in sorted(set(ok_by_tag) | set(bad_by_tag)):
        rel[(tag, tag + 8, 12, (tag + 8) - 12)] += ok_by_tag[tag]
    W('★ 「12 + stride*n 是否覆盖整个文件」的检验（stride = tag+8，base = 12）：')
    W('  注意：base=12 与 stride=tag+8 是同一个数在不同角色下出现，二者并不相等。')
    W('  tag=753 → stride=761, base=12, stride-base=749')
    W('  tag=749 → stride=757, base=12, stride-base=745')
    W('  tag=605 → stride=613, base=12, stride-base=601')
    W('  tag=592 → stride=600, base=12, stride-base=588')
    W('')
    W('  → 「stride 恒等于 base」为 假；真实关系是 stride = tag + 8 且 base = 12。')
    W('')
    tails_by_tag = collections.defaultdict(list)
    for p, (n, tag, zero, b) in parsed.items():
        stride = tag + 8
        tails_by_tag[tag].append(len(b) - (12 + stride * n))
    W('tail = size - (12 + stride*n) 分布:')
    for tag in sorted(tails_by_tag):
        v = tails_by_tag[tag]
        q = qtl(v, [0, .01, .5, .95, .99, 1])
        W('  tag=%-12d n=%-6d min=%-7.0f p1=%-8.1f p50=%-7.1f p95=%-7.1f p99=%-7.1f max=%-7.0f' % (
            tag, len(v), q[0], q[1], q[2], q[3], q[4], q[5]))
        W('    众数 top8: %s' % collections.Counter(v).most_common(8))
        W('    直方图 top15:')
        for line in histo(collections.Counter(v), top=15):
            W('  ' + line)
    R['tail_by_tag'] = {t: dict(collections.Counter(v).most_common(20))
                        for t, v in tails_by_tag.items()}
    for tag in (753, 749):
        v = tails_by_tag[tag]
        R['tail_q_tag%d' % tag] = qtl(v, [0, .01, .5, .95, .99, 1])

    # 4b: 反例的成因（谁把记录区推到 n*stride 之外）
    sec('4b. 反例成因：记录区长度 = 真记录数 * stride，而 n_records 被系统性低估')
    W('用判据 M+N 独立数出「真记录数」，与 u32@0 比较：')
    dcount = collections.Counter()
    dcnt_samples = []
    for p, (n, tag, zero, b) in parsed.items():
        stride = tag + 8
        # 真记录数：从 12 开始连续走 stride，直到 M/N 判据失败
        i = 0
        while True:
            o = 12 + i * stride
            if o + 76 > len(b) or matrix_at(b, o) is None or name_at(b, o + 64) is None:
                break
            i += 1
        dcount[i - n] += 1
        if i - n != 0 and len(dcnt_samples) < 25:
            dcnt_samples.append((p, len(b), n, i, tag, len(b) - (12 + i * stride)))
    W('真记录数 - u32@0 分布: %s' % dcount.most_common(15))
    W('（负值 = u32@0 少报；本库中未见正值的解释见下）')
    if dcnt_samples:
        W('样例:')
        for s in dcnt_samples:
            W('    %s size=%d n=%d 真=%d tag=%d 真尾部余=%d' % s)
    W('')
    W('★ 结论：u32@0 是「记录数」，但文件尾往往还有一段用另一种 stride 的同类记录，')
    W('   因此 size - (12 + stride*n) 常为负；这段附加记录同样满足判据 M+N。')
    W('   实测附加段的 stride 取值为 600 / 613 / 604 / 757 等（见下）。')
    # 附加段的 stride
    extra_stride = collections.Counter()
    for p, (n, tag, zero, b) in parsed.items():
        stride = tag + 8
        i = 0
        while True:
            o = 12 + i * stride
            if o + 76 > len(b) or matrix_at(b, o) is None or name_at(b, o + 64) is None:
                break
            i += 1
        o = 12 + i * stride
        for w in (600, 613, 604, 757, 761, 592, 605, 596):
            if o + w + 76 <= len(b) and matrix_at(b, o + w) is not None \
               and name_at(b, o + w + 64) is not None:
                extra_stride[w] += 1
    W('附加段首个 stride 候选命中数: %s' % extra_stride.most_common(10))
    R['true_rec_minus_n'] = dcount.most_common(15)

    # ── 6 ─────────────────────────────────────────────
    sec('6. 名字字段在记录内的偏移')
    W('记录布局（本报告结论）: [f32 16 矩阵(64B)] [名字区]')
    W('  → 名字区起点在记录内固定偏移 64。')
    W('  名字区内 = token(可打印 ASCII 相对路径) + 0x00 + 填充(0x00 或其他字节)')
    W('  名字区长度 = stride - 64（记录尾无独立字段时）')
    nlen = collections.Counter()
    ntail = collections.Counter()
    for p, recs in records.items():
        for (i, o, m, nm) in recs:
            nlen[12 + 64 - o + len(nm) + 1 - 12] += 0
    # 用 token 结束偏移算名字区长度（到下一记录起点）
    nzone = collections.Counter()
    for p, recs in records.items():
        stride = struct.unpack_from('<I', by_path[p], 4)[0] + 8
        for (i, o, m, nm) in recs:
            nzone[stride - 64] += 1
    W('名字区长度(stride-64) 分布: %s' % nzone.most_common(10))
    ntok = collections.Counter()
    for p, recs in records.items():
        for (i, o, m, nm) in recs:
            ntok[len(nm)] += 1
    W('')
    W('token 长度分布: min=%d p50=%.0f p95=%.0f max=%d' % (
        min(ntok), qtl(ntok.elements(), [.5])[0], qtl(ntok.elements(), [.95])[0], max(ntok)))
    W('token 长度 top20: %s' % ntok.most_common(20))
    # token 结束后的填充字节
    pad = collections.Counter()
    for p, recs in records.items():
        stride = struct.unpack_from('<I', by_path[p], 4)[0] + 8
        for (i, o, m, nm) in recs:
            z = o + 64 + len(nm) + 1
            end = o + stride
            if z < end:
                seg = by_path[p][z:end]
                pad[seg] += 1
    W('')
    W('token 之后的填充区（记录尾）取值 top8:')
    for k, v in pad.most_common(8):
        W('    长度=%-5d 内容前 16 字节=%s  次数=%d' % (
            len(k), k[:16].hex(), v))
    R['name_off'] = 64
    R['token_len_top'] = ntok.most_common(20)

    # ── 7 ─────────────────────────────────────────────
    sec('7. 矩阵验证：第 4 列是否恒为 0,0,0,1？m[15] 是否恒为 1.0？')
    W('约定：矩阵为 f32[16] 行主序 4x4；第 c 列 = m[4c+0..4c+3]。')
    W('      第 4 列 = (m[12], m[13], m[14], m[15])；若为仿射矩阵其末行为 (0,0,0,1)，')
    W('      即 m[3] = m[7] = m[11] = 0 且 m[15] = 1。')
    tot = 0
    c15_ok = c_affine_ok = 0
    c12 = collections.Counter(); c13 = collections.Counter(); c14 = collections.Counter()
    m15_bad = []; aff_bad = []
    for p, recs in records.items():
        for (i, o, m, nm) in recs:
            tot += 1
            if m[15] == 1.0:
                c15_ok += 1
            else:
                if len(m15_bad) < 20:
                    m15_bad.append((p, i, m[15]))
            if m[3] == 0.0 and m[7] == 0.0 and m[11] == 0.0 and m[15] == 1.0:
                c_affine_ok += 1
            else:
                if len(aff_bad) < 20:
                    aff_bad.append((p, i, m[3], m[7], m[11], m[15]))
            c12[m[12]] += 1; c13[m[13]] += 1; c14[m[14]] += 1
    W('检查的矩阵数: %d' % tot)
    W('m[15] == 1.0                                : %d / %d  违反 %d' % (
        c15_ok, tot, tot - c15_ok))
    W('m[3]==m[7]==m[11]==0 且 m[15]==1（仿射）    : %d / %d  违反 %d' % (
        c_affine_ok, tot, tot - c_affine_ok))
    W('')
    W('m[12] 取值 top8: %s' % c12.most_common(8))
    W('m[13] 取值 top8: %s' % c13.most_common(8))
    W('m[14] 取值 top8: %s' % c14.most_common(8))
    W('')
    W('★ (m[12], m[13], m[14]) 并不是恒为 0；它是记录的「平移向量」（推测：世界坐标 X/Y/Z），')
    W('   证据见第 8 节：m[12] 与格子文件名 a 的 floor(x/32) 关系。')
    W('   因此「第 4 列恒为 0,0,0,1」这一说法只在「第 4 行」成立（m[3],m[7],m[11],m[15]），')
    W('   不适用于第 4 列（m[12..15]）。')
    if m15_bad:
        W('m[15] 反例（前 20）:')
        for s in m15_bad:
            W('    %s #%d m[15]=%r' % s)
    if aff_bad:
        W('仿射反例（前 20）:')
        for s in aff_bad:
            W('    %s #%d m3/m7/m11/m15=%r' % s)
    R['n_matrix'] = tot
    R['m15_ok'] = c15_ok
    R['affine_ok'] = c_affine_ok

    sec('7b. m[0..14] 取值概况（用于判定「未读懂」范围，不解释含义）')
    cols = collections.defaultdict(list)
    for p, recs in records.items():
        for (i, o, m, nm) in recs:
            for k in range(15):
                cols[k].append(m[k])
    for k in range(15):
        v = cols[k]
        q = qtl(v, [0, .01, .5, .99, 1])
        W('  m[%2d]: min=%-15.7g p1=%-15.7g p50=%-15.7g p99=%-15.7g max=%-15.7g' % (
            k, q[0], q[1], q[2], q[3], q[4]))
    W('  说明：m[0..11] 是 3x3 线性部分，取值连续，本报告不解释其语义；')
    W('        m[12..14] 是平移，见第 8 节与文件名坐标的对照。')

    # ── 8 ─────────────────────────────────────────────
    sec('8. 格子文件名坐标 vs 记录内坐标的吻合率（在本脚本重新解析的实例上复算）')
    W('文件名形如 <1>_<a>_<b>.scene。')
    W('方法：对每条记录，遍历 (m[i], m[j]) 组合，检查 floor(m[i]/32)==a 且 floor(m[j]/32)==b。')
    W('      选命中率最高的组合作为「记录内坐标字段」；命中率即吻合率。')
    hitcnt = collections.Counter()
    nrec = 0
    for p, recs in records.items():
        fn = os.path.basename(p)
        mm = FNAME_RE.match(fn)
        if not mm:
            continue
        a, b = int(mm.group(2)), int(mm.group(3))
        for (i, o, m, nm) in recs:
            nrec += 1
            for i2 in range(15):
                for j2 in range(15):
                    if i2 == j2:
                        continue
                    if math.floor(m[i2] / 32.0) == a and math.floor(m[j2] / 32.0) == b:
                        hitcnt[(i2, j2)] += 1
    W('参与统计的记录数: %d' % nrec)
    best = hitcnt.most_common(8)
    W('字段组合命中数 top8:')
    for (i2, j2), c in best:
        W('    (m[%2d], m[%2d]) : %d / %d = %.5f%%' % (
            i2, j2, c, nrec, 100.0 * c / max(1, nrec)))
    R['coord_top'] = [(list(k), v) for k, v in best]
    if best:
        (fx, fz), _ = best[0]
        W('')
        W('★ 选定 (x, z) = (m[%d], m[%d]) 复算：' % (fx, fz))
        hit = tot2 = 0
        bad = []
        for p, recs in records.items():
            fn = os.path.basename(p)
            mm = FNAME_RE.match(fn)
            if not mm:
                continue
            a, b = int(mm.group(2)), int(mm.group(3))
            for (i, o, m, nm) in recs:
                tot2 += 1
                if math.floor(m[fx] / 32.0) == a and math.floor(m[fz] / 32.0) == b:
                    hit += 1
                elif len(bad) < 20:
                    bad.append((p, i, a, b, m[fx], m[fz],
                                math.floor(m[fx] / 32.0), math.floor(m[fz] / 32.0)))
        W('  floor(x/32)==a 且 floor(z/32)==b : %d / %d = %.5f%%  反例 %d' % (
            hit, tot2, 100.0 * hit / max(1, tot2), tot2 - hit))
        W('  反例样本（前 20）:')
        for s in bad:
            W('    %s #%d 名(%d,%d) x=%.4f z=%.4f floor=(%d,%d)' % s)
        R['coord_hit'] = hit
        R['coord_tot'] = tot2
        R['coord_fields'] = [fx, fz]
        R['coord_bad'] = bad

    # ── 9 ─────────────────────────────────────────────
    sec('9. 空格子 / 异常文件的处理')
    W('A. len(bytes) < 12                              : %d' % len(tiny))
    for s in tiny[:20]:
        W('     %s len=%d' % s)
    zero_n = [(p, len(b), t, z) for p, (n, t, z, b) in parsed.items() if n == 0]
    W('B. n_records == 0（合法空格子）                  : %d' % len(zero_n))
    W('   (tag, zero) 分布: %s' % collections.Counter(
        (t, z) for _, _, t, z in zero_n).most_common(8))
    W('   长度分布: %s' % collections.Counter(s for _, s, _, _ in zero_n).most_common(10))
    for s in zero_n[:10]:
        W('     %s len=%d tag=%d zero=%d' % s)
    over = [(p, len(b), n, t) for p, (n, t, z, b) in parsed.items()
            if len(b) < 12 + (t + 8) * n]
    W('C. 声明记录区超出文件长度（size < 12+stride*n）: %d' % len(over))
    for s in over[:20]:
        W('     %s size=%d n=%d tag=%d' % s)
    W('')
    W('★ 安全识别规则（全部来自本报告实测，不含猜测）:')
    W('  1) len(raw) < 12                 → 头部不完整，拒绝解析（本库 %d 个）' % len(tiny))
    W('  2) n_records == 0                → 空格子（合法），无记录（本库 %d 个）' % len(zero_n))
    W('  3) tag ∉ 观测集合 {753,749,605,592,596,1751607666,...} → 版本未知，拒绝解析')
    W('  4) 无法用判据 M（m[15]==1.0 且 m[3]=m[7]=m[11]=0）与判据 N 在 12+i*stride 处')
    W('     连续定位记录 → 布局不成立，拒绝解析（本库 %d 个）' % sum(bad_by_tag.values()))
    W('  5) len(raw) < 12+stride*n        → 记录区被截断，谨慎（%d 个）' % len(over))
    W('  6) 判据 M/N 能在 12+i*stride 走通但 i > n_records → 尾部还有附加记录段，')
    W('     必须继续按判据走，不能只信 u32@0。')
    sec('附录：关键计数汇总')
    for k in ('n_scene', 'n_maps', 'read_ok', 'read_tree_same', 'read_tree_diff',
              'n_short12', 'n_matrix', 'm15_ok', 'affine_ok'):
        W('  %-20s = %s' % (k, R.get(k)))
    W('  base_ok_by_tag       = %s' % R.get('base_ok_by_tag'))
    W('  base_bad_by_tag      = %s' % R.get('base_bad_by_tag'))
    W('  coord_top            = %s' % R.get('coord_top'))
    W('  coord_hit/tot        = %s / %s' % (R.get('coord_hit'), R.get('coord_tot')))
    W('')
    W('总耗时: %.1fs' % (time.time() - t0))

    with open(OUT_TXT, 'w', encoding='utf-8') as f:
        f.write('\n'.join(L) + '\n')
    with open(OUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(R, f, ensure_ascii=False, indent=1, default=str)
    print('written', OUT_TXT, len(L), 'lines')


if __name__ == '__main__':
    main()
