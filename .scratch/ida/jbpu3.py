import idaapi, idautils, idc, ida_bytes, ida_segment
out = open(r"D:\TLGL\.scratch\ida\jbpu3_out.txt", "w", encoding="utf-8")
def w(*a): print(*a, file=out, flush=True)
pat = b"JBPU"
hits = []
for seg in idautils.Segments():
    s = ida_segment.getseg(seg)
    if not s: continue
    ea = s.start_ea
    end = s.end_ea
    while ea < end:
        b = ida_bytes.get_bytes(ea, min(0x10000, end - ea))
        if not b: break
        i = b.find(pat)
        if i >= 0:
            hits.append(ea + i)
            b2 = b[i+4:i+64]
            w(hex(ea+i), "ctx", b2.hex())
            ea = ea + i + 4
        else:
            ea += len(b)
        if len(hits) >= 10: break
    if len(hits) >= 10: break
w("hits", len(hits))
out.close()
idc.qexit(0)
