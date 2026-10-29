import idaapi, idc, ida_hexrays, ida_name
out = open(r"D:\TLGL\.scratch\ida\mat_use_out.txt", "w", encoding="utf-8")
def w(*a): print(*a, file=out, flush=True)
for ea in (0x1409BEA90,):
    w("########## %s %s ##########" % (hex(ea), ida_name.get_name(ea) or ""))
    try:
        w(str(ida_hexrays.decompile(ea))[:4000])
    except Exception as e:
        w("fail", repr(e))
out.close()
idc.qexit(0)
