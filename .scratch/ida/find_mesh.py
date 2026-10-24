import idaapi, idautils, idc, ida_funcs, ida_hexrays, ida_bytes, ida_name, ida_xref
out = open(r"D:\TLGL\.scratch\ida\find_mesh_out.txt", "w", encoding="utf-8")
def w(*a): print(*a, file=out, flush=True)
def fname(ea):
    f = ida_funcs.get_func(ea)
    if not f: return "(no func)"
    n = ida_name.get_name(f.start_ea)
    return f"{n}@{hex(f.start_ea)}"
# 1) Copyright 字符串
w("== strings containing copyright / mesh extension ==")
hits = []
try:
    for s in idautils.Strings():
        t = str(s)
        lt = t.lower()
        if ("copyright" in lt) or lt.endswith(".mesh") or lt == "mesh" or ("mesh" in lt and len(t) < 40):
            hits.append((s.ea, t))
except Exception as e:
    w("strings fail", repr(e))
w("count", len(hits))
for ea, t in hits[:60]:
    w(hex(ea), repr(t))
# 2) xrefs to Copyright strings -> functions
w("\n== xrefs of copyright strings ==")
seen = set()
for ea, t in hits:
    if "copyright" not in t.lower(): continue
    for x in idautils.XrefsTo(ea):
        fn = fname(x.frm)
        w(hex(ea), repr(t), "<-", hex(x.frm), fn, "type", x.type)
        seen.add(ida_funcs.get_func(x.frm).start_ea if ida_funcs.get_func(x.frm) else 0)
# 3) 0x1410AD918 附近与 xrefs
w("\n== around qword_1410AD918 ==")
base = 0x1410AD8F0
for i in range(0, 12):
    ea = base + 8*i
    v = ida_bytes.get_qword(ea)
    w(hex(ea), hex(v))
    for x in idautils.XrefsTo(ea, 0):
        w("   xref <-", hex(x.frm), fname(x.frm))
out.close()
idc.qexit(0)
