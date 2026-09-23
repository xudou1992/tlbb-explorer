import math, collections, idautils, idc, ida_bytes, ida_segment

out = []
w = out.append

# --- entropy profile of .text in 64KB windows + function density ---
s = idc.get_segm_by_name('.text')
st, en = ida_segment.getseg(s).start_ea, ida_segment.getseg(s).end_ea
w('=== .text 0x%X-0x%X entropy(64K windows) / funcs(64K) ===' % (st, en))
a = st
while a < en:
    take = min(0x10000, en - a)
    b = ida_bytes.get_bytes(a, take) or b''
    cnt = collections.Counter(b)
    ent = -sum((v / len(b)) * math.log2(v / len(b)) for v in cnt.values()) if b else 0
    nf = sum(1 for _ in idautils.Functions(a, a + take))
    w('  %016X ent=%.2f funcs=%d' % (a, ent, nf))
    a += take

# --- function start histogram: where does real code begin ---
w('')
fs = sorted(idautils.Functions())
w('total funcs %d, first %016X, last %016X' % (len(fs), fs[0], fs[-1]))

# --- Lua binding table reachability ---
w('')
w('=== LuaGlobal_* xrefs ===')
n_with = 0
n_tot = 0
samples = []
for st_ in idautils.Strings():
    txt = str(st_)
    if txt.startswith('LuaGlobal_') or txt.startswith('LuaScriptFunc::') or txt.startswith('NEP2_Shadow'):
        n_tot += 1
        xr = list(idautils.XrefsTo(st_.ea))
        if xr:
            n_with += 1
            if len(samples) < 25:
                samples.append('%-38s @%016X <- %016X %s' %
                               (txt, st_.ea, xr[0].from, idc.get_func_name(xr[0].from)))
w('lua/nep name strings: %d, with direct xref: %d' % (n_tot, n_with))
for x in samples:
    w('  ' + x)

# --- how are they used if not xrefed? look for LEA referencing them via search_text on a couple ---
open(r'D:\TLGL\.scratch\v_out.txt', 'w', encoding='utf-8').write('\n'.join(out))
print('WROTE ->v_out.txt')
