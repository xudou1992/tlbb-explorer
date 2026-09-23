#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
独立复核：用 Python 从 pak 里把同一张图解出来，和 Rust 侧报的特征对账。

存在的理由：墙上所有分组都建立在"Rust 解出来的像素是对的"这个前提上。
如果 Rust 侧的解码有偏移或通道错位，墙面会整片歪掉，而肉眼看缩略图不一定发现
（小图糊，错位一点看不出来）。所以这里用**完全独立的一条实现**重算一遍，
两条实现算出的平均色/尺寸对不上就报错。

这里复刻的是 jmt1/decoder.rs 的规则，但不 import 任何 Rust 产物：
- 24 字节头，'JMT1' magic，tag 在 4..8，marker 在 8..12
- u16 w@16, u16 h@18, u32 mips@20
- mip 表自 24 起，每级 [u32 size][data]
- codec 由 mip0 字节数对 block grid 判定（tag 会撒谎）
- RGBA32 是 BGRA 存储，要换位
"""

import os
import sys
import struct
import sqlite3


def load_index(root):
    """直接扫 pak 索引，不用 Rust 侧的 records 表。"""
    import hashlib
    idx = {}
    for name in sorted(os.listdir(root)):
        if not name.endswith(".pak"):
            continue
        stem = name[:-4]
        path = os.path.join(root, name)
        with open(path, "rb") as f:
            data = f.read(64)
            assert data[:4] == b"JPAK", name
            gen, used_end, crc = struct.unpack("<III", data[4:16])
            at = 16
            while True:
                f.seek(at)
                h = f.read(16)
                cap, used, nxt, acrc = struct.unpack("<IIII", h)
                f.seek(at + 16)
                recs = f.read(used * 36)
                for i in range(used):
                    b = recs[i * 36:(i + 1) * 36]
                    hh, off, stored, occupied, original = struct.unpack("<QIIII", b[:24])
                    ver, flags, method = struct.unpack("<HBB", b[24:28])
                    file_crc, rcrc = struct.unpack("<II", b[28:36])
                    idx[(stem, hh)] = dict(
                        path=path, offset=off, stored=stored, occupied=occupied,
                        original=original, flags=flags, method=method,
                        ver=ver, file_crc=file_crc)
                if nxt == 0:
                    break
                at = nxt
    return idx


def block_grid(w, h):
    return ((w + 3) // 4) * ((h + 3) // 4)


# ------------------------------------------------------------------ 引擎密码（独立复刻）

_CIPHER = None


def cipher_table(root):
    global _CIPHER
    if _CIPHER is None:
        p = os.path.join(root, "tlbb-explorer", "crates", "core", "assets", "cipher_table.bin")
        raw = open(p, "rb").read()
        _CIPHER = struct.unpack("<4096I", raw)
    return _CIPHER


def crypt(key, stored_len, buf, table):
    """复刻 jpak/crypto.rs::crypt —— 就地异或，自逆。

    关键：表下标由**记录的总 dword 数**驱动，所以即便只解头部也必须传完整 stored_len。
    crc32 用 zlib 语义（Python 的 zlib.crc32 就是这套，初值直接给）。
    """
    import zlib
    v = zlib.crc32(struct.pack("<I", stored_len),
                   zlib.crc32(struct.pack("<Q", key)) ^ 0x08088405) & 0xFFFFFFFF
    total_dw = stored_len // 4
    n_dw = len(buf) // 4
    out = bytearray(buf)
    for c in range(n_dw):
        idx = ((total_dw + v - c - 1) & 0xFFFFFFFF) & 0xFFF
        v = (table[idx] + 778904513) & 0xFFFFFFFF
        w = struct.unpack_from("<I", out, c * 4)[0]
        struct.pack_into("<I", out, c * 4, w ^ v)
    tail = stored_len % 4
    if tail > 0 and len(buf) == stored_len:
        x = table[tail] ^ v
        for k in range(len(buf) - n_dw * 4):
            out[n_dw * 4 + k] ^= (x >> (8 * k)) & 0xFF
    return bytes(out)


def snappy_decompress(src, expected):
    """最小 Snappy 解压（复刻 payload/snappy.rs 覆盖的 tag 类型）。"""
    out = bytearray()
    i = 0
    n = len(src)
    # Snappy 流前有 varint 表示解压后长度
    shift = 0
    ln = 0
    while True:
        b = src[i]
        i += 1
        ln |= (b & 0x7F) << shift
        if not (b & 0x80):
            break
        shift += 7
    while i < n:
        tag = src[i]
        i += 1
        t = tag & 3
        if t == 0:
            l = tag >> 2
            if l < 60:
                length = l + 1
            else:
                nb = l - 59
                length = int.from_bytes(src[i:i + nb], "little") + 1
                i += nb
            out += src[i:i + length]
            i += length
        else:
            if t == 1:
                length = 4 + ((tag >> 2) & 7)
                off = ((tag >> 5) << 8) | src[i]
                i += 1
            elif t == 2:
                length = (tag >> 2) + 1
                off = int.from_bytes(src[i:i + 2], "little")
                i += 2
            else:
                length = (tag >> 2) + 1
                off = int.from_bytes(src[i:i + 4], "little")
                i += 4
            start = len(out) - off
            for k in range(length):
                out.append(out[start + k])
    if expected and len(out) != expected:
        raise ValueError("snappy 长度不符 %d != %d" % (len(out), expected))
    return bytes(out)


def manifest_strip(buf):
    """剥掉 manifest 前缀。

    布局见 payload/manifest.rs：`[u8 path_len][path][u32 version][u64 FILETIME][u32 crc]`。
    CRC 在 `path_len + 12`，**不是 +13** —— 差一位是这里的经典 off-by-one。
    """
    if len(buf) < 1:
        return None
    path_len = buf[0]
    attrs = 1 + path_len
    if attrs + 16 > len(buf):
        return None
    return buf[attrs + 16:]


def decode_rgba32(mip0, w, h, tag, marker):
    """返回 (w, h, rgba) 或 None。"""
    px = w * h
    if tag == "COLW":
        return None                      # WebP 内嵌，不在这条复核路径里
    if tag == "COLR" and len(mip0) == (w + 2) * (h + 2) * 4:
        # 带 1 像素边框，裁掉
        stride = (w + 2) * 4
        out = bytearray(w * h * 4)
        for y in range(h):
            out[y * w * 4:(y + 1) * w * 4] = mip0[y * stride:y * stride + w * 4]
        b = out
    elif marker == 0x1909 or tag == "ALI8":
        if len(mip0) != px:
            return None
        b = bytearray()
        for v in mip0:
            b += bytes((v, v, v, 255))
    elif len(mip0) == px * 4:
        b = bytearray(mip0)
    else:
        return None
    # BGRA -> RGBA
    for i in range(0, len(b), 4):
        b[i], b[i + 2] = b[i + 2], b[i]
    return (w, h, bytes(b))


def _rgb565(v):
    r = v >> 11
    g = (v >> 5) & 0x3F
    b = v & 0x1F
    return ((r * 255 + 15) // 31, (g * 255 + 31) // 63, (b * 255 + 15) // 31)


def _mix(a, b, aw, bw, div):
    return tuple((aw * a[i] + bw * b[i]) // div for i in range(3))


def _alpha_table(a0, a1):
    t = [0] * 8
    t[0], t[1] = a0, a1
    if a0 > a1:
        for i in range(2, 8):
            t[i] = ((8 - i) * a0 + (i - 1) * a1) // 7
    else:
        for i in range(2, 6):
            t[i] = ((6 - i) * a0 + (i - 1) * a1) // 5
        t[6], t[7] = 0, 255
    return t


def decode_blocks(data, w, h, block):
    """BC1(8)/BC3(16)。独立复刻 jmt1/decoder.rs::decode_blocks。"""
    bw = (w + 3) // 4
    bh = (h + 3) // 4
    px = bytearray(w * h * 4)
    for by in range(bh):
        for bx in range(bw):
            off = (by * bw + bx) * block
            chunk = data[off:off + block]
            if len(chunk) < block:
                continue
            bc3 = block == 16
            c_at, ci_at = (8, 12) if bc3 else (0, 4)
            c0 = struct.unpack_from("<H", chunk, c_at)[0]
            c1 = struct.unpack_from("<H", chunk, c_at + 2)[0]
            a = _rgb565(c0)
            cc = _rgb565(c1)
            if bc3 or c0 > c1:
                pal = [a + (255,), cc + (255,),
                       _mix(a, cc, 2, 1, 3) + (255,), _mix(a, cc, 1, 2, 3) + (255,)]
            else:
                pal = [a + (255,), cc + (255,), _mix(a, cc, 1, 1, 2) + (255,), (0, 0, 0, 0)]
            ci = struct.unpack_from("<I", chunk, ci_at)[0]
            if bc3:
                tab = _alpha_table(chunk[0], chunk[1])
                ab = int.from_bytes(chunk[2:8] + b"\x00\x00", "little")
            else:
                tab, ab = None, 0
            for k in range(16):
                rr, gg, bb, aa = pal[(ci >> (2 * k)) & 3]
                if tab is not None:
                    aa = tab[(ab >> (3 * k)) & 7]
                x, y = bx * 4 + k % 4, by * 4 + k // 4
                if x < w and y < h:
                    o = (y * w + x) * 4
                    px[o:o + 4] = bytes((rr, gg, bb, aa))
    return bytes(px)


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else r"D:\TLGL"
    db = sys.argv[2] if len(sys.argv) > 2 else r"D:\TLGL\.scratch\resources.db"
    tsv = sys.argv[3] if len(sys.argv) > 3 else r"D:\TLGL\.scratch\wall3_smoke\raw.tsv"
    sample_n = int(sys.argv[4]) if len(sys.argv) > 4 else 60

    print("扫 pak 索引…")
    idx = load_index(root)
    print("  索引条数 %d" % len(idx))

    rows = []
    with open(tsv, encoding="utf-8") as f:
        head = f.readline().rstrip("\n").split("\t")
        c = {k: i for i, k in enumerate(head)}
        for line in f:
            p = line.rstrip("\n").split("\t")
            if p[c["decoded"]] == "1":
                rows.append(p)
    print("  待复核的行 %d（覆盖 RGBA32 / BC1 / BC3）" % len(rows))
    # 按编码分层抽样，保证 BC 与 RGBA 都被覆盖
    byk = {}
    for p in rows:
        byk.setdefault(p[c["catalog_codec"]], []).append(p)
    sel = []
    per = max(1, sample_n // max(1, len(byk)))
    for k, v in sorted(byk.items()):
        sel += v[:: max(1, len(v) // per)][:per]
    rows = sel[:sample_n] if len(sel) > sample_n else sel
    print("  抽样构成 %s" % {k: sum(1 for p in rows if p[c["catalog_codec"]] == k) for k in byk})

    bad = 0
    ok = 0
    skip = {"encrypt": 0, "snappy": 0, "webp": 0, "other": 0}
    table = cipher_table(root)
    for p in rows:
        h = p[c["hash"]]
        pak = p[c["pak"]]
        hh = int(h, 16)
        rec = idx.get((pak, hh))
        if rec is None:
            print("  [缺] %s 不在 %s 索引" % (h, pak))
            bad += 1
            continue
        with open(rec["path"], "rb") as f:
            f.seek(rec["offset"])
            stored = f.read(rec["stored"])
        buf = stored
        if rec["flags"] & 4:              # ENCRYPTED
            buf = crypt(hh, rec["stored"], buf, table)
        if rec["flags"] & 1:              # MANIFEST
            s = manifest_strip(buf)
            if s is None:
                skip["other"] += 1
                continue
            buf = s
        if rec["method"] == 0x33:         # Snappy
            try:
                buf = snappy_decompress(buf, rec["original"])
            except Exception as e:
                print("  [snappy失败] %s %s" % (h, e))
                bad += 1
                continue
        elif rec["method"] != 0:
            skip["other"] += 1
            continue
        if buf[:4] != b"JMT1":
            print("  [非JMT1] %s %r" % (h, buf[:8]))
            bad += 1
            continue
        w, hgt, mips = struct.unpack("<HHI", buf[16:24])
        tag = buf[4:8].decode("latin1")
        marker = struct.unpack("<I", buf[8:12])[0]
        sz = struct.unpack("<I", buf[24:28])[0]
        mip0 = buf[28:28 + sz]
        if tag == "COLW":
            skip["webp"] += 1
            continue
        got = decode_rgba32(mip0, w, hgt, tag, marker)
        if got is None:
            # 不是未压缩格式，试块压缩
            b0 = block_grid(w, hgt)
            if len(mip0) == b0 * 16:
                got = (w, hgt, decode_blocks(mip0, w, hgt, 16))
            elif len(mip0) == b0 * 8:
                got = (w, hgt, decode_blocks(mip0, w, hgt, 8))
        if got is None:
            skip["other"] += 1
            continue
        gw, gh, rgba = got
        mr = sum(rgba[0::4]) / len(rgba[0::4])
        mg = sum(rgba[1::4]) / len(rgba[1::4])
        mb = sum(rgba[2::4]) / len(rgba[2::4])
        ma = sum(rgba[3::4]) / len(rgba[3::4])

        rw = int(p[c["dec_w"]])
        rh = int(p[c["dec_h"]])
        rmr = float(p[c["mean_r"]])
        rmg = float(p[c["mean_g"]])
        rmb = float(p[c["mean_b"]])
        rma = float(p[c["mean_a"]])
        de = max(abs(mr - rmr), abs(mg - rmg), abs(mb - rmb), abs(ma - rma))
        dim_ok = (gw == rw and gh == rh)
        if not dim_ok or de > 0.02:
            bad += 1
            print("  [不符] %s 尺寸 %dx%d vs %dx%d  平均色差 %.4f  (Rust R%.1f G%.1f B%.1f A%.1f / Py R%.1f G%.1f B%.1f A%.1f)"
                  % (h, rw, rh, gw, gh, de, rmr, rmg, rmb, rma, mr, mg, mb, ma))
        else:
            ok += 1

    print()
    print("跳过（本复核不覆盖）：%s" % skip)
    print("复核结论：一致 %d，不符 %d" % (ok, bad))
    if bad:
        print("⇒ Rust 侧解码与独立实现不一致，墙面数据不可信，必须先修。")
        return 1
    if ok == 0:
        print("⇒ 样本全部被跳过，这次复核**没有证明任何东西**。")
        return 2
    print("⇒ Rust 侧解码与独立实现一致（尺寸 + 平均色，含解密与解压路径）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
