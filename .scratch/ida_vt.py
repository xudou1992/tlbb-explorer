# 只读：把 EsSkeleton / EsMesh 的虚表槽位与函数名导到文件里。
# 不改数据库、不命名、不保存。
import ida_bytes
import ida_name
import idaapi

BASE = idaapi.get_imagebase()
TABLES = {
    "EsSkeleton": 0x140F0A010,
    "EsSkeleton_0": 0x140F09EB8,
    "EsMesh": 0x140F09E10,
    "EsMesh_0": 0x140F09CB8,
}
lines = []
for name, vt in TABLES.items():
    lines.append("=== %s  vftable=%s" % (name, hex(vt)))
    for k in range(48):
        ea = vt + 8 * k
        fn = ida_bytes.get_qword(ea)
        if fn < BASE or fn > BASE + 0x0FFFFFFF:
            lines.append("   [%2d] %s  (不像代码)" % (k, hex(fn)))
            continue
        nm = ida_name.get_name(fn) or "?"
        end = fn
        # 函数大小：交给 idc 太慢，这里只报名字
        lines.append("   [%2d] %s  %s" % (k, hex(fn), nm))
with open(r"D:\TLGL\.scratch\ida_vt_out.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")
print("wrote", len(lines))
