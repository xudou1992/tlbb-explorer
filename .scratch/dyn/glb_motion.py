# 「补齐动作配对后重导」这批 GLB 的质量闸（静态、不需要人点头）：
# 每条动画通道真在动吗？——取 output accessor 的逐帧值，算通道内的变化幅度。
# 为什么要单独量：上一班踩过「骨骼挂上了但整张不动」的坑（整张挂根骨 103→14），
# 而 mesh2glb 的日志只报「写出 N 关节 × 3 通道」，不报**通道里有没有值差**。
import io, json, os, struct, sys, collections

GLB = r'.scratch/out/glb_repair'
LIMIT = int(sys.argv[1]) if len(sys.argv) > 1 else 10 ** 6


def chunks(b):
    assert b[:4] == b'glTF', b[:8]
    off, out = 12, []
    total = len(b)
    while off + 8 <= total:
        ln, ty = struct.unpack_from('<II', b, off)
        off += 8
        out.append((ty, b[off:off + ln]))
        off += ln
    return out


def accessor(g, buf, i):
    a = g['accessors'][i]
    bv = g['bufferViews'][a['bufferView']]
    base = bv.get('byteOffset', 0) + a.get('byteOffset', 0)
    ct, n = a['componentType'], a['count']
    comp = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4}[a['type']]
    fmt = {5126: 'f', 5123: 'H', 5125: 'I'}[ct]
    sz = struct.calcsize(fmt)
    step = bv.get('byteStride') or (sz * comp)
    vals = []
    for k in range(n):
        o = base + k * step
        vals.append(struct.unpack_from('<%d%s' % (comp, fmt), buf, o))
    return a['count'], vals


def main():
    files = sorted(f for f in os.listdir(GLB) if f.lower().endswith('.glb'))[:LIMIT]
    per = []
    for fn in files:
        b = open(os.path.join(GLB, fn), 'rb').read()
        g = None
        bin_ = b''
        for ty, data in chunks(b):
            if ty == 0x4E4F534A:
                g = json.loads(data.decode('utf-8'))
            elif ty == 0x004E4942:
                bin_ = data
        anims = g.get('animations', [])
        if not anims:
            per.append((fn, 0, 0, 0.0, 0))
            continue
        ch = moving = 0
        worst = 0.0
        for an in anims:
            for s in an.get('samplers', []):
                for key in ('input', 'output'):
                    if key not in s:
                        continue
                    n, vals = accessor(g, bin_, s[key])
                    if key == 'input' or n < 2:
                        continue
                    ch += 1
                    span = 0.0
                    for d in range(len(vals[0])):
                        col = [v[d] for v in vals]
                        span = max(span, max(col) - min(col))
                    worst = max(worst, span)
                    if span > 1e-4:
                        moving += 1
        per.append((fn, len(anims), ch, worst, moving))
    o = io.open(r'.scratch/dyn/glb_motion.txt', 'w', encoding='utf-8', newline='')
    tot = len(per)
    with_anim = [p for p in per if p[1] > 0]
    all_move = [p for p in with_anim if p[4] == p[2] and p[2] > 0]
    part = [p for p in with_anim if 0 < p[4] < p[2]]
    dead = [p for p in with_anim if p[4] == 0]
    o.write('扫了 %d 个 GLB（目录 %s）\n' % (tot, GLB))
    o.write('  带动画的 %d 个 · 全部通道都有值差的 %d 个 · 部分通道恒定的 %d 个 · 一条都不动的 %d 个\n'
            % (len(with_anim), len(all_move), len(part), len(dead)))
    o.write('  通道总数 %d · 其中有值差的 %d（%.1f%%）\n'
            % (sum(p[2] for p in per), sum(p[4] for p in per),
               100.0 * sum(p[4] for p in per) / max(1, sum(p[2] for p in per))))
    o.write('  最小红绿幅度（单个通道内逐帧最大跨度）中位 %.3f\n'
            % sorted(p[3] for p in with_anim)[len(with_anim) // 2] if with_anim else '  n/a\n')
    if dead:
        o.write('  一条都不动的：%s\n' % [p[0] for p in dead][:10])
    if part:
        o.write('  部分恒定的样例：%s\n' % [(p[0], p[4], p[2]) for p in part][:6])
    o.close()
    print('scanned %d glb, %d with anim' % (tot, len(with_anim)))


main()
