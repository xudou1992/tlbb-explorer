"""Path-template mining: pull format strings and directory literals out of the client binary.

The engine builds most virtual paths at runtime ("ui/icon/skill/%s.tga"), so the template plus a
runtime id/name is the missing half of the naming problem.  This dumps every string that looks
like a path-producing template so it can be expanded against the id/name pools and hash-matched.
"""
import re
import sys
from collections import Counter

EXE = r'D:\TLGL\tlbbgl_x64.exe'
b = open(EXE, 'rb').read()

ASCII = re.compile(rb'[ -~]{5,200}')
GBK = re.compile(rb'[\x20-\x7e\x81-\xfe]{5,200}')

# a template = has %s/%d/%u/%x and either a slash or a file extension
TPL = re.compile(r'%[-+ #0]*[\d.]*[sduxfX]')
EXT = re.compile(r'\.[A-Za-z0-9]{1,8}\b')


def is_path(s):
    if '/' not in s and '\\' not in s and not EXT.search(s):
        return False
    if ' ' in s and '%' not in s:
        return False
    return bool(TPL.search(s))


def main():
    strs = set()
    for m in ASCII.finditer(b):
        strs.add(m.group().decode())
    gbk = set()
    for m in GBK.finditer(b):
        try:
            t = m.group().decode('gbk')
        except UnicodeDecodeError:
            continue
        if all(32 <= ord(c) < 127 or '一' <= c <= '鿿' for c in t):
            gbk.add(t)
    alls = strs | gbk
    tpl = sorted(s for s in alls if is_path(s))
    dirs = sorted(s for s in alls if (('/' in s or '\\' in s) and not TPL.search(s)
                                      and re.fullmatch(r'[\w.+:@\-/\\ ]{3,80}', s)
                                      and (s.endswith(('/', '\\')) or EXT.search(s) or '/' in s)))
    with open(r'D:\TLGL\.scratch\templates.txt', 'w', encoding='utf-8') as o:
        o.write('\n'.join(tpl) + '\n')
    print('exe strings: %d ascii-ish, %d gbk-ish' % (len(strs), len(gbk)))
    print('path templates: %d  -> templates.txt' % len(tpl))
    for t in tpl[:80]:
        print('   ', t)
    print('\npath-looking literals: %d' % len(dirs))
    roots = Counter(re.split(r'[/\\]', d)[0].lower() for d in dirs if re.split(r'[/\\]', d))
    print('top first components:', roots.most_common(30))


if __name__ == '__main__':
    main()
