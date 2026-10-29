# 只读：在名表前找「像堆指针」的 qword，跟一层看目标处是否像浮点数组。
import ctypes, ctypes.wintypes as w, sys, struct
PROCESS_QUERY_INFORMATION, PROCESS_VM_READ = 0x0400, 0x0010
k32=ctypes.WinDLL('kernel32',use_last_error=True); k32.OpenProcess.restype=w.HANDLE
k32.ReadProcessMemory.argtypes=[w.HANDLE,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_size_t,ctypes.POINTER(ctypes.c_size_t)]
k32.ReadProcessMemory.restype=w.BOOL
pid=int(sys.argv[1]); names=int(sys.argv[2],16)
h=k32.OpenProcess(PROCESS_QUERY_INFORMATION|PROCESS_VM_READ,False,pid)
def rd(a,n):
    b=ctypes.create_string_buffer(n); got=ctypes.c_size_t(0)
    if not k32.ReadProcessMemory(h,ctypes.c_void_p(a),b,n,ctypes.byref(got)) or got.value<n: return None
    return b.raw[:n]
back=rd(names-256,256)
print("名表前 256 字节里的 qword（找 0x1xx 堆指针）：")
for i in range(0,256,8):
    v=struct.unpack_from("<Q",back,i)[0]
    if 0x10000000000 <= v <= 0x7fffffffffff:
        tgt=rd(v,32)
        if not tgt: 
            print(f"  -0x{256-i:03x} -> {v:#x} 读不到"); continue
        fl=struct.unpack_from("<8f",tgt,0)
        q=struct.unpack_from("<4f",tgt,0)
        n=sum(x*x for x in q)**0.5 if all(abs(x)<2 for x in q) else -1
        print(f"  -0x{256-i:03x} -> {v:#x}  前 8 float: {tuple(round(x,4) for x in fl)}  四元数模长={n:.3f}")
