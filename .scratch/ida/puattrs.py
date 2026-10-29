import idaapi, idautils, idc, ida_funcs, ida_name
out = open(r"D:\TLGL\.scratch\ida\puattrs_out.txt", "w", encoding="utf-8")
def w(*a): print(*a, file=out, flush=True)
def fn(ea):
    f = ida_funcs.get_func(ea)
    return (ida_name.get_name(f.start_ea) or hex(f.start_ea), f.end_ea - f.start_ea) if f else ("(nofunc)", 0)
want = {"colours","colour","basespeed","gravity","align","scale","width","height","velocity"}
found = []
for s in idautils.Strings():
    t = str(s)
    if len(t) < 4 or len(t) > 40: continue
    if t.lower() in want:
        found.append((s.ea, t))
w("matched strings:", len(found))
for ea, t in found[:30]:
    w(repr(t), hex(ea))
    for x in idautils.XrefsTo(ea):
        w("   <-", hex(x.frm), fn(x.frm), "type", x.type)
out.close()
idc.qexit(0)
