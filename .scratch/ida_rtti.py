# 只读：从 RTTI 名字反查 EsMesh/EsSkeleton 的虚表与成员函数地址。
# 不改名、不注释、不保存 —— 交给 IDA 的 py_exec_file 跑，结果打到它的输出控制台。
import ida_bytes
import ida_name
import idaapi
import idc

BASE = idaapi.get_imagebase()


def u32(ea):
    return ida_bytes.get_dword(ea)


def find_str(needle):
    """在全部段里找一个 ASCII 串，返回它的地址列表。"""
    out = []
    for seg in range(idaapi.get_segm_qty()):
        s = idaapi.getnseg(seg)
        if not s:
            continue
        ea = s.start_ea
        while ea < s.end_ea:
            b = ida_bytes.get_bytes(ea, len(needle))
            if b == needle:
                out.append(ea)
            ea += 1
    return out


def rtti_walk(cls_name):
    """MSVC x64：TypeDescriptor ←CompleteObjectLocator← 虚表最后一格前一格。"""
    td_list = find_str((".{0}@@".format(cls_name)).encode())
    res = []
    for td in td_list:
        td_rva = td - BASE
        for seg in range(idaapi.get_segm_qty()):
            s = idaapi.getnseg(seg)
            ea = s.start_ea
            while ea + 4 <= s.end_ea:
                if u32(ea) == td_rva:
                    # 这里可能是 COL 的 name 字段（COL+0x10 处是 name 的 RVA）
                    col = ea - 0x10
                    col_rva = col - BASE
                    for seg2 in range(idaapi.get_segm_qty()):
                        s2 = idaapi.getnseg(seg2)
                        e2 = s2.start_ea
                        while e2 + 8 <= s2.end_ea:
                            if u32(e2) == col_rva and ida_bytes.get_qword(e2 + 8) != 0:
                                vt = e2 + 8
                                names = []
                                for k in range(24):
                                    fn = ida_bytes.get_qword(vt + 8 * k)
                                    if fn < BASE or fn > BASE + 0x0FFFFFFF:
                                        break
                                    names.append((k, hex(fn), ida_name.get_name(fn) or "?"))
                                res.append({"td": hex(td), "col": hex(col), "vftable": hex(vt), "slots": names})
                            e2 += 4
                            if e2 - s2.start_ea > (s2.end_ea - s2.start_ea) - 8:
                                break
                    break
                ea += 4
                if ea - s.start_ea > (s.end_ea - s.start_ea) - 4:
                    break
    return res


for cls in ("EsSkeleton", "EsMesh"):
    rows = rtti_walk(cls)
    print("=== %s：虚表 %d 张 ===" % (cls, len(rows)))
    for r in rows[:4]:
        print(" vftable", r["vftable"], "COL", r["col"])
        for k, addr, nm in r["slots"]:
            sz = idc.get_func_attr(idc.get_ea_from_func(int(addr, 16)) if False else int(addr, 16), idc.FUNCATTR_SIZE)
            print("   [%2d] %s %s size=%s" % (k, addr, nm, sz))
