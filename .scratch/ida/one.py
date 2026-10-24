import idaapi, idc, ida_hexrays
out = open(r"D:\TLGL\.scratch\ida\one_out.txt", "w", encoding="utf-8")
txt = str(ida_hexrays.decompile(0x1407A6E40))
print(txt, file=out)
out.close()
idc.qexit(0)
