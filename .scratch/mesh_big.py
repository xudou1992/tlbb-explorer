import struct

d = open(r"D:\TLGL\.scratch\meshbin_test_jianzhen.mesh.bin", "rb").read()
vc, fc, sm = struct.unpack_from("<3I", d, 0x8C)
print("vc=%d fc=%d sm=%d size=%d" % (vc, fc, sm, len(d)))

# 找 u32 == fc 的所有出现位置
target = struct.pack("<I", fc)
pos = []
i = d.find(target)
while i >= 0 and len(pos) < 40:
    pos.append(i)
    i = d.find(target, i + 1)
print("u32==fc 出现:", pos)

# 也找 0x8C/0x90/0x94 的重复（第二套几何头？）
for val, nm in [(vc, "vc"), (fc, "fc")]:
    t = struct.pack("<I", val)
    hits = []
    i = d.find(t)
    while i >= 0 and len(hits) < 10:
        hits.append(hex(i))
        i = d.find(t, i + 1)
    print(nm, "hits:", hits)

# 检查 0x118 处顶点流假设的结束位置附近的数据形态
after_v = 0x118 + vc * 32
print("after verts %#x:" % after_v, " ".join("%02x" % b for b in d[after_v:after_v + 32]))
# 那里如果是 f32，看看像不像坐标
f = struct.unpack_from("<6f", d, after_v)
print("as f32:", [round(x, 3) for x in f])

# 找到 fc 出现点后，验证后面 fc*6 字节是否像合法 u16 索引（max < vc）
for p in pos[:8]:
    seg = d[p + 4: p + 4 + min(fc * 6, 1200)]
    if len(seg) < 6:
        continue
    idxs = struct.unpack_from("<%dH" % (len(seg) // 2), seg)
    mx = max(idxs)
    print("at %#x: 首16索引=%s max=%d %s" % (
        p, idxs[:16], mx, "OK" if mx < vc else "越界"))
