# 只读：在给定地址附近找「每根骨一条矩阵」的数组。判据=左上 3×3 近似正交（行/列模长≈1、互相点积≈0）。
import ctypes, ctypes.wintypes as w, sys, struct, math
PROCESS_QUERY_INFORMATION, PROCESS_VM_READ = 0x0400, 0x0010
k32 = ctypes.WinDLL('kernel32', use_last_error=True)
k32.OpenProcess.restype = w.HANDLE
k32.ReadProcessMemory.argtypes=[w.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
k32.ReadProcessMemory.restype = w.BOOL
pid=int(sys.argv[1]); center=int(sys.argv[2],16); span=int(sys.argv[3]) if len(sys.argv)>3 else 8192
h=k32.OpenProcess(PROCESS_QUERY_INFORMATION|PROCESS_VM_READ, False, pid)
if not h: print("打不开", ctypes.get_last_error()); sys.exit(2)
base=center-span
buf=ctypes.create_string_buffer(span*2); got=ctypes.c_size_t(0)
if not k32.ReadProcessMemory(h, ctypes.c_void_p(base), buf, span*2, ctypes.byref(got)):
    print("读失败", ctypes.get_last_error()); sys.exit(2)
d=buf.raw[:got.value]
def ortho(o):
    try: f=struct.unpack_from("<9f", d, o)
    except struct.error: return None
    if any(not math.isfinite(x) or abs(x)>4 for x in f): return None
    rows=[f[0:3],f[3:6],f[6:9]]
    for r in rows:
        n=math.sqrt(sum(x*x for x in r))
        if abs(n-1)>0.05: return None
    for i in range(3):
        for j in range(i+1,3):
            if abs(sum(rows[i][k]*rows[j][k] for k in range(3)))>0.08: return None
    return rows
# 找连续多条 64B 记录都正交的起点
runs=[]
for off in range(0, len(d)-64*3, 4):
    if ortho(off) and ortho(off+64) and ortho(off+128):
        runs.append(off)
# 合并相邻起点
merged=[]
for o in runs:
    if merged and o-merged[-1]<=8: continue
    merged.append(o)
print(f"读 {got.value} 字节；疑似矩阵数组起点 {len(merged)} 处（相对 {hex(base)}）")
for o in merged[:6]:
    cnt=0
    while ortho(o+cnt*64) and cnt<400: cnt+=1
    t=struct.unpack_from("<3f", d, o+48)
    print(f"  +{o:#06x} 连 {cnt} 条 64B 记录；首条平移 {tuple(round(x,3) for x in t)}")
