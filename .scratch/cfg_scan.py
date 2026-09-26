import struct, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
raw = open('D:/TLGL/.scratch/out/tree/ResourcePath.cfg', 'rb').read()
n4 = len(raw) // 4
u = struct.unpack('<%dI' % n4, raw[:n4*4])
print('hdr:', u[:16])
print('file:', len(raw))
# chain scan: descriptor j at even u-index m: u[m]=off, u[m+1]=len, next off == off+len
best_s = best_c = 0
cur_s = cur_c = 0
for m in range(0, n4-2, 2):
    if u[m+2] == u[m] + u[m+1] and 0 < u[m+1] < 4096 and u[m] < 12_000_000:
        if cur_c == 0: cur_s = m
        cur_c += 1
    else:
        if cur_c > best_c: best_s, best_c = cur_s, cur_c
        cur_c = 0
if cur_c > best_c: best_s, best_c = cur_s, cur_c
print(f'longest chain: u-index {best_s} (byte {best_s*4}) count {best_c} (+1 descriptors = {best_c+1})')
STRTAB_OFF = best_s * 4
NS = best_c + 1
print('NS =', NS, ' STRTAB_OFF =', STRTAB_OFF)
N36 = (STRTAB_OFF - 64) / 36
print('records if 36B from 64:', N36)
BLOB = STRTAB_OFF + 8 * NS
a0, l0 = u[best_s], u[best_s+1]
print('first desc:', a0, l0, ' blob candidate @', BLOB, ' blob len:', len(raw)-BLOB)
print('first string try:', raw[BLOB+a0 : BLOB+a0+min(l0,80)])
