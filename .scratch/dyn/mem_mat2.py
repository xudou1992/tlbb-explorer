# 只读：放宽步长找逐骨矩阵数组，目标是 32/39/42/45 条那种（与内存里已加载的 .ani 骨数对上）。
import ctypes, ctypes.wintypes as w, sys, struct, math, time
PROCESS_QUERY_INFORMATION, PROCESS_VM_READ = 0x0400, 0x0010
MEM_COMMIT=0x1000; READABLE={0x02,0x04,0x20,0x40,0x80}
k32=ctypes.WinDLL('kernel32',use_last_error=True); k32.OpenProcess.restype=w.HANDLE
class MBI(ctypes.Structure):
    _fields_=[("BaseAddress",ctypes.c_void_p),("AllocationBase",ctypes.c_void_p),("AllocationProtect",w.DWORD),
              ("RegionSize",ctypes.c_size_t),("State",w.DWORD),("Protect",w.DWORD),("Type",w.DWORD)]
k32.VirtualQueryEx.argtypes=[w.HANDLE,ctypes.c_void_p,ctypes.POINTER(MBI),ctypes.c_size_t]
k32.ReadProcessMemory.argtypes=[w.HANDLE,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_size_t,ctypes.POINTER(ctypes.c_size_t)]
pid=int(sys.argv[1]); h=k32.OpenProcess(PROCESS_QUERY_INFORMATION|PROCESS_VM_READ,False,pid)
def ok(d,o,stride):
    if o+stride>len(d): return False
    f=struct.unpack_from("<12f",d,o)
    for x in f:
        if not math.isfinite(x) or abs(x)>100: return False
    rows=[f[0:3],f[4:7],f[8:11]]
    for r in rows:
        n=math.sqrt(sum(x*x for x in r))
        if abs(n-1)>0.02: return False
    for i in range(3):
        for j in range(i+1,3):
            if abs(sum(rows[i][k]*rows[j][k] for k in range(3)))>0.03: return False
    return True
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
                for stride in (48,64,80):
                    o=0
                    while o+stride*4<len(d):
                        if ok(d,o,stride) and ok(d,o+stride,stride) and ok(d,o+2*stride,stride):
                            cnt=3
                            while o+cnt*stride+12<=len(d) and ok(d,o+cnt*stride,stride) and cnt<600: cnt+=1
                            if 20<=cnt<=60: found.append((cnt,stride,base+off+o))
                            o+=cnt*stride
                        else: o+=4
            off+=chunk
        if time.time()-t0>240: break
    addr=base+size
    if addr==0: break
found.sort(reverse=True)
print(f"扫描 {time.time()-t0:.0f}s；20~60 条的矩阵数组 {len(found)} 处（按条数）：")
for cnt,stride,at in found[:14]: print(f"  {at:#x} 步长 {stride} 连续 {cnt}")
