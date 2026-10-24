import idaapi, idautils, idc, ida_bytes, ida_funcs, ida_name, ida_hexrays
out = open(r"D:\TLGL\.scratch\ida\reg_out.txt", "w", encoding="utf-8")
def w(*a): print(*a, file=out, flush=True)
def nm(ea):
    f = ida_funcs.get_func(ea)
    return (ida_name.get_name(f.start_ea) or hex(f.start_ea)) if f else "(nodata)"
w("== 0x1410AD8C0 .. 0x1410AD980 ==")
for ea in range(0x1410AD8C0, 0x1410AD980, 8):
    v = ida_bytes.get_qword(ea)
    ann = ""
    if 0x140000000 <= v < 0x142000000:
        f = ida_funcs.get_func(v)
        ann = ("FUNC " + (ida_name.get_name(v) or "")) if f and f.start_ea == v else "DATA/CODE " + (ida_name.get_name(v) or "")
    s = None
    try:
        s = idc.get_strlit_contents(v, -1, idc.STRTYPE_C)
    except Exception:
        pass
    w(hex(ea), hex(v), ann, ("STR " + repr(s.decode('ascii','replace'))) if s else "")
w("\n== xrefs to 0x1410AD918 ==")
for x in idautils.XrefsTo(0x1410AD918):
    w(hex(x.frm), nm(x.frm), "type", x.type)
w("\n== xrefs to 0x1410AD910 / 0x1410AD920 ==")
for a in (0x1410AD910, 0x1410AD920):
    for x in idautils.XrefsTo(a):
        w(hex(a), "<-", hex(x.frm), nm(x.frm), "type", x.type)
out.close()
idc.qexit(0)
