"""在资源装载模块里找「尾部 160 字节前奏」的读写者。

判据：函数体里同时出现 160/0xA0（前奏整块）、64/0x40（一张 4×4）、96/0x60（节点记录）
这几个立即数，并且处在 0x14072F000..0x140745000 这个装载器模块里。
"""
import ida_funcs, idautils, idc, json

WANT = {160: "0xA0", 64: "0x40", 96: "0x60", 176: "0xB0", 44: "0x2C", 60: "0x3C", 272: "0x110"}
rows = []
for fea in idautils.Functions(0x14072F000, 0x140745000):
    f = ida_funcs.get_func(fea)
    if not f:
        continue
    seen = {}
    for head in idautils.Heads(f.start_ea, f.end_ea):
        for i in range(5):
            op = idc.get_operand_value(head, i)
            if op in WANT and idc.print_operand(head, i).startswith(("?", "0x")) or (op in WANT):
                seen.setdefault(op, []).append((hex(head), idc.print_insn_mnem(head), idc.print_operand(head, 0), idc.print_operand(head, 1)))
    if not seen:
        continue
    score = len([k for k in (160, 64, 96) if k in seen])
    rows.append((score, hex(fea), idc.get_func_name(fea), f.end_ea - f.start_ea,
                 {WANT[k]: v[:3] for k, v in seen.items()}))
rows.sort(key=lambda r: (-r[0], r[3]))
with open(r"D:\TLGL\.scratch\ida\prefix_scan.out", "w", encoding="utf-8") as fp:
    json.dump(rows[:25], fp, ensure_ascii=False, indent=1)
for r in rows[:14]:
    print(r[0], r[1], r[2], "size", r[3], "立即数", list(r[4].keys()))
