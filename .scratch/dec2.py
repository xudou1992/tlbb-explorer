p = r'D:\TLGL\.scratch\test_out.txt'
raw = open(p, 'rb').read()
t = raw.decode('utf-16-le', errors='replace')
if 'cargo' not in t[:200]:
    t = raw.decode('utf-8', errors='replace')
t = t.replace('\x00', '')
lines = t.splitlines()
keep = []
for l in lines:
    s = l.strip()
    if (s.startswith('Running ') or s.startswith('test result:') or 'FAILED' in s
            or 'panicked' in s or s.startswith('error[') or s.startswith('error:')
            or 'warning: unused' in s):
        keep.append(s)
out = '\n'.join(keep)
open(r'D:\TLGL\.scratch\test_summary3.txt', 'w', encoding='utf-8').write(out)
print('total_lines', len(lines), 'kept', len(keep))
