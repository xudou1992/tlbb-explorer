"""v0.5.0 复合层预探（pose.rs 开工前的数字底）：
1. .ani 第 0 帧沿父链组合（world = local·parent_world，缺轨道的骨恒等）出骨架；
2. 与网格顶点重心（按影响表加权）对比——组合骨架是否"站"在网格里；
3. 存储矩阵 W/L 两种口径下的骨位 vs 重心距离对照。
"""
import struct, math, re

mb = open('.scratch/ani/w1351_monster_xiyuqiezei_yifu_001.mesh', 'rb').read()
VC = struct.unpack_from('<I', mb, 0x8C)[0]
NAME_OK = re.compile(rb"[0-9A-Za-z_\-.]{3,31}")


def name_at(buf, off):
    if off < 1 or off + 32 > len(buf):
        return None
    if re.match(rb"[0-9A-Za-z_\-.]", buf[off - 1:off]):
        return None
    m = NAME_OK.match(buf, off)
    if not m:
        return None
    s = m.group()
    if buf[off + len(s)] != 0 or any(x != 0 for x in buf[off + len(s):off + 32]):
        return None
    return s.decode()


def u32(buf, off):
    return struct.unpack_from('<I', buf, off)[0]


def rec_at(buf, off):
    nm = name_at(buf, off)
    if nm is None:
        return None
    m = list(struct.unpack_from('<16f', buf, off + 32))
    if abs(m[15] - 1.0) > 1e-3:
        return None
    rows = [m[0:3], m[4:7], m[8:11]]
    lens = [math.sqrt(sum(v * v for v in r)) for r in rows]
    if min(lens) < 1e-6 or max(lens) / min(lens) > 1.05:
        return None
    for i in range(3):
        for k in range(i + 1, 3):
            if abs(sum(rows[i][t] * rows[k][t] for t in range(3))) / (lens[i] * lens[k]) > 0.03:
                return None
    return nm, m


def is_u92(buf, off):
    d = struct.unpack_from('<f', buf, off)[0]
    if not (0.9 <= d <= 1.1):
        return False
    if abs(struct.unpack_from('<f', buf, off + 20)[0] - d) > 1e-6 or abs(struct.unpack_from('<f', buf, off + 40)[0] - d) > 1e-6:
        return False
    if abs(struct.unpack_from('<f', buf, off + 60)[0] - 1.0) > 1e-3:
        return False
    return all(abs(struct.unpack_from('<f', buf, off + o)[0] - 100.0) < 1e-2 for o in (76, 80, 84))


def is_mat64(buf, off):
    m = list(struct.unpack_from('<16f', buf, off))
    if not all(math.isfinite(v) and abs(v) < 1e7 for v in m):
        return False
    if any(abs(m[k]) > 1e-3 for k in (3, 7, 11)) or abs(m[15] - 1.0) > 1e-3:
        return False
    rows = [m[0:3], m[4:7], m[8:11]]
    lens = [math.sqrt(sum(v * v for v in r)) for r in rows]
    if min(lens) < 1e-4 or max(lens) / min(lens) > 1.05:
        return False
    for i in range(3):
        for k in range(i + 1, 3):
            if abs(sum(rows[i][t] * rows[k][t] for t in range(3))) > 1e-2:
                return False
    return True


def is_inf(buf, off, vc):
    n = u32(buf, off)
    if n == 0:
        return True, 0
    if n > vc or off + 4 + 8 * n > len(buf):
        return False, 0
    last = 0
    for k in range(n):
        v = u32(buf, off + 4 + 4 * k)
        if k > 0 and v <= last:
            return False, 0
        if v >= vc:
            return False, 0
        last = v
    return True, n


def blocks(buf, p, vc):
    inf = None
    while True:
        if is_u92(buf, p):
            p += 88
            continue
        if is_mat64(buf, p):
            p += 64
            continue
        ok, n = is_inf(buf, p, vc)
        if ok:
            if n:
                vs = list(struct.unpack_from('<%dI' % n, buf, p + 4))
                ws = list(struct.unpack_from('<%df' % n, buf, p + 4 + 4 * n))
                inf = (vs, ws)
            p += 4 + 8 * n
            continue
        break
    return p, inf


