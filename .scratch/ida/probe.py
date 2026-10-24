import idaapi, idautils, idc, ida_funcs, ida_hexrays, ida_bytes, ida_name
out = open(r"D:\TLGL\.scratch\ida\probe_out.txt", "w", encoding="utf-8")
def w(*a): print(*a, file=out, flush=True)
w("funcs:", ida_funcs.get_func_qty())
ids = ["sub_1406C6380", "sub_14073FA60", "sub_14073F7A0", "sub_140136890", "sub_1400E0840"]
for n in ids:
    ea = ida_name.get_name_ea(idaapi.BADADDR, n)
    w(n, hex(ea) if ea != idaapi.BADADDR else "NOT FOUND", "func" if ea != idaapi.BADADDR and ida_funcs.get_func(ea) else "")
# 名字里带 mesh/skeleton/mesh 的符号（先看命名空间恢复了多少）
hits = []
for ea, name in idautils.Names():
    ln = name.lower()
    if ("skeleton" in ln or "skeletal" in ln) and len(hits) < 40:
        hits.append((hex(ea), name))
w("names with skeleton:", len(hits))
for h in hits: w("  ", h[0], h[1])
# 解一个已知函数
for n in ["sub_1406C6380"]:
    ea = ida_name.get_name_ea(idaapi.BADADDR, n)
    if ea != idaapi.BADADDR:
        try:
            cf = ida_hexrays.decompile(ea)
            txt = str(cf) if cf else "(no decomp)"
            w("\n===== decomp", n, hex(ea), "=====")
            w(txt[:6000])
        except Exception as e:
            w("decomp fail", n, repr(e))
out.close()
idc.qexit(0)
