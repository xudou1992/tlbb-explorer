import re, collections, idautils, idc, ida_bytes, ida_segment, math

out = []
w = out.append

# ---------- 1. PE section / protection analysis ----------
w('==== PE SECTIONS ====',)
nt = ida_segment.get_ui_first_nseg() if False else None
for s in idautils.Segments():
    name = idc.get_segm_name(s)
    end = idc.get_segm_end(s)
    sz = end - s
    perm = ida_bytes.get_segments() and ida_segment.get_segm_perm(s)
    cls = idc.get_segm_class(s)
    nfn = sum(1 for _ in idautils.Functions(s, end))
    # entropy of first 256KB
    take = min(sz, 0x40000)
    b = ida_bytes.get_bytes(s, take) or b''
    if b:
        cnt = collections.Counter(b)
        n = len(b)
        ent = -sum((v / n) * math.log2(v / n) for v in cnt.values())
    else:
        ent = 0.0
    w('SEG %-10s %016X-%016X size=0x%-9x perm=%s class=%-8s entropy=%.2f funcs=%d'
      % (name, s, end, sz, format(perm, 'o'), cls, ent, nfn))

# ---------- 2. RTTI namespace map ----------
rtti = []
for st in idautils.Strings():
    x = str(st)
    if x.startswith('.?AV') or x.startswith('.?AU'):
        rtti.append(x[4:].rstrip('@'))


def pretty(n):
    # crude demangle: strip template guts, convert @ to ::
    depth = 0
    res = []
    for ch in n:
        if ch == '<':
            depth += 1
        if ch == '>':
            depth -= 1
        if ch == '@' and depth == 0:
            res.append('::')
        elif depth == 0:
            res.append(ch)
    s = ''.join(res)
    s = re.sub(r'\?\$[A-Za-z0-9_]+', '', s)
    s = re.sub(r'::+', '::', s)
    return s.strip(':')


pf = [pretty(r) for r in rtti]


def outer(n):
    p = [x for x in n.split('::') if x]
    return p[0] if len(p) > 1 else '<global>'


c = collections.Counter(outer(n) for n in pf)
w('')
w('==== RTTI outer namespace histogram (total %d classes) ====' % len(pf))
for k, v in c.most_common(50):
    w('%6d  %s' % (v, k))

w('')
w('==== classes per interesting namespace ====')
by = collections.defaultdict(list)
for n in pf:
    o = outer(n)
    p = [x for x in n.split('::') if x]
    if len(p) > 1 and '::' not in p[-1]:
        by[o].append(p[-1])
targets = sorted(by, key=lambda k: -len(by[k]))[:26]
for ns in targets:
    uniq = sorted(set(by[ns]))
    w('[%s] n=%d' % (ns, len(uniq)))
    w('    ' + ', '.join(uniq[:40]))

open(r'D:\TLGL\.scratch\arch_out.txt', 'w', encoding='utf-8').write('\n'.join(out))
print('WROTE', len(out), 'lines ->D:\\TLGL\\.scratch\\arch_out.txt')
