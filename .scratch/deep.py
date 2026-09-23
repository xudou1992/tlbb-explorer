import re, collections
import idautils, idc, ida_nalt, ida_segment, ida_bytes, math

lines = []

rtti = []
for s in idautils.Strings():
    s = str(s)
    if s.startswith('.?AV'):
        rtti.append(s[4:].rstrip('@'))


def demo(n):
    return n.replace('@', '::').rstrip(':')


allc = [demo(n) for n in rtti]

# A) Module / subsystem registry style classes
lines.append('--- classes matching Module/Interface/Manager/System ---')
for pat in [r'Module', r'IScene', r'Mgr$', r'Manager', r'System']:
    hits = sorted({c for c in allc if re.search(pat, c) and c.count('::') <= 3})
    lines.append('[%s] n=%d' % (pat, len(hits)))
    for h in hits[:70]:
        lines.append('   ' + h)

# B) distinct top-level namespaces across full RTTI (any depth token)
tok = collections.Counter()
for c in allc:
    for p in c.split('::'):
        if p and not p.startswith('?') and len(p) > 2 and not p.isdigit():
            tok[p] += 1
lines.append('--- most frequent type tokens ---')
for k, v in tok.most_common(90):
    lines.append('%6d  %s' % (v, k))

# C) section / protection analysis
lines.append('--- segments + entropy ---')
for seg in idautils.Segments():
    name = idc.get_segm_name(seg)
    end = idc.get_segm_end(seg)
    sz = end - seg
    perms = idc.get_segm_attr(seg, idc.SEGATTR_PERM)
    sclass = idc.get_full_segm_class_name(seg) if hasattr(idc, 'get_full_segm_class_name') else ''
    # entropy over first 64KB
    take = min(sz, 0x10000)
    data = ida_bytes.get_bytes(seg, take) or b''
    cnt = collections.Counter(data)
    ent = -sum((v / len(data)) * math.log2(v / len(data)) for v in cnt.values()) if data else 0
    nfunc = sum(1 for f in idautils.Functions(seg, end))
    lines.append('%-10s %016X-%016X size=0x%-9x perm=%s entropy=%.2f funcs=%d' %
                 (name, seg, end, sz, bin(perms), ent, nfunc))

# D) TLS callbacks + entry
lines.append('--- TLS ---')
lines.append(str(list(idautils.TeaInfo()) if hasattr(idautils, 'TeaInfo') else 'n/a'))
for ea in idautils.Functions():
    n = idc.get_func_name(ea)
    if 'Tls' in n or n in ('start', '_mainCRTStartup'):
        lines.append('entry %s %016X' % (n, ea))

open(r'D:\TLGL\.scratch\deep_out.txt', 'w', encoding='utf-8').write('\n'.join(lines))
print('WROTE %d lines' % len(lines))