def walk_tail(buf, vc):
    entries, p = [], 0x7690
    while p < len(buf):
        r = rec_at(buf, p)
        if r:
            q, own_inf = blocks(buf, p + 96, vc)
            q += 4
            nm1 = name_at(buf, q)
            if nm1 and nm1 == r[0]:
                q += 64
                c = u32(buf, q)
                q += 4
                kids = []
                for _ in range(c):
                    cr = rec_at(buf, q)
                    if cr:
                        q2, inf2 = blocks(buf, q + 96, vc)
                        kids.append((cr[0], cr[1], inf2))
                        q = q2
                    else:
                        kids.append((name_at(buf, q), None, None))
                        q += 32
                entries.append({'name': nm1, 'bind': r[1], 'inf': own_inf, 'kids': kids})
                p = q
                continue
            entries.append({'name': r[0], 'bind': r[1], 'inf': own_inf, 'kids': []})
            p += 96
            continue
        q, own_inf = blocks(buf, p, vc)
        q += 4
        nm1 = name_at(buf, q)
        if nm1 is None:
            break
        q += 64
        c = u32(buf, q)
        q += 4
        kids = []
        for _ in range(c):
            cr = rec_at(buf, q)
            if cr:
                q2, inf2 = blocks(buf, q + 96, vc)
                kids.append((cr[0], cr[1], inf2))
                q = q2
            else:
                kids.append((name_at(buf, q), None, None))
                q += 32
        entries.append({'name': nm1, 'bind': None, 'inf': own_inf, 'kids': kids})
        p = q
    # 孩子记录带的影响表也归到孩子骨名下
    infs = {}
    for e in entries:
        if e['inf']:
            infs[e['name']] = e['inf']
        for kn, _kb, _ki, in e['kids'] if False else []:
            pass
    return entries, p


def walk_tail2(buf, vc):
    entries, p = [], 0x7690
    while p < len(buf):
        r = rec_at(buf, p)
        if r:
            q, own_inf = blocks(buf, p + 96, vc)
            q += 4
            nm1 = name_at(buf, q)
            if nm1 and nm1 == r[0]:
                q += 64
                c = u32(buf, q)
                q += 4
                kids = []
                for _ in range(c):
                    cr = rec_at(buf, q)
                    if cr:
                        q2, inf2 = blocks(buf, q + 96, vc)
                        kids.append((cr[0], cr[1], inf2))
                        q = q2
                    else:
                        kids.append((name_at(buf, q), None, None))
                        q += 32
                entries.append({'name': nm1, 'bind': r[1], 'inf': own_inf, 'kids': kids})
                p = q
                continue
            entries.append({'name': r[0], 'bind': r[1], 'inf': own_inf, 'kids': []})
            p += 96
            continue
        q, own_inf = blocks(buf, p, vc)
        q += 4
        nm1 = name_at(buf, q)
        if nm1 is None:
            break
        q += 64
        c = u32(buf, q)
        q += 4
        kids = []
        for _ in range(c):
            cr = rec_at(buf, q)
            if cr:
                q2, inf2 = blocks(buf, q + 96, vc)
                kids.append((cr[0], cr[1], inf2))
                q = q2
            else:
                kids.append((name_at(buf, q), None, None))
                q += 32
        entries.append({'name': nm1, 'bind': None, 'inf': own_inf, 'kids': kids})
        p = q
    return entries, p


entries, endp = walk_tail2(mb, VC)
print('entries', len(entries), 'tail end', hex(endp), 'file', hex(len(mb)))
infs = {}
for e in entries:
    if e['inf']:
        infs[e['name']] = e['inf']
    for kn, kb, ki in e['kids']:
        if ki:
            infs[kn] = ki
print('bones with influence tables:', len(infs))

name2i = {e['name']: i for i, e in enumerate(entries)}
par = [None] * len(entries)
bind = [e['bind'] for e in entries]
for e in entries:
    for kn, kb, _ki in e['kids']:
        j = name2i[kn]
        par[j] = name2i[e['name']]
        if kb is not None and bind[j] is None:
            bind[j] = kb

pos = list(struct.unpack_from('<%df' % (VC * 3), mb, 0x118))
V = [(pos[3 * i], pos[3 * i + 1], pos[3 * i + 2]) for i in range(VC)]


def centroid(nm):
    c = infs.get(nm)
    if not c:
        return None
    vs, ws = c
    sw = sum(ws)
    return tuple(sum(V[v][k] * w for v, w in zip(vs, ws)) / sw for k in range(3)) + (sw,)


def matmul(a, m):
    return [sum(a[r * 4 + k] * m[k * 4 + c] for k in range(4)) for r in range(4) for c in range(4)]


I16 = [1.0 if r == c else 0.0 for r in range(4) for c in range(4)]


