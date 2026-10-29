import ctypes, ctypes.wintypes as w, sys, struct
PROCESS_QUERY_INFORMATION, PROCESS_VM_READ = 0x0400, 0x0010
k32=ctypes.WinDLL('kernel32',use_last_error=True); k32.OpenProcess.restype=w.HANDLE
k32.ReadProcessMemory.argtypes=[w.HANDLE,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_size_t,ctypes.POINTER(ctypes.c_size_t)]
pid=int(sys.argv[1]); at=int(sys.argv[2],16); stride=int(sys.argv[3]); n=int(sys.argv[4]); out=sys.argv[5]
h=k32.OpenProcess(PROCESS_QUERY_INFORMATION|PROCESS_VM_READ,False,pid)
buf=ctypes.create_string_buffer(stride*n); got=ctypes.c_size_t(0)
ok=k32.ReadProcessMemory(h,ctypes.c_void_p(at),buf,stride*n,ctypes.byref(got))
q=[]
for i in range(got.value//stride):
    v=struct.unpack_from("<4f",buf,i*stride)
    q.append(v)
with open(out,"w",encoding="utf-8") as f:
    for v in q: f.write("%.6f %.6f %.6f %.6f\n"%v)
print("ok",ok,"条数",len(q),"步长",stride)
