# 只读：全内存扫「谁存了这个地址」（8 字节小端），即骨架对象。
import ctypes, ctypes.wintypes as w, sys, struct, time
PROCESS_QUERY_INFORMATION, PROCESS_VM_READ = 0x0400, 0x0010
MEM_COMMIT=0x1000; READABLE={0x02,0x04,0x20,0x40,0x80}
k32=ctypes.WinDLL('kernel32',use_last_error=True); k32.OpenProcess.restype=w.HANDLE
class MBI(ctypes.Structure):
    _fields_=[("BaseAddress",ctypes.c_void_p),("AllocationBase",ctypes.c_void_p),("AllocationProtect",w.DWORD),
              ("RegionSize",ctypes.c_size_t),("State",w.DWORD),("Protect",w.DWORD),("Type",w.DWORD)]
k32.VirtualQueryEx.argtypes=[w.HANDLE,ctypes.c_void_p,ctypes.POINTER(MBI),ctypes.c_size_t]
k32.ReadProcessMemory.argtypes=[w.HANDLE,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_size_t,ctypes.POINTER(ctypes.c_size_t)]
pid=int(sys.argv[1]); target=int(sys.argv[2],16)
pat=struct.pack("<Q",target)
h=k32.OpenProcess(PROCESS_QUERY_INFORMATION|PROCESS_VM_READ,False,pid)
addr=0; hits=[]; t0=time.time(); buf=ctypes.create_string_buffer(1<<20)
while True:
    m=MBI()
    if not k32.VirtualQueryEx(h,ctypes.c_void_p(addr),ctypes.byref(m),ctypes.sizeof(m)): break
    base=m.BaseAddress or 0; size=m.RegionSize
    if m.State==MEM_COMMIT and (m.Protect&0xFF) in READABLE and size<=(1<<30):
        off=0
        while off<size:
            chunk=min(1<<20,size-off); got=ctypes.c_size_t(0)
            if k32.ReadProcessMemory(h,ctypes.c_void_p(base+off),buf,chunk,ctypes.byref(got)) and got.value:
                data=buf.raw[:got.value]; p=data.find(pat)
                while p!=-1 and len(hits)<30:
                    hits.append(base+off+p); p=data.find(pat,p+1)
            off+=chunk
        if len(hits)>=30 or time.time()-t0>240: break
    addr=base+size
    if addr==0: break
print(f"指向 {target:#x} 的指针 {len(hits)} 处，用时 {time.time()-t0:.0f}s")
for a in hits[:12]: print("  ",hex(a))
