p = r'D:\TLGL\.scratch\test_out2.txt'
raw = open(p, 'rb').read()
t = raw.decode('utf-16-le', errors='replace')
if 'cargo' not in t[:300] and 'Compiling' not in t[:500]:
    t = raw.decode('utf-8', errors='replace')
t = t.replace('\x00', '')
lines = t.splitlines()
keep = []
for i, l in enumerate(lines):
    s = l.strip()
    if (s.startswith('test result:') or s.startswith('Running ') or s.startswith('error')
            or s.startswith('test ') and ('FAILED' in s or 'ok' in s)
            or 'panicked' in s or 'assertion' in s or 'expected' in s or 'left:' in s or 'right:' in s
            or 'warning:' in s or s.startswith('-->')):
        keep.append(s)
out = '\n'.join(keep)
open(r'D:\TLGL\.scratch\test_summary4.txt', 'w', encoding='utf-8').write(out[-8000:])
print('total', len(lines), 'kept', len(keep))
