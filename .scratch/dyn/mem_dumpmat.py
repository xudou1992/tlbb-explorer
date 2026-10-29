import ctypes, ctypes.wintypes as w, sys, struct, math
PROCESS_QUERY_INFORMATION, PROCESS_VM_READ = 0x0400, 0x0010
k32=ctypes.WinDLL('kernel32',use_last_error=True); k32.OpenProcess.restype=w.HANDLE
k32.ReadProcessMemory.argtypes=[w.HANDLE,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_size_t,ctypes.POINTER(ctypes.c_size_t)]
pid=int(sys.argv[1]); at=int(sys.argv[2],16); n=int(sys.argv[3])
h=k32.OpenProcess(PROCESS_QUERY_INFORMATION|PROCESS_VM_READ,False,pid)
buf=ctypes.create_string_buffer(64*n); got=ctypes.c_size_t(0)
k32.ReadProcessMemory(h,ctypes.c_void_p(at),buf,64*n,ctypes.byref(got))
ms=[struct.unpack_from("<16f",buf,i*64) for i in range(got.value//64)]
print("条数",len(ms))
tr=[(m[12],m[13],m[14]) for m in ms]
mag=[math.sqrt(x*x+y*y+z*z) for x,y,z in tr]
print("平移模长：min %.3f 中位 %.3f max %.3f"%(min(mag),sorted(mag)[len(mag)//2],max(mag)))
print("前 6 条平移：",[tuple(round(v,3) for v in t) for t in tr[:6]])
print("第 4 行(底部行)样例：",[tuple(round(m[3],3) for m in ms[:2]), tuple(round(m[7],3) for m in ms[:2]), tuple(round(m[11],3) for m in ms[:2]), tuple(round(m[15],3) for m in ms[:2])])
