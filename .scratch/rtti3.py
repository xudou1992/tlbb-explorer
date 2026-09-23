import re, json, collections
import idautils, idc, ida_nalt, ida_name

lines = []

# 1) collect RTTI strings from string list (works even if IDA didn't name them)
rtti = []
for s in idautils.Strings():
    s = str(s)
    if s.startswith('.?AV'):
        rtti.append(s[4:].rstrip('@'))

lines.append('rtti_count %d' % len(rtti))


def split_name(n):
    # demangled "A::B::Class" or mangled "@Class@NS@@"
    n = n.replace('@', '::')
    n = re.sub(r'::+$', '', n)
    n = re.sub(r'^::+', '', n)
    return n


def top_ns(n):
    parts = [p for p in n.split('::') if p and not p.startswith('?')]
    return parts[0] if len(parts) > 1 else '<global>'


# 2) function-name histogram
fns = []
for ea in idautils.Functions():
    nm = idc.get_func_name(ea)
    if nm:
        fns.append(nm)
lines.append('func_count %d' % len(fns))

c = collections.Counter(top_ns(split_name(n)) for n in fns)
lines.append('--- top namespace by FUNCTION name ---')
for k, v in c.most_common(45):
    lines.append('%6d  %s' % (v, k))

# 3) RTTI class histogram (richest signal)
c2 = collections.Counter(top_ns(split_name(n)) for n in rtti)
lines.append('--- top namespace by RTTI class ---')
for k, v in c2.most_common(60):
    lines.append('%6d  %s' % (v, k))

# 4) samples from biggest clusters
big = [k for k, _ in c2.most_common(14)]
lines.append('--- samples ---')
for b in big:
    ex = [split_name(n) for n in rtti if top_ns(split_name(n)) == b]
    lines.append('[%s] n=%d :: %s' % (b, len(ex), ' | '.join(sorted(set(ex))[:12])))

open(r'D:\TLGL\.scratch\rtti_out.txt', 'w', encoding='utf-8').write('\n'.join(lines))
print('WROTE %d lines' % len(lines))
