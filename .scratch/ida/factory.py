import idaapi, idautils, idc, ida_funcs, ida_name, ida_hexrays
out = open(r"D:\TLGL\.scratch\ida\factory_out.txt", "w", encoding="utf-8")
def w(*a): print(*a, file=out, flush=True)
def fn(ea):
    f = ida_funcs.get_func(ea)
    return (ida_name.get_name(f.start_ea) or hex(f.start_ea), f.end_ea - f.start_ea) if f else ("(nofunc)", 0)
w("== callers of EsMesh factory sub_1406C6A50 ==")
fs = set()
for x in idautils.XrefsTo(0x1406C6A50):
    w(hex(x.frm), fn(x.frm), "type", x.type)
    f = ida_funcs.get_func(x.frm)
    if f: fs.add(f.start_ea)
for fea in list(fs)[:5]:
    f = ida_funcs.get_func(fea)
    w("\n#### %s size=%d" % (hex(fea), f.end_ea - fea))
    try:
        txt = str(ida_hexrays.decompile(fea))
    except Exception as e:
        w("fail", repr(e)); continue
    for l in txt.split("\n"):
        if any(k in l for k in ["sub_1406C6A50", "memcpy", "malloc", "8C", "110", "96", "Copyright", "sub_140"]):
            w("   ", l.strip()[:180])
out.close()
idc.qexit(0)
