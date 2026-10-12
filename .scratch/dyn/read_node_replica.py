#!/usr/bin/env python3
"""逐条复刻 Rust `read_node` 的判据，回答：那 43 份里 python 多认的记录死在哪一条。
上一版我凭印象分类（把「前 32 字节是名字」当成拒绝理由），那次归因作废；
这次照 `preview/geometry.rs::read_node` 的顺序与常数抄：
 1 前一字不能是名字字符 2 NUL 前长度 3..40 3 字符白名单（字母数字与 _ - .）
 4 名字段剩余必须全 0 5 前 32 字节是名字**且以 tx_ 开头**才算挂点表
 6 矩阵：有限且 |v|<1e7、m[15]≈1、轴长比 ≤1.05、两两 cos ≤0.03
"""
import os, re, struct, collections

NAME = re.compile(b'[ -~]{3,31}' + bytes([0]))
OK = set(range(48, 58)) | set(range(65, 91)) | set(range(97, 123)) | {95, 45, 46}


def load(path):
    d = {}
    for line in open(path, encoding='utf-8', errors='replace').read().splitlines()[1:]:
        p = line.split('|')
        if len(p) >= 5:
            try:
                d[p[0].replace(chr(92), '/')] = (int(p[1]), int(p[2]), int(p[3]), int(p[4]))
            except ValueError:
                pass
    return d


def why(raw, off):
    if off and raw[off - 1] in OK:
        return '1 前一字是名字字符'
    field = raw[off:off + 32]
    if len(field) < 32:
        return 'EOF'
    end = field.find(bytes([0]))
    if end < 3:
        return '2 名字长度不合规'
    if any(c not in OK for c in field[:end]):
        return '3 名字有白名单外字符'
    if any(c != 0 for c in field[end:]):
        return '4 名字段填充非全 0'
    if off >= 32:
        prev = raw[off - 32:off]
        pl = prev.find(bytes([0]))
        pl = 32 if pl < 0 else pl
        if pl >= 3 and all(c in OK for c in prev[:pl]) and prev[:3].lower() == b'tx_':
            return '5 挂点表第二段'
    if off + 96 > len(raw):
        return 'EOF'
    m = struct.unpack_from('<16f', raw, off + 32)
    if any(abs(v) >= 1e7 or v != v for v in m):
        return '6 矩阵数值出界'
    if abs(m[15] - 1.0) > 1e-3:
        return '6 m15 非 1'
    R = [list(m[0:3]), list(m[4:7]), list(m[8:11])]
    L = [sum(x * x for x in v) ** 0.5 for v in R]
    mn, mx = min(L), max(L)
    if mn <= 1e-6 or mx / mn > 1.05:
        return '6 轴长比>1.05'
    for i in range(3):
        for j in range(i + 1, 3):
            if abs(sum(R[i][k] * R[j][k] for k in range(3))) / (L[i] * L[j]) > 0.03:
                return '6 三轴不正交'
    return '放行（那就要看别的差别了）'


def main():
    py = load('.scratch/tree_weights_python.txt')
    rs = {}
    rs.update(load('.scratch/tree_weights_rust_both.txt'))
    rs.update(load('.scratch/sidecar_weights_rust_both.txt'))
    py2 = {}
    for k, v in py.items():
        for pre in ('tree/', 'sidecar_tree/'):
            if k.startswith(pre):
                py2[k[len(pre):]] = v
    diff = sorted(k for k in set(py2) & set(rs) if py2[k][1] > rs[k][1])
    print('python 比 Rust 多认表的文件：%d 份' % len(diff))
    cnt = collections.Counter()
    done = 0
    for k in diff:
        path = None
        for cand in ('.scratch/out/' + k, os.path.join('.scratch/out/tree', k),
                     os.path.join('.scratch/out/sidecar_tree', k)):
            if os.path.exists(cand):
                path = cand
                break
        if not path:
            cnt['文件没找到'] += 1
            continue
        raw = open(path, 'rb').read()
        done += 1
        for m in NAME.finditer(raw):
            off = m.start()
            if off + 96 > len(raw):
                continue
            f = struct.unpack_from('<16f', raw, off + 32)
            if abs(f[15] - 1.0) > 1e-3:
                continue
            cnt[why(raw, off)] += 1
    print('看了 %d 份；python 认得的这些位置按 Rust 判据分类：' % done)
    for kk, v in cnt.most_common():
        print('   %-28s %6d' % (kk, v))


main()
