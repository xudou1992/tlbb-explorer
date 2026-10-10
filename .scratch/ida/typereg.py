"""列类型注册表：谁调 sub_1402E0480(名字, 长度, hash)，注册到哪个全局，
全局指向的描述符里哪些字段是代码指针（= 该类资源的装载/处理函数）。
"""
import ida_bytes, ida_funcs, ida_name, idautils, idc, json

REG = 0x1402E0480
TEXT_LO, TEXT_HI = 0x140001000, 0x141000000

def code_name(p):
    if TEXT_LO <= p < TEXT_HI:
        f = ida_funcs.get_func(p)
        return hex(p) + ("=" + idc.get_func_name(f.start_ea) if f else "")
    return None

rows = []
for xr in idautils.XrefsTo(REG, 0):
    site = xr.frm
    fn = ida_funcs.get_func(site)
    if not fn:
        continue
    # 找这条调用之前最近的一条 lea rcx/rdx/r8, offset xxx  (名字串) 与全局写入
    name = None
    head = site
    for _ in range(60):
        head = idc.prev_head(head, fn.start_ea)
        if head == idc.BADADDR or head < fn.start_ea:
            break
        mnem = idc.print_insn_mnem(head)
        if mnem == "lea":
            op = idc.print_operand(head, 1)
            if op.startswith("offset ") or op.startswith("a"):
                s = idc.get_strlit_contents(idc.get_operand_value(head, 1), -1, 0)
                if s and len(s) < 40:
                    name = s.decode("utf-8", "replace")
                    break
    # 这个 init 函数最后把结果写进哪个全局
    tgt = None
    try:
        for h in idautils.Heads(fn.start_ea, fn.end_ea):
            if idc.print_insn_mnem(h) == "mov" and idc.print_operand(h, 0).startswith("qword_"):
                tgt = idc.get_operand_value(h, 0)
    except Exception as e:
        print('扫描函数失败', hex(site), e)
    desc = []
    if tgt:
        p = ida_bytes.get_qword(tgt) if tgt else 0
        for i in range(8):
            v = ida_bytes.get_qword(p + 8 * i) if p else 0
            cn = code_name(v)
            if cn:
                desc.append((i, cn))
    rows.append((name, hex(tgt) if tgt else "?", hex(p) if tgt and 'p' in dir() and p else "?", desc[:6]))

rows.sort(key=lambda r: (r[0] or ""))
with open(r"D:\TLGL\.scratch\ida\typereg.out", "w", encoding="utf-8") as fp:
    json.dump(rows, fp, ensure_ascii=False, indent=1)
for r in rows:
    print(r[0], "|", r[1], "|", r[3])
