import idaapi, idc, ida_bytes, ida_ua, ida_name
out = open(r"D:\TLGL\.scratch\ida\assert_out.txt", "w", encoding="utf-8")
def w(*a): print(*a, file=out, flush=True)
# 从断言引用点往前看 30 条指令，找出被比较的字段偏移
ea = 0x140643981
starts = []
p = ea
for _ in range(30):
    p = idc.prev_head(p)
    if p == idaapi.BADADDR: break
    starts.append(p)
for a in reversed(starts):
    w(hex(a), idc.generate_disasm_line(a, 0))
out.close()
idc.qexit(0)
