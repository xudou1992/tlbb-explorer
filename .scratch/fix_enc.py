import sys
p = r'D:\TLGL\.scratch\extract_out.txt'
raw = open(p, 'rb').read()
try:
    t = raw.decode('utf-16-le', errors='replace')
except Exception:
    t = raw.decode('utf-8', errors='replace')
if t.count('\x00') > len(t) // 3:
    t = raw.decode('utf-16-le', errors='replace')
    t = t.replace('\x00', '')
lines = [l for l in t.splitlines() if 'lines_total' in l or 'Running ' in l or 'test result' in l or 'FAILED' in l or 'error[' in l]
open(r'D:\TLGL\.scratch\test_summary2.txt', 'w', encoding='utf-8').write('\n'.join(lines))
print('kept', len(lines))
