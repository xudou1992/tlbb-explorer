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
    ours.append((p[0], None if len(p)<2 or p[1]=="NaN" else tuple(float(x) for x in p[1].split())))
def rotang(a,b):
    tr=sum(a[r*4+c]*b[r*4+c] for r in range(3) for c in range(3))
    return math.degrees(math.acos(max(-1.0,min(1.0,(tr-1)/2))))
def transposed(m):
    return (m[0],m[4],m[8],m[12], m[1],m[5],m[9],m[13], m[2],m[6],m[10],m[14], m[3],m[7],m[11],m[15])
for tag, prep in (("原样", lambda m:m), ("转置", transposed)):
    bests=[]
    for i,em in enumerate(eng):
        b=min((rotang(prep(em),om) for nm,om in ours if om), default=999)
        bests.append(b)
    bests.sort()
    print(f"{tag}: 世界矩阵逐条最佳旋转差 中位 {bests[len(bests)//2]:.2f}° · 前 10 条最小 {[round(x,2) for x in bests[:10]]} · <5° 的 {sum(1 for x in bests if x<5)}/{len(bests)}")
# 也试「我们的局部旋转」对引擎（若引擎存的是局部）
locals_=[]
