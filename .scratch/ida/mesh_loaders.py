import idaapi, idautils, idc, ida_funcs, ida_hexrays, ida_bytes, ida_name
out = open(r"D:\TLGL\.scratch\ida\mesh_loaders_out.txt", "w", encoding="utf-8")
def w(*a): print(*a, file=out, flush=True)
def dec(ea, limit=7000):
    try:
        cf = ida_hexrays.decompile(ea)
        return str(cf)[:limit] if cf else "(no decomp)"
    except Exception as e:
        return "decomp fail " + repr(e)
# 1) ".mesh" 字符串的引用
w("== xrefs of '.mesh' (0x140eea824) ==")
for x in idautils.XrefsTo(0x140eea824):
    f = ida_funcs.get_func(x.frm)
    w(hex(x.frm), ida_name.get_name(f.start_ea) if f else "(no func)", hex(f.start_ea) if f else "")
# 2) EsMesh RTTI / vftable 的引用（找构造函数与使用点）
w("\n== xrefs of EsMesh RTTI (.?AVEsMesh@@ = 0x141094598) ==")
for x in idautils.XrefsTo(0x141094598):
    f = ida_funcs.get_func(x.frm)
    w(hex(x.frm), ida_name.get_name(f.start_ea) if f else "(no func)", hex(f.start_ea) if f else "")
# 3) 五个文件头引用者
for ea in [0x14070FB70, 0x14072F6F0, 0x140736070, 0x1407A6E40]:
    w("\n\n########## " + hex(ea) + " " + (ida_name.get_name(ea) or "") + " ##########")
    w(dec(ea))
out.close()
idc.qexit(0)
