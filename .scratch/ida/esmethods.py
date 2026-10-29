import idaapi, idc, ida_hexrays
out = open(r"D:\TLGL\.scratch\ida\esmethods_out.txt", "w", encoding="utf-8")
for ea in (0x14073F2C0, 0x14073F060):
    print("\n########## %s ##########" % hex(ea), file=out)
    try:
        print(str(ida_hexrays.decompile(ea))[:9000], file=out)
    except Exception as e:
        print("fail", repr(e), file=out)
out.close()
idc.qexit(0)
