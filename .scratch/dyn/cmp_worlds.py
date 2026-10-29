import ctypes, ctypes.wintypes as w, struct, math
PROCESS_QUERY_INFORMATION, PROCESS_VM_READ = 0x0400, 0x0010
k32=ctypes.WinDLL('kernel32',use_last_error=True); k32.OpenProcess.restype=w.HANDLE
k32.ReadProcessMemory.argtypes=[w.HANDLE,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_size_t,ctypes.POINTER(ctypes.c_size_t)]
h=k32.OpenProcess(PROCESS_QUERY_INFORMATION|PROCESS_VM_READ,False,13148)
n=134; buf=ctypes.create_string_buffer(64*n); got=ctypes.c_size_t(0)
k32.ReadProcessMemory(h,ctypes.c_void_p(0x18e953fffe0),buf,64*n,ctypes.byref(got))
eng=[struct.unpack_from("<16f",buf,i*64) for i in range(n)]
ours=[]
for line in open("D:/TLGL/.scratch/dyn/ours_worlds.txt",encoding="utf-8"):
    p=line.rstrip("\n").split("\t")
    if len(p)<2 or p[1]=="NaN": ours.append((p[0],None)); continue
    ours.append((p[0], tuple(float(x) for x in p[1].split())))
def rotang(a,b):
    # 3x3 角度：trace(Ra^T Rb)
    tr=sum(a[r*4+c]*b[r*4+c] for r in range(3) for c in range(3))
    cos=max(-1.0,min(1.0,(tr-1)/2))
    return math.degrees(math.acos(cos))
def dist(a,b): return math.dist(a[12:15],b[12:15])
matched=0; exact=0; names=[]
for i,em in enumerate(eng):
    best=None
    for nm,om in ours:
        if om is None: continue
        d=dist(em,om)
        if d>0.35: continue
        a=rotang(em,om)
        if best is None or a<best[0]: best=(a,d,nm)
    if best and best[0]<2.0 and best[1]<0.01:
        matched+=1; names.append(best[2])
        if best[0]<0.05: exact+=1
print(f"引擎 {n} 条世界矩阵 vs 我们反推的绑定世界：")
print(f"  旋转<2° 且平移<0.01 的 {matched} 条；其中旋转<0.05° 的 {exact} 条")
print("  匹配到的骨名前 8：", names[:8])
# 打印引擎前几条与世界最大的一条，便于人读
print("  引擎首条平移", tuple(round(x,3) for x in eng[0][12:15]))
