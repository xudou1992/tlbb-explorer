import struct

def load(name):
    return open(r"D:\TLGL\.scratch\meshbin_%s.bin" % name.replace('/', '_'), "rb").read()

def hexdump(data, lo, hi):
    out = []
    for off in range(lo, min(hi, len(data)), 16):
        seg = data[off:off+16]
        hx = " ".join("%02x" % b for b in seg)
        asc = "".join(chr(b) if 0x20 <= b < 0x7f else "." for b in seg)
        out.append("%06x  %-47s  %s" % (off, hx, asc))
    return "\n".join(out)

d = load("w1351_model_plane_c01.mesh")
rep = []
rep.append("== plane_c01 全量 %d 字节 ==" % len(d))
rep.append(hexdump(d, 0, len(d)))

# 尝试解读 0x8C 起的块结构
rep.append("\n== 0x8C 起按 u32/4CC 读 ==")
off = 0x8C
while off + 8 <= len(d):
    tag = d[off:off+4]
    asc = tag.decode("ascii", "replace")
    v = struct.unpack_from("<I", d, off)[0]
    rep.append("%06x  %08x  '%s'" % (off, v, asc if tag.isascii() and all(32 <= b < 127 for b in tag) else "."))
    off += 4

# 0x8C 之后找 float 序列：连续 12 字节解释为 3 个 f32，量级在 [-5000, 5000] 且不太接近 0 指数
def f32scan(data, lo):
    hits = []
    for off in range(lo, len(data) - 12, 4):
        a, b, c = struct.unpack_from("<3f", data, off)
        for f in (a, b, c):
            if f != 0 and (abs(f) > 1e4 or abs(f) < 1e-3):
                break
        else:
            if (a, b, c) != (0, 0, 0):
                hits.append((off, round(a, 3), round(b, 3), round(c, 3)))
    return hits

rep.append("\n== plane_c01 疑似顶点(连续3x f32 合理量级) ==")
hits = f32scan(d, 0x8C)
for h in hits[:40]:
    rep.append("  %06x  %r" % (h[0], h[1:]))

open(r"D:\TLGL\.scratch\mesh_plane.txt", "w", encoding="utf-8").write("\n".join(rep))
print("done")
