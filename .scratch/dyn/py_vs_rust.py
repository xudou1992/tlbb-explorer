# 双实现剩下的差集到底差在哪：把 python 认到、Rust 没认到的那些「带表记录」找出来，
# 报它们的**字节偏移 mod 4** 与名字。为什么要看 mod 4：Rust `parse_nodes` 只扫 0 和 2 两个相位
# （10-12 补的 2 相位），而 python 是按**名字串**锚定的，任何对齐都能认到。
# 如果差集全落在 1/3 相位，那就是 Rust 还在漏——覆盖率 2,227/7,996 就不是终值。
import io, os, re, struct, collections, sys

sys.path.insert(0, r'.scratch/dyn')

NAME = re.compile(b'[ -~]{3,31}' + bytes([0]))


def mat_ok(raw, off):
    if off + 64 > len(raw):
        return False
    f = struct.unpack_from('<16f', raw, off)
    if f[15] != 1.0:
        return False
    rows = [f[0:4], f[4:8], f[8:12]]
    lens = [sum(x * x for x in r) ** 0.5 for r in rows]
    if min(lens) < 1e-6 or max(lens) / min(lens) > 1.5:
        return False
    for i, j in ((0, 1), (0, 2), (1, 2)):
        d = sum(rows[i][k] * rows[j][k] for k in range(4))
        if abs(d) > 0.02 * lens[i] * lens[j]:
            return False
    return True


def table(raw, off, vc):
    if off + 4 > len(raw):
        return None
    n = struct.unpack_from('<I', raw, off)[0]
    if n == 0 or n > vc or off + 4 + 8 * n > len(raw):
        return None
    idx = struct.unpack_from('<%dI' % n, raw, off + 4)
    w = struct.unpack_from('<%df' % n, raw, off + 4 + 4 * n)
    if len(set(idx)) != n or max(idx) >= vc:
        return None
    if min(w) < 0.0 or max(w) > 1.0001 or all(x <= 1e-6 for x in w):
        return None
    return n


def scan_paths(path):
    """返回这份文件里 python 认到的每条带表记录：(名字, 偏移 mod 4, 顶点数)"""
    raw = open(path, 'rb').read()
    if len(raw) < 0x90 or not raw.startswith(b'Copyright'):
        return []
    vc = struct.unpack_from('<I', raw, 0x8C)[0]
    if not (0 < vc < 400000):
        return []
    out = []
    for m in NAME.finditer(raw):
        off = m.start()
        if off and 32 <= raw[off - 1] < 127:
            continue
        if raw[off:off + 3] == b'tx_':
            continue
        if not mat_ok(raw, off + 32):
            continue
        t = table(raw, off + 96, vc)
        if t is None:
            continue
        out.append((m.group()[:-1].decode('ascii', 'replace'), off % 4, t))
    return out


# 1) 连表：python 的键是 tree/xxx，Rust(mixcensus) 的键是相对 .scratch/out/tree 的 xxx
rust = {}
for line in io.open(r'.scratch/dyn/mixcensus.tsv', encoding='utf-8'):
    p = line.rstrip('\n').split('|')
    if len(p) < 8 or p[0] == 'file':
        continue
    rust[p[0].replace('\\', '/')] = (int(p[1]), int(p[2]), int(p[3]))

py = {}
for line in io.open(r'.scratch/tree_weights_python.txt', encoding='utf-8'):
    p = line.rstrip('\n').split('|')
    if len(p) < 5 or p[0] == 'file':
        continue
    k = p[0]
    if k.startswith('tree/'):
        k = k[len('tree/'):]
    else:
        continue
    py[k] = (int(p[1]), int(p[2]), int(p[3]))

out = io.open(r'.scratch/dyn/py_vs_rust.txt', 'w', encoding='utf-8', newline='')
both = set(py) & set(rust)
out.write('python %d 行 · Rust %d 行 · 两边都有的 %d 份\n' % (len(py), len(rust), len(both)))
more = [k for k in both if py[k][1] > rust[k][1]]
less = [k for k in both if py[k][1] < rust[k][1]]
out.write('python 比 Rust 多认表的：%d 份 · Rust 比 python 多的：%d 份\n' % (len(more), len(less)))
out.write('（Rust 多的那份方向此前已定：Rust 扫相位会前进/跳过，python 按名字去重口径不同）\n\n')

hist = collections.Counter()
files_by_cause = collections.Counter()
tot_extra = 0
for k in sorted(more):
    full = os.path.join('.scratch/out/tree', k)
    recs = scan_paths(full)
    extra = max(0, len(recs) - rust[k][1])
    tot_extra += extra
    mods = collections.Counter(m for _, m, _ in recs)
    for m, c in mods.items():
        hist[m] += c
    kinds = set(m for _, m, _ in recs)
    if kinds <= {0, 2}:
        cause = '全在 Rust 已扫的 0/2 相位 ⇒ 差在去重/白名单，不是对齐'
    else:
        cause = '有记录落在 1 或 3 相位 ⇒ Rust 少扫这两个相位'
    files_by_cause[cause] += 1
    if len(files_by_cause) and cause.startswith('有记录落在'):
        if sum(files_by_cause.values()) <= 12:
            out.write('%s · python %d 条 Rust %d 条 · 相位分布 %s · 例 %s\n'
                      % (k, len(recs), rust[k][1], dict(mods), recs[:4]))
out.write('\n带表记录的相位分布（python 口径，只算多认的那些文件）：%s\n' % dict(sorted(hist.items())))
out.write('按成因分档：%s\n' % dict(files_by_cause))
out.write('python 比 Rust 多认的表总数：%d 张\n' % tot_extra)
out.close()
print(open(r'.scratch/dyn/py_vs_rust.txt', encoding='utf-8').read()[:2600])
