import idaapi, idautils, idc, ida_funcs, ida_name
out=open(r"D:\TLGL\.scratch\ida\magics_out.txt","w",encoding="utf-8")
def w(*a): print(*a,file=out,flush=True)
for s in idautils.Strings():
    t=str(s)
    if t in ("JBCF","JBPU","JMT1","JBCF") or "JBCF" in t or "JMT" in t:
        w(repr(t), hex(s.ea))
out.close(); idc.qexit(0)
