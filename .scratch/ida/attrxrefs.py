import idaapi, idautils, idc, ida_funcs, ida_name
out = open(r"D:\TLGL\.scratch\ida\attrxrefs_out.txt", "w", encoding="utf-8")
def w(*a): print(*a, file=out, flush=True)
def fn(ea):
    f = ida_funcs.get_func(ea)
    return (ida_name.get_name(f.start_ea) or hex(f.start_ea), f.end_ea - f.start_ea) if f else ("(nofunc)", 0)
for t in (0x141071ea0, 0x1410745a0, 0x141075000):
    w("\n== xrefs to %s ==" % hex(t))
    for x in idautils.XrefsTo(t):
        w(hex(x.frm), fn(x.frm), "type", x.type)
out.close()
idc.qexit(0)
