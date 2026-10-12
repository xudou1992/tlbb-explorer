# 上一条把「相位漏扫」排除了（python 多认的 30 份里，带表记录全落在 Rust 已扫的 0/2 相位），
# 剩下的成因只可能是计数口径。Rust 的去重键是 (名字, 绑定矩阵)——
# 万一**同名同矩阵的两条记录带的是两张不同的表**，Rust 丢掉第二条就是**真丢权重**。
# 这份脚本只看这一件事：把同名同矩阵成组，比较组内各条的顶点集合。
import io, os, re, struct, collections

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


def read_table(raw, off, vc):
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
    return set(idx)


rust = {}
for line in io.open(r'.scratch/dyn/mixcensus.tsv', encoding='utf-8'):
    p = line.rstrip('\n').split('|')
    if len(p) < 8 or p[0] == 'file':
        continue
    rust[p[0].replace('\\', '/')] = int(p[2])
py = {}
for line in io.open(r'.scratch/tree_weights_python.txt', encoding='utf-8'):
    p = line.rstrip('\n').split('|')
    if len(p) < 5 or p[0] == 'file' or not p[0].startswith('tree/'):
        continue
    py[p[0][len('tree/'):]] = int(p[2])
more = sorted(k for k in set(py) & set(rust) if py[k] > rust[k])

out = io.open(r'.scratch/dyn/dup_key_check.txt', 'w', encoding='utf-8', newline='')
out.write('python 多认的 %d 份，逐份查「同名同矩阵组内的表是不是同一张」\n' % len(more))
same = diff = disjoint = part = 0
for k in more:
    raw = open(os.path.join('.scratch/out/tree', k), 'rb').read()
    if not raw.startswith(b'Copyright') or len(raw) < 0x90:
        continue
    vc = struct.unpack_from('<I', raw, 0x8C)[0]
    groups = collections.defaultdict(list)
    for m in NAME.finditer(raw):
        off = m.start()
        if off and 32 <= raw[off - 1] < 127:
            continue
        if raw[off:off + 3] == b'tx_':
            continue
        if not mat_ok(raw, off + 32):
            continue
        t = read_table(raw, off + 96, vc)
        if t is None:
            continue
        key = (m.group()[:-1], raw[off + 32:off + 96])
        groups[key].append(t)
    for key, ts in groups.items():
        if len(ts) < 2:
            continue
        nm = key[0].decode('ascii', 'replace')
        uniq = [next(iter([x for x in ts if x == ts[0]]), None)]
        all_same = all(x == ts[0] for x in ts)
        inter = set.intersection(*ts)
        union = set.union(*ts)
        if all_same:
            same += 1
            tag = '顶点集合完全相同 ⇒ Rust 去重没丢东西'
        elif not inter:
            disjoint += 1
            tag = '集合完全不相交 ⇒ **Rust 丢了真权重**'
        else:
            part += 1
            tag = '部分交叠 %d/%d ⇒ 需人看' % (len(inter), len(union))
        diff += 0
        if not all_same:
            out.write('%-58s %-22s 组内 %d 条 · %s\n' % (k[-58:], nm, len(ts), tag))
out.write('\n汇总（组内 ≥2 条的同名同矩阵组）：完全相同 %d · 不相交 %d · 部分交叠 %d\n'
          % (same, disjoint, part))
out.write('判读：不相交=0 且部分交叠=0 ⇒ (名字,绑定矩阵) 这个去重键不会丢权重，'
          '两边 30/30 的差纯粹是计数口径。\n' if (disjoint == 0 and part == 0) else '判读：有非重复的组 ⇒ 去重键要改（把表本身并进键）。\n')
out.close()
print('written')
