import idaapi, idautils, idc, ida_funcs, ida_bytes, ida_name, ida_segment
out = open(r"D:\TLGL\.scratch\ida\f100_out.txt", "w", encoding="utf-8")
def w(*a): print(*a, file=out, flush=True)
def fn(ea):
    f = ida_funcs.get_func(ea)
    return (ida_name.get_name(f.start_ea) or hex(f.start_ea), f.end_ea - f.start_ea) if f else ("(nofunc)", 0)
# 所有 .rdata/.data 里等于 100.0f 的 dword 地址
addrs = []
for seg in idautils.Segments():
    s = ida_segment.getseg(seg)
    if s is None: continue
    name = ida_segment.get_segm_name(s)
    if name not in (".rdata", ".data", "rdata", "data"): continue
    ea = s.start_ea
    end = s.end_ea
    while ea + 4 <= end:
        if ida_bytes.get_dword(ea) == 0x42C80000:
            addrs.append(ea)
        ea += 4
w("100.0f dwords:", len(addrs))
seen = {}
for a in addrs:
    xr = list(idautils.XrefsTo(a, 0))
    if not xr: continue
    for x in xr:
        n, sz = fn(x.frm)
        seen.setdefault((n, sz), []).append((hex(a), hex(x.frm)))
w("distinct referencing funcs:", len(seen))
for (n, sz), lst in sorted(seen.items(), key=lambda kv: -len(kv[1]))[:25]:
    w(f"  {n} size={sz} refs={len(lst)} e.g. {lst[:3]}")
out.close()
idc.qexit(0)
