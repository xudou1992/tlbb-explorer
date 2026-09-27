# -*- coding: utf-8 -*-
"""version_dx11.collect.pcfg 解析器（PackageConfigFileReader 0x1405A3B30 的忠实复刻）

格式（见 .scratch/ida_loadchain_20260926.md §3）:
  [u32 N][u16 outer]
  分组计数区: 每层 [u16 标记] + 计数(u16, 0xFFFF→u32)，计数只在「上次计数>1」时写出
  池 ×N:     [u64 ID][u32 偏移][u16 ver][u8 卷号]   (collect 模式读取器按 u64+跳7 消费)
  链接对区:  [u32 frm][计数][计数 × u32 to]          (同样的省略旗标)
  尾部:      打包工具残留的清单段（运行时不读）
"""
import struct, sqlite3, sys

class R:
    def __init__(self, d, o=0):
        self.d = d; self.o = o
    def read(self, n):
        v = self.d[self.o:self.o+n]
        if len(v) < n:
            raise EOFError(f'off={self.o}')
        self.o += n
        return v
    def u16(self):
        return struct.unpack('<H', self.read(2))[0]
    def u32(self):
        return struct.unpack('<I', self.read(4))[0]
    def u64(self):
        return struct.unpack('<Q', self.read(8))[0]
    def ucount(self):
        c = self.u16()
        return self.u32() if c == 0xFFFF else c

def parse(path):
    data = open(path, 'rb').read()
    r = R(data)
    N = r.u32()
    outer = r.u16()
    pool = []                       # (ID, file_offset, meta7)
    r13 = True                      # mid 层旗标（全局）
    for _ in range(outer):
        r.u16()                     # 标记
        mid_count = r.ucount() if r13 else 1
        if r13:
            r13 = mid_count > 1
        r12 = True                  # inner 层旗标（每个 outer 组重置）
        for _ in range(mid_count):
            r.u16()
            inner_count = r.ucount() if r12 else 1
            if r12:
                r12 = inner_count > 1
            sil = True              # run 层旗标（每个 mid 组重置）
            for _ in range(inner_count):
                r.u32()             # 标记
                run_count = r.ucount() if sil else 1
                if sil:
                    sil = run_count > 1
                for _ in range(run_count):
                    off = r.o
                    v = r.u64()
                    meta = r.read(7)
                    pool.append((v, off, meta))
    pc = r.ucount()
    pairs = []
    dil = True
    u32idx = N > 0xFFFF
    for _ in range(pc):
        frm = r.u32() if u32idx else r.u16()
        cnt = r.ucount() if dil else 1
        if dil:
            dil = cnt > 1
        for _ in range(cnt):
            to = r.u32() if u32idx else r.u16()
            pairs.append((frm, to))
    return N, pool, pairs, r.o, len(data)

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else \
        r'D:/TLGL/.scratch/out/named/data__version_dx11.collect.pcfg'
    N, pool, pairs, end, size = parse(path)
    print(f'N={N} pool={len(pool)} pairs={len(pairs)} consumed={end}/{size}')
    db = sqlite3.connect(r'D:/TLGL/.scratch/resources.db')
    cur = db.cursor()
    keyinfo = {}
    for hs, p, named in cur.execute('SELECT hash, path, named FROM resources'):
        keyinfo[int(hs, 16)] = (p, named)
    named = anon = out = 0
    for v, _, _ in pool:
        info = keyinfo.get(v)
        if info is None:
            out += 1
        elif info[1]:
            named += 1
        else:
            anon += 1
    print(f'pool: named={named} anon={anon} outside={out}')

if __name__ == '__main__':
    main()
