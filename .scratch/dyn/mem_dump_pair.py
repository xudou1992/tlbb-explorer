# 只读：把 45 骨 .ani 按闭式算出真实长度后整段读出，并把 45 条矩阵数组一起落盘。
import ctypes, ctypes.wintypes as w, struct, sys
PROCESS_QUERY_INFORMATION, PROCESS_VM_READ = 0x0400, 0x0010
k32=ctypes.WinDLL('kernel32',use_last_error=True); k32.OpenProcess.restype=w.HANDLE
k32.ReadProcessMemory.argtypes=[w.HANDLE,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_size_t,ctypes.POINTER(ctypes.c_size_t)]
pid=int(sys.argv[1]); ani=int(sys.argv[2],16); mat=int(sys.argv[3],16); nmat=int(sys.argv[4])
h=k32.OpenProcess(PROCESS_QUERY_INFORMATION|PROCESS_VM_READ,False,pid)
def rd(a,n):
    b=ctypes.create_string_buffer(n); got=ctypes.c_size_t(0)
    if not k32.ReadProcessMemory(h,ctypes.c_void_p(a),b,n,ctypes.byref(got)) or got.value<n: return None
    return b.raw[:n]
head=rd(ani,0xd2+78*45+4096)
b=struct.unpack_from("<H",head,0xba)[0]; b2=struct.unpack_from("<H",head,0xbe)[0]; fr=struct.unpack_from("<H",head,0xc2)[0]
print("头:", b, b2, fr)
flags_at=0xd2+78*b
cur=flags_at+4*b2
for i in range(b2):
    f=struct.unpack_from("<I",head,cur-4*b2+ (flags_at+(cur-4*b2-flags_at)) ) if False else None
for i in range(b2):
    f=struct.unpack_from("<I",head,flags_at+4*i)[0]
    if f&1:
        step=6 if f&0x800 else 16
        if f&0x10:
            n=struct.unpack_from("<I",head,cur)[0]; cur+=4+n*step
        else: cur+=fr*step
    if f&2:
        if f&0x20:
            n=struct.unpack_from("<I",head,cur)[0]; cur+=4+n*12+(n*2 if f&0x80 else n*4)
        else: cur+=fr*12
    if f&4:
        if f&0x40:
            n=struct.unpack_from("<I",head,cur)[0]; cur+=4+n*4+(n if f&0x80 else n*2)
        else: cur+=fr*4
total=cur
print("闭式总长:", total)
raw=rd(ani,total)
open("D:/TLGL/.scratch/dyn/ani45.bin","wb").write(raw)
print("已落 ani45.bin", len(raw), "tag", raw[0x8c:0x90])
mb=rd(mat,48*nmat)
open("D:/TLGL/.scratch/dyn/mat45.bin","wb").write(mb)
print("已落 mat45.bin", len(mb), "条数", len(mb)//48)
