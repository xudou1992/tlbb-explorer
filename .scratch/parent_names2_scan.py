"""找出尾部所有「同名 32B 名字槽 ×2」的组(NAMES2),打印每组前后的 u32
与随后的孩子名单,用于定死父链字段。结果写 json+txt。"""
import json
import math
import re
import struct
import sys

path = sys.argv[1] if len(sys.argv) > 1 else ".scratch/ani/w1351_monster_xiyuqiezei_yifu_001.mesh"
out_json = sys.argv[2] if len(sys.argv) > 2 else ".scratch/parent_names2.json"
out_txt = sys.argv[3] if len(sys.argv) > 3 else ".scratch/parent_names2.txt"
b = open(path, "rb").read()
NAME_OK = re.compile(rb"[0-9A-Za-z_\-.]{3,40}")


def name_at(off):
    if off > 0:
        prev = b[off - 1:off]
        if re.match(rb"[0-9A-Za-z_\-.]", prev):
            return None
    m = NAME_OK.match(b, off)
    if not m:
        return None
    s = m.group()
    if len(s) > 31:
        return None
    if b[off + len(s)] != 0:
        return None
    if any(x != 0 for x in b[off + len(s):off + 32]):
        return None
    return s.decode()


def u32(off):
    return struct.unpack_from("<I", b, off)[0]


def f32(off):
    return struct.unpack_from("<f", b, off)[0]


# 全文件扫描名字槽(尾部区域:从 origin 记录前一点到 EOF)
TAIL = 0x7690
names = {}
i = TAIL
while i + 32 <= len(b):
    n = name_at(i)
    if n:
        names[i] = n
        i += 4
    else:
        i += 4

# NAMES2: 名字槽 off 与 off+32 同名
groups = []
for off in sorted(names):
    if off + 32 in names and names[off + 32] == names[off]:
        # 排除重叠(名字很长时 off+32 可能落在槽内,但槽是 32B 对齐的,ok)
        groups.append((off, names[off]))

# 对每个组:前 u32(组前 4B)、前 4B 是否 0.9998/矩阵尾;后 32B 的 u32 流
lines = []
w = lines.append
data = []
w("file=%s  NAMES2 groups=%d" % (path, len(groups)))
for off, nm in groups:
    pu = u32(off - 4)
    pf = f32(off - 4)
    # 向前找:这个组前面最近的块
    after = []
    for k in range(32, 32 + 4 * 12, 4):
        o = off + 64 + k - 32
        v = u32(o)
        after.append(v)
    # 收集组后面的名字(连续 32B 名字槽)
    kids = []
    o = off + 64
    while o in names:
        kids.append((o, names[o]))
        o += 32
    data.append({
        "at": off, "hex": "0x%06x" % off, "name": nm,
        "u32_before": pu, "f32_before": pf,
        "u32_after_first8": after[:8],
        "kids": [{"at": k, "name": n} for k, n in kids],
    })
    w("0x%06x %-30s before_u32=%-11d before_f32=%.4g  after_u32=%s  kids=%s" %
      (off, nm, pu, pf, after[:8], [n for _, n in kids]))

open(out_txt, "w", encoding="utf-8").write("\n".join(lines))
json.dump(data, open(out_json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("written", out_txt)
