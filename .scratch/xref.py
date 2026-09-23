import re, collections, idautils, idc, ida_name

out = []
w = out.append

entries = []
for st in idautils.Strings():
    entries.append((st.ea, str(st)))

w('strings %d' % len(entries))

byea = dict(entries)

groups = collections.defaultdict(list)
for ea, s in entries:
    if s.startswith('LuaGlobal_'):
        groups['LuaGlobal_*'].append((ea, s))
    elif s.startswith('LuaScriptFunc::'):
        groups['LuaScriptFunc::*'].append((ea, s))
    elif s.startswith('Lua'):
        groups['Lua*'].append((ea, s))
    elif s.startswith('NEP2_'):
        groups['NEP2_*'].append((ea, s))


def nxref(ea, lim=6):
    xr = list(idautils.XrefsTo(ea))
    # also check pointer references: data pointing at string, then xrefs to that pointer
    return xr


w('')
for g in groups:
    items = groups[g]
    withx = 0
    code = 0
    for ea, s in items:
        xr = list(idautils.XrefsTo(ea))
        if xr:
            withx += 1
            if any(idc.is_code(f.from) for f in xr):
                code += 1
    w('GROUP %s: n=%d  direct_xref=%d  from_code=%d' % (g, len(items), withx, code))
    # sample where xrefs come from
    shown = 0
    for ea, s in items:
        xr = list(idautils.XrefsTo(ea))
        if xr and shown < 6:
            f = xr[0]
            fn = idc.get_func_name(f.from)
            w('    %s  ea=%X  xref@%X in %s' % (s[:40], ea, f.from, fn))
            shown += 1

# indirect: find pointers to these strings in .rdata, then xrefs to those pointer slots
w('')
w('--- indirect (pointer -> string) resolution ---')
seg_end = idc.get_segm_end(0x140cabd48)
ptrmap = collections.defaultdict(list)
ea = 0x140cabd48
while ea < seg_end:
    v = idc.get_qword(ea)
    if v in byea:
        ptrmap[byea[v]].append(ea)
    ea += 8
w('rdata qword-scan done; pointered strings: %d' % len(ptrmap))

w('')
w('==== LuaGlobal_* (%d) ====' % len(groups['LuaGlobal_*']))
for ea, s in sorted(groups['LuaGlobal_*'], key=lambda t: t[1]):
    xr = list(idautils.XrefsTo(ea)) + [x for p in ptrmap.get(s, []) for x in idautils.XrefsTo(p)]
    fr = idc.get_func_name(xr[0].from) if xr else '-'
    w('  %-42s  %s' % (s, fr))

open(r'D:\TLGL\.scratch\xref_out.txt', 'w', encoding='utf-8').write('\n'.join(out))
print('WROTE ->xref_out.txt')
