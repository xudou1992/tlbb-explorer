import idc, ida_bytes, ida_funcs
out = open(r'D:/TLGL/.scratch/ida/mesh_magic_out.txt', 'w', encoding='utf-8')
for name, pat in [('copyright', b'Copyright 2013'), ('copy', b'Copy')]:
    ea = 0x140001000
    hits = []
    mask = bytes([0xFF] * len(pat))
    for _ in range(40):
        r = ida_bytes.bin_search(ea, 0x140000000 + 0x1400000, pat, mask, len(pat), ida_bytes.BIN_SEARCH_FORWARD)
        if r is None:
            break
        ea = r[0]
        f = ida_funcs.get_func(ea)
        hits.append((ea, f.start_ea if f else 0))
        ea += 1
    out.write('%s %d\n' % (name, len(hits)))
    for e, fn in hits:
        out.write('  %x func=%x\n' % (e, fn))
out.close()
idc.qexit(0)
