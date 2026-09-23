p = r'D:\TLGL\.scratch\test_out5.txt'
raw = open(p, 'rb').read()
t = raw.decode('utf-16-le', errors='replace')
if 'test result' not in t:
    t = raw.decode('utf-8', errors='replace')
t = t.replace('\x00', '')
import re
res = re.findall(r'test result: (ok\. \d+ passed[^\r\n]*|FAILED[^\r\n]*)', t)
total = 0
for r in res:
    m = re.search(r'(\d+) passed', r)
    if m: total += int(m.group(1))
fail = [r for r in res if 'FAILED' in r or 'failed; ' in r and not r.startswith('ok')]
out = 'TOTAL_PASSED=%d FAILED_ENTRIES=%d\n%s' % (total, len(fail), '\n'.join(res))
open(r'D:\TLGL\.scratch\res5.txt', 'w', encoding='utf-8').write(out)
print('done')
