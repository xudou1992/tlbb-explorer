"""找 .mesh 的读取端：aMesh("mesh") 字符串被谁引用、那些函数长什么样。"""
import ida_bytes, ida_name, ida_funcs, idautils, idc, json, os

out = []
# 1) 全库找内容为 "mesh" 的字符串地址（引擎用它当类型标签）
ea = idc.get_inf_attr(idc.INF_MIN_EA)
max_ea = idc.get_inf_attr(idc.INF_MAX_EA)
hits = []
while ea < max_ea and len(hits) < 40:
    s = idc.get_strlit_contents(ea, -1, 0)
    if s == b"mesh":
        hits.append(ea)
        ea += 8
    else:
        ea = idc.next_head(ea, max_ea)
out.append(("mesh 串地址", [hex(h) for h in hits]))

# 2) 每个引用的所在函数
refs = {}
for h in hits:
    for xr in idautils.XrefsTo(h, 0):
        f = ida_funcs.get_func(xr.frm)
        name = idc.get_func_name(xr.frm) if f else "?"
        refs.setdefault(name, []).append((hex(xr.frm), hex(f.start_ea) if f else "?"))
out.append(("引用者", {k: v[:6] for k, v in sorted(refs.items())}))

# 3) 顺带：装载器邻居区（0x14072F000..0x140740000）里所有函数的大小与
#    是否出现 0x60/96 这类步长，帮助认出网格读取端
near = []
for fea in idautils.Functions(0x14072F000, 0x140745000):
    f = ida_funcs.get_func(fea)
    if not f:
        continue
    size = f.end_ea - f.start_ea
    if size < 0x200:
        continue
    txt = []
    for head in idautils.Functions(fea, f.end_ea):
        pass
    near.append((hex(fea), size, idc.get_func_name(fea)))
out.append(("该区大函数", near[:40]))

with open(r"D:\TLGL\.scratch\ida\mesh_find.out", "w", encoding="utf-8") as fp:
    json.dump(out, fp, ensure_ascii=False, indent=1, default=str)
print(json.dumps(out, ensure_ascii=False, default=str)[:3000])
