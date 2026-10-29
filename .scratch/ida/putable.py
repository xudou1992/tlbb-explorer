import idaapi, idc, ida_bytes, ida_name
out = open(r"D:\TLGL\.scratch\ida\putable_out.txt", "w", encoding="utf-8")
def w(*a): print(*a, file=out, flush=True)
def annot(v):
    try:
        s = idc.get_strlit_contents(v, -1, idc.STRTYPE_C)
        if s: return repr(s.decode('ascii','replace'))
    except Exception: pass
    return ""
for base in (0x141072cc8, 0x1410615a8, 0x141072008):
    w("\n== around %s ==" % hex(base))
    for k in range(-6, 7):
        ea = base + 8 * k
        v = ida_bytes.get_qword(ea)
        w("%s %s %s" % (hex(ea), hex(v), annot(v)))
out.close()
idc.qexit(0)
