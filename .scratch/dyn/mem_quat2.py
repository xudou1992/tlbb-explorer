# 只读：找「连续单位四元数且**确实在变**」的长串——那才是逐骨旋转数组，不是恒等填充。
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
def q(d,o):
    if o+16>len(d): return None
    v=struct.unpack_from("<4f",d,o)
    for x in v:
        if not math.isfinite(x) or abs(x)>1.2: return None
    n=math.sqrt(sum(x*x for x in v))
    return v if abs(n-1)<0.02 else None
def ang(a,b):
    dot=abs(sum(a[i]*b[i] for i in range(4)))
    return 2*math.acos(min(1.0,dot))
addr=0; found=[]; t0=time.time(); buf=ctypes.create_string_buffer(1<<20)
while True:
    m=MBI()
    if not k32.VirtualQueryEx(h,ctypes.c_void_p(addr),ctypes.byref(m),ctypes.sizeof(m)): break
    base=m.BaseAddress or 0; size=m.RegionSize
    if m.State==MEM_COMMIT and (m.Protect&0xFF) in READABLE and size<=(1<<30):
        off=0
        while off<size:
            chunk=min(1<<20,size-off); got=ctypes.c_size_t(0)
            if k32.ReadProcessMemory(h,ctypes.c_void_p(base+off),buf,chunk,ctypes.byref(got)) and got.value>=64:
                d=buf.raw[:got.value]
                for stride in (16,32,48,64):
                    o=0
                    while o+stride*5<len(d):
                        a0=q(d,o); a1=q(d,o+stride); a2=q(d,o+2*stride); a3=q(d,o+3*stride)
                        if a0 and a1 and a2 and a3:
                            cnt=4; varied=(ang(a0,a1)>0.005) or (ang(a1,a2)>0.005) or (ang(a2,a3)>0.005)
                            while o+cnt*stride+16<=len(d) and q(d,o+cnt*stride) and cnt<2000: cnt+=1
                            if cnt>=40 and varied: found.append((cnt,stride,base+off+o))
                            o+=max(cnt,1)*stride
                        else: o+=4
            off+=chunk
        if time.time()-t0>300: break
    addr=base+size
    if addr==0: break
found.sort(reverse=True)
print(f"扫描 {time.time()-t0:.0f}s；有变化且 ≥40 条的四元数串 {len(found)} 处：")
for cnt,stride,at in found[:10]: print(f"  {at:#x} 步长 {stride} 连续 {cnt}")
