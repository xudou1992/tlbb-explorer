import idaapi, idautils, idc, ida_funcs, ida_name
out=open(r"D:\TLGL\.scratch\ida\magicimm_out.txt","w",encoding="utf-8")
def w(*a): print(*a,file=out,flush=True)
def scan(target, label):
    hits=0
    for fb in idautils.Functions():
        f=ida_funcs.get_func(fb)
        if not f or (f.end_ea-f.start_ea)>30000: continue
        ea=f.start_ea
        while ea < f.end_ea:
            if idc.get_wide_dword(ea)==target:
                w("%s @%s %s" % (label, hex(ea), ida_name.get_name(f.start_ea) or ""))
                hits+=1
                if hits>10: return
            ea+=4
    w("%s 命中 %d" % (label, hits))
scan(0x4643424A, "JBCF")
scan(0x4255504A, "JBPU")
scan(0x31544D4A, "JMT1")
out.close(); idc.qexit(0)
