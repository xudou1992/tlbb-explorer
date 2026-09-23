import struct

d = open(r"D:\TLGL\.scratch\meshbin_w1351_st_fwzhongxing_001.mesh.bin", "rb").read()
vc, fc, sm = struct.unpack_from("<3I", d, 0x8C)
print("vc=%d fc=%d sm=%d size=%d" % (vc, fc, sm, len(d)))

# 按静态布局，位置流 0x118 + vc*12，法线 vc*12，UV vc*8
pos_end = 0x118 + vc * 12
static_idx = pos_end + vc * 20
print("pos_end=%#x static_idx=%#x" % (pos_end, static_idx))
print("u32@static_idx =", struct.unpack_from("<I", d, static_idx)[0] if len(d) > static_idx + 4 else "OOB")

# 假设：尾部 7 个子网格块，每块 [u32 n][n*3 u16]，n 之和 = fc
# 从 static_idx 开始尝试按块消费
at = static_idx
blocks = []
while len(blocks) < 12 and at + 4 <= len(d):
    n = struct.unpack_from("<I", d, at)[0]
    if 0 < n <= fc and at + 4 + n * 6 <= len(d):
        seg = d[at + 4: at + 4 + min(n * 6, 60)]
        idxs = struct.unpack_from("<%dH" % (len(seg) // 2), seg)
        mx = max(idxs) if idxs else 0
        ok = mx < vc
        blocks.append((hex(at), n, ok))
        if not ok:
            break
        at = at + 4 + n * 6
        if sum(b[1] for b in blocks) == fc:
            break
    else:
        break
total = sum(b[1] for b in blocks)
print("blocks:", blocks)
print("sum=%d (fc=%d) %s" % (total, fc, "MATCH" if total == fc else "no"))