def compose(locals_):
    W = [None] * len(entries)
    ch = True
    while ch:
        ch = False
        for i, e in enumerate(entries):
            if W[i] is not None:
                continue
            l = locals_[i] if locals_[i] else I16
            pp = par[i]
            if pp is None:
                W[i] = l
                ch = True
            elif W[pp] is not None:
                W[i] = matmul(l, W[pp])
                ch = True
    return W


# ---- .ani frame 0
a = open('.scratch/ani/w1351_monster_xiyuqiezei_idle01.ani', 'rb').read()
bones = struct.unpack_from('<H', a, 0xba)[0]
frames = struct.unpack_from('<H', a, 0xc2)[0]
anames = []
for i in range(bones):
    slot = a[0xf0 + i * 30:0xf0 + i * 30 + 30]
    end = slot.find(b'\0')
    if end < 0:
        end = 30
    anames.append(slot[:end].decode('ascii', 'replace'))
base = len(a) - bones * frames * 32


def quat(q):
    x, y, z, w = q
    return [1 - 2 * (y * y + z * z), 2 * (x * y + w * z), 2 * (x * z - w * y),
            2 * (x * y - w * z), 1 - 2 * (x * x + z * z), 2 * (y * z + w * x),
            2 * (x * z + w * y), 2 * (y * z - w * x), 1 - 2 * (x * x + y * y)]


def frame_local(f):
    out = [None] * bones
    for i in range(bones):
        o = base + i * frames * 32
        q = struct.unpack_from('<4f', a, o + f * 16)
        pp = struct.unpack_from('<3f', a, o + frames * 16 + f * 12)
        s = struct.unpack_from('<f', a, o + frames * 28 + f * 4)[0]
        r = quat(q)
        out[i] = (r[0:3] + [0] + r[3:6] + [0] + r[6:9] + [0] + list(pp) + [1.0], s)
    return out


named = [(nm, i) for i, nm in enumerate(anames) if nm]
print('ani tracks %d, named %d, unnamed idx %s' % (bones, len(named), [i for i, nm in enumerate(anames) if not nm]))
print('hierarchy bones missing a track:', [e['name'] for e in entries if e['name'] not in set(anames)])
missing_track = set(e['name'] for e in entries) - set(nm for nm in anames if nm)
print('missing_track set:', missing_track)

for FR in (0, 20):
    loc_by_name = {}
    for i, nm in enumerate(anames):
        if nm:
            loc_by_name[nm] = frame_local(FR)[i]
    locs = [loc_by_name.get(e['name'], (I16, 1.0))[0] for e in entries]
    W = compose(locs)
    print()
    print('=== idle01 第 %d 帧组合世界 vs 顶点重心 ===' % FR)
    tot = 0.0
    cnt = 0
    for i, e in enumerate(entries):
        t = W[i][12:15]
        c = centroid(e['name'])
        if c:
            d = math.sqrt((c[0] - t[0]) ** 2 + (c[1] - t[1]) ** 2 + (c[2] - t[2]) ** 2)
            tot += d
            cnt += 1
            flag = ' <<<' if d > 1.0 else ''
            print('%-24s (%8.4f,%8.4f,%8.4f)  c(%6.2f,%6.2f,%6.2f) d=%6.3f%s' % (e['name'], t[0], t[1], t[2], c[0], c[1], c[2], d, flag))
    print('mean centroid distance: %.3f over %d bones' % (tot / cnt, cnt))

# ---- bind W/L 对照（同表输出）
print()
print('=== 存储矩阵两种口径 vs 顶点重心 ===')
locW = [bind[i] for i in range(len(entries))]
WW = compose(locW)
locL = [bind[i] for i in range(len(entries))]
WL = compose(locL)
totW = totL = cnt = 0
for i, e in enumerate(entries):
    c = centroid(e['name'])
    if not c:
        continue
    tW = WW[i][12:15]
    tL = WL[i][12:15]
    dW = math.sqrt((c[0] - tW[0]) ** 2 + (c[1] - tW[1]) ** 2 + (c[2] - tW[2]) ** 2)
    dL = math.sqrt((c[0] - tL[0]) ** 2 + (c[1] - tL[1]) ** 2 + (c[2] - tL[2]) ** 2)
    totW += dW
    totL += dL
    cnt += 1
    print('%-24s dW=%6.3f dL=%6.3f' % (e['name'], dW, dL))
print('mean: W %.3f  L %.3f over %d' % (totW / cnt, totL / cnt, cnt))
