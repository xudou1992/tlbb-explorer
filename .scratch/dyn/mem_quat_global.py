# 只读：全内存找「连续单位四元数」长串（步长 16/32），这是逐骨旋转数组的特征。
import ctypes, ctypes.wintypes as w, sys, struct, math, time
PROCESS_QUERY_INFORMATION, PROCESS_VM_READ = 0x0400, 0x0010
MEM_COMMIT=0x1000; READABLE={0x02,0x04,0x20,0x40,0x80}
k32=ctypes.WinDLL('kernel32',use_last_error=True); k32.OpenProcess.restype=w.HANDLE
class MBI(ctypes.Structure):
    _fields_=[("BaseAddress",ctypes.c_void_p),("AllocationBase",ctypes.c_void_p),("AllocationProtect",w.DWORD),
              ("RegionSize",ctypes.c_size_t),("State",w.DWORD),("Protect",w.DWORD),("Type",w.DWORD)]
k32.VirtualQueryEx.argtypes=[w.HANDLE,ctypes.c_void_p,ctypes.POINTER(MBI),ctypes.c_size_t]
k32.ReadProcessMemory.argtypes=[w.HANDLE,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_size_t,ctypes.POINTER(ctypes.c_size_t)]
pid=int(sys.argv[1]); minrun=int(sys.argv[2]) if len(sys.argv)>2 else 60
h=k32.OpenProcess(PROCESS_QUERY_INFORMATION|PROCESS_VM_READ,False,pid)
def unit(d,o):
    if o+16>len(d): return False
    q=struct.unpack_from("<4f",d,o)
    for x in q:
        if not math.isfinite(x) or abs(x)>1.2: return False
    return abs(math.sqrt(q[0]*q[0]+q[1]*q[1]+q[2]*q[2]+q[3]*q[3])-1)<0.02
addr=0; best=[]; t0=time.time(); buf=ctypes.create_string_buffer(1<<20)
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
                for stride in (16,32):
                    o=0
                    while o+stride*5<len(d):
                        if unit(d,o) and unit(d,o+stride) and unit(d,o+2*stride) and unit(d,o+3*stride):
                            cnt=4
                            while o+cnt*stride+16<=len(d) and unit(d,o+cnt*stride) and cnt<400: cnt+=1
                            if cnt>=minrun: best.append((cnt,stride,base+off+o))
                            o+=cnt*stride
                        else: o+=4
            off+=chunk
        if time.time()-t0>300: break
    addr=base+size
    if addr==0: break
best.sort(reverse=True)
print(f"扫描 {time.time()-t0:.0f}s；连续单位四元数 ≥{minrun} 的串 {len(best)} 处：")
for cnt,stride,at in best[:8]: print(f"  地址 {at:#x} 步长 {stride} 连续 {cnt} 条")
