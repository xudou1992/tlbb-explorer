"""看几个地址附近的反汇编 + 所在函数（地址从 peek_addrs.txt 逐行读）。"""
import ida_funcs, idautils, idc, json

ADDRS = [l.strip() for l in open(r"D:\TLGL\.scratch\ida\peek_addrs.txt", encoding="utf-8") if l.strip()]
out = []
for a in ADDRS:
    ea = int(a, 16)
    f = ida_funcs.get_func(ea)
    out.append(f"=== {a} 函数 {idc.get_func_name(f.start_ea) if f else '?'} "
               f"起 {hex(f.start_ea) if f else '?'} 大小 {hex(f.end_ea - f.start_ea) if f else '?'}")
    if not f:
        continue
    h = f.start_ea
    n = 0
    while h < f.end_ea and n < 400:
        line = f"{hex(h)}  {idc.print_insn_mnem(h):<7} {idc.print_operand(h,0)}, {idc.print_operand(h,1)}"
        s = idc.get_strlit_contents(idc.get_operand_value(h, 1), -1, 0) if idc.get_operand_value(h, 1) else None
        if s:
            line += "   ; " + s.decode("utf-8", "replace")[:40]
        out.append(line)
        h = idc.next_head(h, f.end_ea)
        n += 1
    out.append(f"   （函数共 {n} 条，只列前 400）")
txt = "\n".join(out)
open(r"D:\TLGL\.scratch\ida\peek.out", "w", encoding="utf-8").write(txt)
print(txt[:2000])
