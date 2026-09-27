# -*- coding: utf-8 -*-
"""sfl_strings.py — READ-ONLY dump of every JBCF string in all 297 .sfl files.

Outputs:
  sfl_strings_all.txt   every (file, index, len, hash, text) line
  sfl_prop_texts.txt    the long "property dump" strings, de-duplicated, split
  sfl_tex_names.txt     texture-looking strings with per-file counts
"""
import struct, glob, os, re, collections

FILES = sorted(glob.glob(os.path.join(r'D:\TLGL\.scratch\out\tree\mobile_maps', '*', '*.sfl')))
HERE = r'D:\TLGL\.scratch'

def r8(n):
    return n if n % 8 == 0 else n + 8 - (n % 8)

def sdecode(b):
    for enc in ('utf-8', 'gbk'):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            pass
    return b.decode('latin1', 'replace')

def read(f):
    raw = open(f, 'rb').read()
    a = struct.unpack_from('<6I', raw, 0)
    so = r8(a[5]) + 24
    sid, size, flag, cnt = struct.unpack_from('<4I', raw, so)
    assert sid == 85, (f, sid)
    out, p = [], so + 16 + 8 * cnt
    for i in range(cnt):
        ln, hv = struct.unpack_from('<2I', raw, so + 16 + 8 * i)
        out.append((sdecode(raw[p:p + ln]), hv))
        p += ln
    return out

all_lines = open(os.path.join(HERE, 'sfl_strings_all.txt'), 'w', encoding='utf-8')
texcount = collections.Counter()
uniq = collections.Counter()
for f in FILES:
    strs = read(f)
    base = os.path.basename(f)
    for i, (s, hv) in enumerate(strs):
        all_lines.write('%s\t%d\t%d\t0x%08x\t%s\n' % (base, i, len(s), hv, s.replace('\n', '\\n')))
        uniq[s] += 1
        if re.search(r'\.(tga|dds|png|jpg|bmp|cfg|mesh|mtl)$', s, re.I):
            texcount[s] += 1
all_lines.close()

props = [s for s in uniq if re.match(r'^[A-Za-z].*:', s) and '(' in s and len(s) > 12 and not re.search(r'\.\w{3}$', s)]
with open(os.path.join(HERE, 'sfl_prop_texts.txt'), 'w', encoding='utf-8') as g:
    for s in sorted(props):
        g.write('=====%d=====\n%s\n' % (uniq[s], s))

with open(os.path.join(HERE, 'sfl_tex_names.txt'), 'w', encoding='utf-8') as g:
    for s, c in sorted(texcount.items()):
        g.write('%5d  %s\n' % (c, s))

print('files', len(FILES), 'total rows', sum(uniq.values()), 'distinct', len(uniq))
print('name-like (ext suffix) distinct', len(texcount), 'rows', sum(texcount.values()))
print('long property-text strings distinct', len(props))
