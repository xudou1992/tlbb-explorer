import idaapi, idautils, idc, ida_funcs, ida_hexrays, ida_bytes, ida_name
out = open(r"D:\TLGL\.scratch\ida\bip_out.txt", "w", encoding="utf-8")
def w(*a): print(*a, file=out, flush=True)
def fn(ea):
    f = ida_funcs.get_func(ea)
    return (ida_name.get_name(f.start_ea), hex(f.start_ea), f.end_ea - f.start_ea) if f else ("(nofunc)", hex(ea), 0)
for s in [0x140ef5df0, 0x140ea3380]:  # "nMeshBipSize > 0" / "szMeshName"
    w("\n== xrefs of", hex(s), "==")
    for x in idautils.XrefsTo(s):
        w(hex(x.frm), "type", x.type, fn(x.frm))
# 名字里带 Mesh 的符号（RTTI vftable / 函数）
w("\n== names containing 'EsMesh' or 'MeshModel' ==")
cnt = 0
for ea, name in idautils.Names():
    if ("EsMesh" in name or "MeshModel" in name) and cnt < 40:
        w(hex(ea), name)
        cnt += 1
out.close()
idc.qexit(0)
