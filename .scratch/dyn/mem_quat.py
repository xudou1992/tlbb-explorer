# 只读：找「每骨一条 TRS」的数组——按给定步长扫连续单位四元数。
import ctypes, ctypes.wintypes as w, sys, struct, math
PROCESS_QUERY_INFORMATION, PROCESS_VM_READ = 0x0400, 0x0010
k32=ctypes.WinDLL('kernel32',use_last_error=True)
k32.OpenProcess.restype=w.HANDLE
k32.ReadProcessMemory.argtypes=[w.HANDLE,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_size_t,ctypes.POINTER(ctypes.c_size_t)]
k32.ReadProcessMemory.restype=w.BOOL
pid=int(sys.argv[1]); center=int(sys.argv[2],16); span=int(sys.argv[3]) if len(sys.argv)>3 else 65536
h=k32.OpenProcess(PROCESS_QUERY_INFORMATION|PROCESS_VM_READ,False,pid)
base=center-span; buf=ctypes.create_string_buffer(span*2); got=ctypes.c_size_t(0)
if not k32.ReadProcessMemory(h,ctypes.c_void_p(base),buf,span*2,ctypes.byref(got)):
    print("读失败",ctypes.get_last_error()); sys.exit(2)
d=buf.raw[:got.value]
def unit(o):
    if o+16>len(d): return False
    q=struct.unpack_from("<4f",d,o)
    if any(not math.isfinite(x) or abs(x)>1.2 for x in q): return False
    n=math.sqrt(sum(x*x for x in q))
    return abs(n-1)<0.02
best=[]
for stride in (16,20,32,48,64,80,96,112,128):
    for off in range(0,len(d)-stride*8,4):
        if unit(off) and unit(off+stride) and unit(off+2*stride) and unit(off+3*stride):
            cnt=0
            while unit(off+cnt*stride) and cnt<500: cnt+=1
            best.append((cnt,stride,off))
best.sort(reverse=True)
seen=set(); out=[]
for cnt,stride,off in best:
    k=(stride,off//16)
    if k in seen: continue
    seen.add(k); out.append((cnt,stride,off))
print(f"读 {got.value} 字节；最长连续单位四元数串（前 8）：")
for cnt,stride,off in out[:8]:
    print(f"  +{off:#06x} 步长 {stride:3d}B 连续 {cnt} 条")
