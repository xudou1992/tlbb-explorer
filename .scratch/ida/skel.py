import idaapi, idc, ida_hexrays, ida_name
out = open(r"D:\TLGL\.scratch\ida\skel_out.txt", "w", encoding="utf-8")
def w(*a): print(*a, file=out, flush=True)
for ea in (0x140739960, 0x140735590):
    w("\n########## %s %s ##########" % (hex(ea), ida_name.get_name(ea) or ""))
    try:
        txt = str(ida_hexrays.decompile(ea))
        w(txt[:11000])
    except Exception as e:
        w("fail", repr(e))
out.close()
idc.qexit(0)
