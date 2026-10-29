# 只读：把给定地址前后一段读出来，按 30 字节名表槽尝试解析骨名。
import ctypes, ctypes.wintypes as w, sys
PROCESS_QUERY_INFORMATION, PROCESS_VM_READ = 0x0400, 0x0010
k32 = ctypes.WinDLL('kernel32', use_last_error=True)
k32.OpenProcess.restype = w.HANDLE
k32.ReadProcessMemory.argtypes = [w.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
k32.ReadProcessMemory.restype = w.BOOL
pid, addr, n = int(sys.argv[1]), int(sys.argv[2], 16), int(sys.argv[3]) if len(sys.argv) > 3 else 2048
h = k32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
if not h: print("OpenProcess 失败", ctypes.get_last_error()); sys.exit(2)
buf = ctypes.create_string_buffer(n); got = ctypes.c_size_t(0)
ok = k32.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, n, ctypes.byref(got))
print("读了", got.value, "字节 ok=", ok)
d = buf.raw[:got.value]
# 打印可打印串（>=4 字节）
import re
for m in re.finditer(rb"[\x20-\x7e]{4,}", d):
    print(f"+{m.start():5d}  {m.group().decode('latin1')}")
