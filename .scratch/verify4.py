import re, collections, idautils, idc, ida_bytes, ida_segment, ida_name, math

out = []
w = out.append

# ---- locate high-entropy blobs in .text ----
segs = {}
for s in idautils.Segments():
    sg = ida_segment.getseg(s)
    segs.setdefault(sg.name, []).append((sg.start_ea, sg.end_ea, sg.perm))
for n, v in segs.items():
    for a, b, p in v:
        w('SEG %-10s %016X-%016X 0x%-9x perm=%o' % (n, a, b, b - a, p))

w('')
w('=== entropy profile of every segment, 64K windows ===')
for n, v in segs.items():
    for a0, b0, p in v:
        a = a0
        blocks = []
        while a < b0:
            take = min(0x10000, b0 - a)
            bb = ida_bytes.get_bytes(a, take) or b''
            cnt = collections.Counter(bb)
            ent = -sum((x / len(bb)) * math.log2(x / len(bb)) for x in cnt.values()) if bb else 0
            nf = sum(1 for _ in idautils.Functions(a, a + take))
            blocks.append((a, ent, nf))
            a += take
        hi = [x for x in blocks if x[1] > 7.5]
        w('%-10s windows=%d  high-entropy(>7.5)=%d  zero-func-high-ent=%s' %
          (n, len(blocks), len(hi), [ '%016X(%.2f)' % (x[0], x[1]) for x in hi if x[2] == 0 ][:12]))

# ---- entry / TLS ----
w('')
w('=== entry & TLS & init ===')
for nm in ['start', 'TlsCallback_0', 'TlsCallback_1', 'TlsCallback_2', 'DllMain']:
    ea = idc.get_name_ea_simple(nm)
    if ea != idc.BADADDR:
        w('%s = %016X  size=%s' % (nm, ea, idc.get_func_attr(ea, idc.FUNCATTR_END) - ea))
# TLS directory
w('')
w('=== xrefs to TLS callbacks ===')
for nm in ['TlsCallback_0', 'start']:
    ea = idc.get_name_ea_simple(nm)
    if ea != idc.BADADDR:
        for x in list(idautils.XrefsTo(ea))[:10]:
            w('  %s <- %016X (%s)' % (nm, x.frm, idc.get_func_name(x.frm)))

# ---- what calls the NEP2 import thunk ----
w('')
w('=== NEP2 import usage ===')
imp = idc.get_name_ea_simple('__imp_NEP2_64_1')
w('__imp_NEP2_64_1 = %016X' % imp)
xr = list(idautils.XrefsTo(imp))
w('direct xrefs to import slot: %d' % len(xr))
for x in xr[:15]:
    w('   from %016X in %s' % (x.frm, idc.get_func_name(x.frm)))
for nm in ['NEP2_64_1', 'sub_1402DFBA0', 'sub_1402DFA70', 'sub_140135A90', 'sub_140133920']:
    ea = idc.get_name_ea_simple(nm)
    if ea != idc.BADADDR:
        w('ref %s = %016X' % (nm, ea))

open(r'D:\TLGL\.scratch\v4_out.txt', 'w', encoding='utf-8').write('\n'.join(out))
print('WROTE ->v4_out.txt')
