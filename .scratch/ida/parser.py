import idaapi, idc, ida_hexrays
out = open(r"D:\TLGL\.scratch\ida\parser_out.txt", "w", encoding="utf-8")
txt = str(ida_hexrays.decompile(0x14072F6F0))
print(txt, file=out)
out.close()
idc.qexit(0)
