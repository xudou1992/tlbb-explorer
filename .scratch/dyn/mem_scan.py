# 只读扫描：OpenProcess(PROCESS_VM_READ) + VirtualQueryEx + ReadProcessMemory。
# 不注入、不挂钩、不写内存、不改线程。只找 ASCII 标记，报告地址。
import ctypes, ctypes.wintypes as w, sys, time

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
MEM_COMMIT = 0x1000
PAGE_READABLE = {0x02, 0x04, 0x20, 0x40, 0x80}  # R/RW/EXECUTE_READ/READWRITE...

k32 = ctypes.WinDLL('kernel32', use_last_error=True)
class MBI(ctypes.Structure):
    _fields_ = [("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p),
                ("AllocationProtect", w.DWORD), ("RegionSize", ctypes.c_size_t),
                ("State", w.DWORD), ("Protect", w.DWORD), ("Type", w.DWORD)]
k32.OpenProcess.restype = w.HANDLE
k32.VirtualQueryEx.argtypes = [w.HANDLE, ctypes.c_void_p, ctypes.POINTER(MBI), ctypes.c_size_t]
k32.VirtualQueryEx.restype = ctypes.c_size_t
k32.ReadProcessMemory.argtypes = [w.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
k32.ReadProcessMemory.restype = w.BOOL

pid = int(sys.argv[1])
pat = sys.argv[2].encode() if len(sys.argv) > 2 else b"bip01_pelvis"
h = k32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
if not h:
    print("OpenProcess 失败，err", ctypes.get_last_error()); sys.exit(2)
print("已打开 PID", pid, "（只读句柄）")

addr = 0
hits = []
t0 = time.time()
buf = ctypes.create_string_buffer(1 << 20)
while True:
    mbi = MBI()
    if not k32.VirtualQueryEx(h, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)):
        break
    base = mbi.BaseAddress or 0
    size = mbi.RegionSize
    if mbi.State == MEM_COMMIT and (mbi.Protect & 0xFF) in PAGE_READABLE and size <= (1 << 30):
        off = 0
        while off < size:
            chunk = min(1 << 20, size - off)
            got = ctypes.c_size_t(0)
            if k32.ReadProcessMemory(h, ctypes.c_void_p(base + off), buf, chunk, ctypes.byref(got)) and got.value:
                data = buf.raw[:got.value]
                p = data.find(pat)
                while p != -1 and len(hits) < 40:
                    hits.append(base + off + p)
                    p = data.find(pat, p + 1)
            off += chunk
        if len(hits) >= 40:
            break
        if time.time() - t0 > 240:
            print("（240 秒到，提前收工）"); break
    addr = base + size
    if addr == 0:
        break
print("命中", len(hits), "处；用时 %.1fs" % (time.time() - t0))
for a in hits[:12]:
    print("  ", hex(a))
