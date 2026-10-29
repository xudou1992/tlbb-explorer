import idaapi, idautils, idc, ida_funcs, ida_name, ida_hexrays
out = open(r"D:\TLGL\.scratch\ida\attrfns_out.txt", "w", encoding="utf-8")
def w(*a): print(*a, file=out, flush=True)
def fn(ea):
    f = ida_funcs.get_func(ea)
    return (ida_name.get_name(f.start_ea) or hex(f.start_ea), f.end_ea - f.start_ea) if f else ("(nofunc)", 0)
ea = 0x140691C00
w("== decompile %s ==" % hex(ea))
try: w(str(ida_hexrays.decompile(ea))[:3000])
except Exception as e: w("fail", repr(e))
w("\n== callers of %s ==" % hex(ea))
for x in idautils.XrefsTo(ea):
    w(hex(x.frm), fn(x.frm), "type", x.type)
out.close()
idc.qexit(0)
