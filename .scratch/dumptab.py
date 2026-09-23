import ida_bytes, struct
data = ida_bytes.get_bytes(0x140DC8F90, 4096*4)
open(r'D:\TLGL\.scratch\table.bin','wb').write(data)
print('wrote', len(data), 'first8=', struct.unpack('<8I', data[:32]))
