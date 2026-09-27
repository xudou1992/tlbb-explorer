# -*- coding: utf-8 -*-
"""64 位 pak 键公式全量验证（IDA 反汇结果，见 .scratch/ida_loadchain_20260926.md §1）

公式（反汇自 tlbbgl_x64.exe pak_dualhash_sdbm_in_HIGH 0x14059FA30）:
  每字节: 有符号 char; 'A'-'Z'→+32; '\\'→'/'
  high32 = sdbm32 : h=0;      h = c + 65599*h
  low32  = xorhash: h=0x4E67C6A7; h ^= c + (h<<5) + (h>>2)
  key = (high32<<32) | low32
"""
import sqlite3, time

M32 = 0xFFFFFFFF

def pak_hash_bytes(bs):
    lo = 0x4E67C6A7
    hi = 0
    for ch in bs:
        c = ch - 256 if ch >= 128 else ch          # 有符号 char
        if 65 <= ch <= 90:
            c = ch + 32                            # tolower
        elif ch == 92:
            c = 47                                 # '\' -> '/'
        lo = (lo ^ ((c + ((lo << 5) & M32) + (lo >> 2)) & M32)) & M32
        hi = (c + 65599 * hi) & M32
    return (hi << 32) | lo

def main():
    db = sqlite3.connect(r'D:/TLGL/.scratch/resources.db')
    cur = db.cursor()
    cur.execute("SELECT hash, path FROM resources WHERE named=1 AND path IS NOT NULL")
    rows = cur.fetchall()
    t0 = time.time()
    ok = 0
    bad = []
    for hs, p in rows:
        calc = pak_hash_bytes(p.encode('utf-8', errors='surrogateescape'))
        if calc == int(hs, 16):
            ok += 1
        elif len(bad) < 5:
            bad.append((p, hs, '%016x' % calc))
    print(f'named entries: {len(rows)}  full-64bit match: {ok}  ({time.time()-t0:.1f}s)')
    for b in bad:
        print('MISMATCH:', b)

if __name__ == '__main__':
    main()
