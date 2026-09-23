import idautils, idc, ida_bytes, ida_segment, ida_name, idaentry, idaapi

out = []
w = out.append

# delay-load helper present?
for nm in ['__delayLoadHelper2', '_tailMerge_d3d11_dll', '_tailMerge_dxgi_dll',
           '_tailMerge_NEP2_64_dll', '__tailMerge_esent_dll', 'crypto_ll_get_table']:
    ea = idc.get_name_ea_simple(nm)
    w('name %-26s %s' % (nm, '%016X' % ea if ea != idc.BADADDR else '-'))
c = 0
for ea in idautils.Functions():
    n = idc.get_func_name(ea)
    if 'tailMerge' in n or 'delayLoad' in n:
        c += 1
        if c < 25:
            w('  delay %016X %s' % (ea, n))
w('total tailMerge/delayLoad funcs: %d' % c)

# dump the table at 0x1411e1780 as ImgDelayDescr (attributes, rvaDLLName, rvaIAT, rvaINT, rvaUnload, rvaDLLNameString)
w('')
w('=== table @0x1411E1780, 0x14 stride ===')
a = 0x1411E1780
for i in range(18):
    q = [ida_bytes.get_dword(a + k * 4) for k in range(5)]
    dname = ida_bytes.get_qword(a + 8)
    s1 = idc.get_strlit_contents(q[1] + 0x140000000 if q[1] < 0x2000000 else q[1], -1, 0)
    w('  %016X  f0=%08X nameRVA=%08X(%s) iat=%08X int=%08X hmod=%08X' %
      (a, q[0], q[1], (s1 or b'?').decode('latin1'), q[2], q[3], q[4]))
    a += 0x14

# raw bytes of .pdata head to judge structure
w('')
w('=== .pdata first 64 bytes ===')
pd = idc.get_segm_by_name('.pdata')
for s in idautils.Segments():
    if idc.get_segm_name(s) == '.pdata':
        st = ida_segment.getseg(s).start_ea
        w('  start %016X' % st)
        w('  ' + ' '.join('%02x' % b for b in (ida_bytes.get_bytes(st, 64) or b'')))
        break
w('=== .200/.201 first 48 bytes ===')
for nm in ['.200', '.201']:
    for s in idautils.Segments():
        if idc.get_segm_name(s) == nm:
            st = ida_segment.getseg(s).start_ea
            w('  %s %016X  %s' % (nm, st, ' '.join('%02x' % b for b in (ida_bytes.get_bytes(st, 48) or b''))))

open(r'D:\TLGL\.scratch\v7_out.txt', 'w', encoding='utf-8').write('\n'.join(out))
print('WROTE ->v7_out.txt')
