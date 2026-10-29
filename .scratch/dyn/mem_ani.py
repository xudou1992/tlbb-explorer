# 只读：在进程内存里找 .ani 容器头（0x8C 处 MIN2/MIN3，文件头是 Copyright）。
import ctypes, ctypes.wintypes as w, sys, struct, time
PROCESS_QUERY_INFORMATION, PROCESS_VM_READ = 0x0400, 0x0010
MEM_COMMIT=0x1000; READABLE={0x02,0x04,0x20,0x40,0x80}
k32=ctypes.WinDLL('kernel32',use_last_error=True); k32.OpenProcess.restype=w.HANDLE
class MBI(ctypes.Structure):
    _fields_=[("BaseAddress",ctypes.c_void_p),("AllocationBase",ctypes.c_void_p),("AllocationProtect",w.DWORD),
              ("RegionSize",ctypes.c_size_t),("State",w.DWORD),("Protect",w.DWORD),("Type",w.DWORD)]
k32.VirtualQueryEx.argtypes=[w.HANDLE,ctypes.c_void_p,ctypes.POINTER(MBI),ctypes.c_size_t]
k32.ReadProcessMemory.argtypes=[w.HANDLE,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_size_t,ctypes.POINTER(ctypes.c_size_t)]
pid=int(sys.argv[1]); h=k32.OpenProcess(PROCESS_QUERY_INFORMATION|PROCESS_VM_READ,False,pid)
addr=0; hits=[]; t0=time.time(); buf=ctypes.create_string_buffer(1<<20)
while True:
    m=MBI()
    if not k32.VirtualQueryEx(h,ctypes.c_void_p(addr),ctypes.byref(m),ctypes.sizeof(m)): break
    base=m.BaseAddress or 0; size=m.RegionSize
    if m.State==MEM_COMMIT and (m.Protect&0xFF) in READABLE and size<=(1<<30):
        off=0
        while off<size:
            chunk=min(1<<20,size-off); got=ctypes.c_size_t(0)
            if k32.ReadProcessMemory(h,ctypes.c_void_p(base+off),buf,chunk,ctypes.byref(got)) and got.value>160:
                d=buf.raw[:got.value]
                for tag in (b"MIN3",b"MIN2"):
                    p=d.find(tag)
                    while p!=-1:
                        # tag 应在 file+0x8c
                        fo=off+p-0x8c
                        if fo>=0 and d[fo:fo+9]==b"Copyright":
                            bones=struct.unpack_from("<H",d,fo+0xba)[0]
                            frames=struct.unpack_from("<H",d,fo+0xc2)[0]
                            if 1<=bones<=4096 and 1<=frames<=8192:
                                hits.append((base+fo, tag.decode(), bones, frames))
                        p=d.find(tag,p+1)
            off+=chunk
        if time.time()-t0>240: break
    addr=base+size
    if addr==0: break
print(f"扫描 {time.time()-t0:.0f}s；候选 .ani {len(hits)} 条")
for a,tag,b,f in hits[:12]: print(f"  {a:#x} {tag} 骨{b} 帧{f}")
