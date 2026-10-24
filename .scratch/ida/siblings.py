import idaapi, idautils, idc, ida_bytes, ida_funcs, ida_name
out = open(r"D:\TLGL\.scratch\ida\siblings_out.txt", "w", encoding="utf-8")
def w(*a): print(*a, file=out, flush=True)
def fn(ea):
    f = ida_funcs.get_func(ea)
    return (ida_name.get_name(f.start_ea) or hex(f.start_ea), f.end_ea - f.start_ea) if f else ("(nofunc)", 0)
keys = ["load failed", "is empty", "Open file", "MeshList", "ModelList", "mesh file", "Mesh file", "MESH"]
seen = set()
try:
    for s in idautils.Strings():
        t = str(s)
        if not any(k in t for k in keys): continue
        if len(t) > 120: continue
        xs = list(idautils.XrefsTo(s.ea))
        if not xs: continue
        w(repr(t))
        for x in xs[:4]:
            n, sz = fn(x.frm)
            w("    <-", hex(x.frm), n, "size", sz)
except Exception as e:
    w("strings fail", repr(e))
out.close()
idc.qexit(0)
