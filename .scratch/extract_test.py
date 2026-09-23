import sys

p = r'D:\TLGL\.scratch\test_out.txt'
try:
    t = open(p, 'r', encoding='utf-8', errors='replace').read()
except Exception as e:
    print('READ FAIL', e)
    sys.exit(1)

lines = t.splitlines()
keep = []
for l in lines:
    s = l.strip()
    if s.startswith('Running ') or s.startswith('test result:') or 'FAILED' in s or 'panicked' in s or 'error[' in s or s.startswith('warning:'):
        keep.append(s)

out = '\n'.join(keep)
open(r'D:\TLGL\.scratch\test_summary.txt', 'w', encoding='utf-8').write(out)
print('lines_total=%d kept=%d' % (len(lines), len(keep)))
print(out[:4000])
