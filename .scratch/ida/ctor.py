import idaapi, idautils, idc, ida_funcs, ida_name, ida_hexrays
out = open(r"D:\TLGL\.scratch\ida\ctor_out.txt", "w", encoding="utf-8")
def w(*a): print(*a, file=out, flush=True)
def fn(ea):
    f = ida_funcs.get_func(ea)
    return (ida_name.get_name(f.start_ea) or hex(f.start_ea), f.end_ea - f.start_ea) if f else ("(nofunc)", 0)
callers = set()
for c in (0x140735B40, 0x140735D70):
    w("== callers of", hex(c), "==")
    for x in idautils.XrefsTo(c):
        if x.type in (idaapi.fl_CN, idaapi.fl_CF, 16, 17):
            w(hex(x.frm), fn(x.frm))
            callers.add(x.frm)
# 也看调用者所在函数（若不是函数头）
for x in list(callers)[:6]:
    f = ida_funcs.get_func(x)
    if not f: continue
    fea = f.start_ea
    w("\n#### caller func %s size=%d" % (hex(fea), f.end_ea - fea))
    try:
        txt = str(ida_hexrays.decompile(fea))
    except Exception as e:
        w("fail", repr(e)); continue
    for l in txt.split("\n"):
        if any(k in l for k in ["8C", "110", "memcpy", "malloc", "96", "32", "bone", "Bone", "skin", "Skin", "sub_140735B40", "sub_140735D70"]):
            w("   ", l.strip()[:180])
out.close()
idc.qexit(0)
