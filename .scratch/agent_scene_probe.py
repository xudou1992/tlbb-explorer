import re
import struct
from pathlib import Path

f = Path(r"D:\TLGL\.scratch\out\tree\mobile_maps\w1351_fb_sxzc_001\1_3_-9.scene")
raw = f.read_bytes()
print("size", len(raw), "head u32", struct.unpack_from("<3I", raw, 0))
occ = [m.start() for m in re.finditer(rb"[ -~]{5,64}?\.mesh\x00", raw)]
print("mesh-name 出现次数", len(occ), "前 8 偏移", [hex(o) for o in occ[:8]])
print("相邻间距", [occ[i + 1] - occ[i] for i in range(min(8, len(occ) - 1))])
for i, o in enumerate(occ[:4]):
    nm = raw[o : o + 700].split(b"\x00")[0].decode("latin1", "replace")
    print(f"\n--- #{i} name@{hex(o)} = {nm!r}")
    base = o - 64
    print("   f32[16] @name-64 :", [round(x, 3) for x in struct.unpack_from("<16f", raw, base)])
    print("   u32[16] @name-64 :", [struct.unpack_from("<I", raw, base + 4 * k)[0] for k in range(16)])
    print("   名字之后 32 字节:", raw[o + len(nm) + 1 : o + len(nm) + 33].hex())

# 第一条名字之前的头部
print("\n头部 0..0x60 u32:", [struct.unpack_from("<I", raw, k)[0] for k in range(0, 0x60, 4)])
print("头部 0..0x60 f32:", [round(x, 4) for x in struct.unpack_from("<24f", raw, 0)])
last = occ[-1]
nm = raw[last : last + 700].split(b"\x00")[0]
print("\n最后一条 name@%s len=%d；文件尾距=%d" % (hex(last), len(nm), len(raw) - (last + 697)))
print("若步长恒 761：12+761*%d=%d vs 实际 %d" % (len(occ), 12 + 761 * len(occ), len(raw)))
print("按 (size-12)/N 反推 =", (len(raw) - 12) / struct.unpack_from("<I", raw, 0)[0])
