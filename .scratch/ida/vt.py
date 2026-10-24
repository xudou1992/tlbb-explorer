import idaapi, idautils, idc, ida_bytes, ida_funcs, ida_name, ida_hexrays
out = open(r"D:\TLGL\.scratch\ida\vt_out.txt", "w", encoding="utf-8")
def w(*a): print(*a, file=out, flush=True)
def fn(ea):
    f = ida_funcs.get_func(ea)
    return (ida_name.get_name(f.start_ea) or hex(f.start_ea), f.end_ea - f.start_ea) if f else ("(nofunc)", 0)
for v in (0x140f09e10, 0x140f09cb8):
    w("\n== xrefs to vftable", hex(v), "==")
    for x in idautils.XrefsTo(v):
        w(hex(x.frm), fn(x.frm), "type", x.type)
out.close()
idc.qexit(0)
