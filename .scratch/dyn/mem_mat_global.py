# 只读：全局找「连续 64B 正交矩阵」数组（引擎的逐骨矩阵）。
# 旋转部分要求单位正交；平移按行主序/列主序两种槽位都试（游戏世界坐标上千，不能拿 50 卡平移）。
import ctypes, ctypes.wintypes as w, sys, struct, math, time
PROCESS_QUERY_INFORMATION, PROCESS_VM_READ = 0x0400, 0x0010
MEM_COMMIT=0x1000; READABLE={0x02,0x04,0x20,0x40,0x80}
k32=ctypes.WinDLL('kernel32',use_last_error=True); k32.OpenProcess.restype=w.HANDLE
class MBI(ctypes.Structure):
    _fields_=[("BaseAddress",ctypes.c_void_p),("AllocationBase",ctypes.c_void_p),("AllocationProtect",w.DWORD),
              ("RegionSize",ctypes.c_size_t),("State",w.DWORD),("Protect",w.DWORD),("Type",w.DWORD)]
k32.VirtualQueryEx.argtypes=[w.HANDLE,ctypes.c_void_p,ctypes.POINTER(MBI),ctypes.c_size_t]
k32.ReadProcessMemory.argtypes=[w.HANDLE,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_size_t,ctypes.POINTER(ctypes.c_size_t)]
pid=int(sys.argv[1]); MINC=int(sys.argv[2]) if len(sys.argv)>2 else 12
h=k32.OpenProcess(PROCESS_QUERY_INFORMATION|PROCESS_VM_READ,False,pid)
ZERO=1e-3
def ok(o,d):
    if o+64>len(d): return None
    f=struct.unpack_from("<16f",d,o)
    for i in (0,1,2,4,5,6,8,9,10):
        if not math.isfinite(f[i]) or abs(f[i])>50: return None
    rows=[f[0:3],f[4:7],f[8:11]]
    for r in rows:
        if abs(math.sqrt(sum(x*x for x in r))-1)>0.03: return None
    for i in range(3):
        for j in range(i+1,3):
            if abs(sum(rows[i][k]*rows[j][k] for k in range(3)))>0.05: return None
    if f[15]!=1.0: return None
    for x in f[12:15]:
        if not math.isfinite(x) or abs(x)>1e8: return None
    if max(abs(f[3]),abs(f[7]),abs(f[11]))<ZERO: return (f,'row')
    if max(abs(f[12]),abs(f[13]),abs(f[14]))<ZERO:
        return (f,'col')
    return None
def tvec(f,lay):
    return (f[12],f[13],f[14]) if lay=='row' else (f[3],f[7],f[11])
addr=0; found=[]; t0=time.time(); buf=ctypes.create_string_buffer(1<<20)
while True:
    m=MBI()
    if not k32.VirtualQueryEx(h,ctypes.c_void_p(addr),ctypes.byref(m),ctypes.sizeof(m)): break
    base=m.BaseAddress or 0; size=m.RegionSize
    if m.State==MEM_COMMIT and (m.Protect&0xFF) in READABLE and size<=(1<<30):
        off=0
        while off<size:
            chunk=min(1<<20,size-off); got=ctypes.c_size_t(0)
            if k32.ReadProcessMemory(h,ctypes.c_void_p(base+off),buf,chunk,ctypes.byref(got)) and got.value>=256:
                d=buf.raw[:got.value]
                o=0
                while o+64*4<len(d):
                    hit=ok(o,d)
                    if hit:
                        cnt=1
                        while o+cnt*64+64<=len(d) and ok(o+cnt*64,d) and cnt<2000: cnt+=1
                        if cnt>=MINC:
                            run=[ok(o+i*64,d) for i in range(cnt)]
                            lay=run[0][1]
                            ts=[tvec(r[0],r[1]) for r in run]
                            span=max(max(abs(a-b) for a,b in zip(ts[0],ts[-1])),0)
                            uniq=len(set(tuple(round(v,3) for v in t) for t in ts))
                            found.append((cnt,base+off+o,lay,ts[0],ts[-1],span,uniq))
                        o+=cnt*64
                    else: o+=4
            off+=chunk
        if time.time()-t0>300: break
    addr=base+size
    if addr==0: break
found.sort(key=lambda x:-x[0])
print(f"scan {time.time()-t0:.0f}s; arrays>={MINC}: {len(found)}")
for cnt,at,lay,t0v,t1v,span,uniq in found[:40]:
    print(f"  {at:#x} count={cnt} lay={lay} uniq_t={uniq} span={span:.1f} t0=({t0v[0]:.1f},{t0v[1]:.1f},{t0v[2]:.1f}) tN=({t1v[0]:.1f},{t1v[1]:.1f},{t1v[2]:.1f})")
