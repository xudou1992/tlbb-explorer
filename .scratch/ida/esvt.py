import idaapi, idc, ida_bytes, ida_funcs, ida_name
out = open(r"D:\TLGL\.scratch\ida\esvt_out.txt", "w", encoding="utf-8")
def w(*a): print(*a, file=out, flush=True)
for vt in (0x140f0a010, 0x140f09eb8):
    w("\n== vftable", hex(vt), "==")
    for i in range(0, 80):
        p = ida_bytes.get_qword(vt + 8 * i)
        if p == 0:
            w("  [%d] 0  (end)" % i); break
        f = ida_funcs.get_func(p)
        w("  [%d] %s %s size %s" % (i, hex(p), ida_name.get_name(p) or "", (f.end_ea - f.start_ea) if f else "?"))
out.close()
idc.qexit(0)
