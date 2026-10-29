import idaapi, idautils, idc, ida_bytes
out = open(r"D:\TLGL\.scratch\ida\jbpu2_out.txt", "w", encoding="utf-8")
def w(*a): print(*a, file=out, flush=True)
pat = b"JBPU"
found = []
for seg in idautils.Segments():
    s = ida_segment.getseg(seg) if hasattr(idaapi,'segment_t') else None
    w("seg", hex(seg))
out.close()
idc.qexit(0)
