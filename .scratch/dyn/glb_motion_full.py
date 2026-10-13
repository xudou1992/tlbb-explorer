# -*- coding: utf-8 -*-
# 全库导出（.scratch/out/glb_full）里，那些标着 rigged 的 GLB 到底有多少**带动画且动画真在动**。
# 判据与 271 份那次同一条：读 GLB 二进制，逐 sampler 的 output accessor 算逐帧最大跨度 > 1e-4。
import io, json, os, struct, collections

ROOT = '.scratch/out/glb_full'
man = json.load(io.open(os.path.join(ROOT, 'manifest.json'), encoding='utf-8'))
assets = man['assets'] if isinstance(man, dict) else man
rig = [a for a in assets if a.get('rigged')]
o = io.open('.scratch/dyn/glb_motion_full.txt', 'w', encoding='utf-8', newline='')
o.write('manifest 条目 %d · 标 rigged 的 %d 个\n\n' % (len(assets), len(rig)))

def read(fn):
    b = open(os.path.join(ROOT, fn), 'rb').read()
    off, g, bin_ = 12, None, b''
    while off + 8 <= len(b):
        ln, ty = struct.unpack_from('<II', b, off)
        off += 8
        if ty == 0x4E4F534A:
            g = json.loads(b[off:off + ln].decode('utf-8'))
        elif ty == 0x004E4942:
            bin_ = b[off:off + ln]
        off += ln
    return g, bin_

def acc(g, buf, i):
    a = g['accessors'][i]
    bv = g['bufferViews'][a['bufferView']]
    base = bv.get('byteOffset', 0) + a.get('byteOffset', 0)
    comp = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4}[a['type']]
    fmt = {5126: 'f', 5123: 'H', 5125: 'I'}[a['componentType']]
    sz = struct.calcsize(fmt)
    step = bv.get('byteStride') or (sz * comp)
    return a['count'], fmt, comp, base, step, buf

stat = collections.Counter()
span_med = []
for a in rig[:2400]:
    fn = a.get('glb')
    if not fn or not os.path.exists(os.path.join(ROOT, fn)):
        stat['文件不在'] += 1
        continue
    g, buf = read(fn)
    anims = g.get('animations', [])
    if not anims:
        stat['无 animation 节点'] += 1
        continue
    ch = mv = 0
    best = 0.0
    for an in anims:
        for s in an.get('samplers', []):
            if 'output' not in s:
                continue
            n, fmt, comp, base, step, bb = acc(g, buf, s['output'])
            if n < 2:
                continue
            cols = [0.0] * comp
            prev = None
            for k in range(n):
                vals = struct.unpack_from('<%d%s' % (comp, fmt), bb, base + k * step)
                for d in range(comp):
                    span = abs(vals[d] - vals[0])
                    if span > best:
                        best = span
                    if span > 1e-4:
                        cols[d] = 1
            ch += comp
            mv += sum(cols)
    stat['带动画文件'] += 1
    if mv == 0:
        stat['其中一条通道都不动'] += 1
    span_med.append(best)
span_med.sort()
o.write('扫了 %d 个 rigged GLB：\n' % len(span_med))
for k, v in stat.most_common():
    o.write('  %-22s %d\n' % (k, v))
if span_med:
    o.write('  每份最大跨度中位 %.3f · p90 %.3f · 最小 %.5f\n'
            % (span_med[len(span_med)//2], span_med[int(len(span_med)*0.9)], span_med[0]))
o.close()
print('done')
