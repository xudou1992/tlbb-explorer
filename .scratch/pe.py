import re, collections, idautils, idc, ida_bytes, ida_segment, ida_name, math

out = []
w = out.append

# ---------- PE sections ----------
w('==== SEGMENTS ====')
for s in idautils.Segments():
    name = idc.get_segm_name(s)
    end = idc.get_segm_end(s)
    sz = end - s
    try:
        si = ida_segment.getseg(s)
        perm = 'r%s%s%s' % ('w' if si.perm & ida_segment.NM_PERM_WRITABLE else '',
                            'x' if si.perm & ida_segment.NM_PERM_EXECUTABLE else '',
                            'r' if si.perm & ida_segment.NM_PERM_READABLE else '')
    except Exception as e:
        perm = '?'
    nfn = sum(1 for _ in idautils.Functions(s, end))
    take = min(sz, 0x40000)
    b = ida_bytes.get_bytes(s, take) or b''
    ent = 0.0
    if b:
        cnt = collections.Counter(b)
        n = len(b)
        ent = -sum((v / n) * math.log2(v / n) for v in cnt.values())
    w('%-10s %016X-%016X size=0x%-9x perm=%-3s entropy=%.2f funcs=%d' % (name, s, end, sz, perm, ent, nfn))

# ---------- NEP2 api-name table extent ----------
w('')
w('==== NEP2 name table ====')
rdata = ida_segment.getseg(idc.get_segm_by_name('.rdata')).end_ea
rs = ida_segment.getseg(idc.get_segm_by_name('.rdata')).start_ea
blob = ida_bytes.get_bytes(rs, rdata - rs) or b''
idxs = [m.start() for m in re.finditer(b'NEP2_', blob)]
w('NEP2_ occurrences in .rdata: %d, span 0x%X..0x%X' % (len(idxs), rs + min(idxs), rs + max(idxs)))
names = sorted(set(re.findall(rb'NEP2_[A-Za-z0-9_]{2,40}', blob)))
w('unique NEP2 symbols: %d' % len(names))
w(', '.join(n.decode() for n in names))

# ---------- other SDK name tables in .rdata ----------
w('')
w('==== other vendor symbol tables in .rdata ====')
for pat in [rb'LuaGlobal_[A-Za-z0-9_]{2,40}', rb'YiDun[A-Za-z0-9_]{2,40}', rb'CEF[A-Za-z0-9_]{2,40}',
            rb'Cef[A-Za-z0-9_]{2,40}', rb'TMG[A-Za-z0-9_]{2,40}', rb'ags[A-Za-z0-9_]{3,40}',
            rb'AGS[A-Za-z0-9_]{3,40}']:
    u = sorted(set(re.findall(pat, blob)))
    w('[%s] unique=%d' % (pat.decode(), len(u)))
    w('   ' + ', '.join(x.decode() for x in u[:60]))

open(r'D:\TLGL\.scratch\pe_out.txt', 'w', encoding='utf-8').write('\n'.join(out))
print('WROTE ->D:\\TLGL\\.scratch\\pe_out.txt')
