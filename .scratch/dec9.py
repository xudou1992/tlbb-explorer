p = r'D:\TLGL\.scratch\test_out7.txt'
raw = open(p, 'rb').read()
t = raw.decode('utf-16-le', errors='replace')
if 'test result' not in t:
    t = raw.decode('utf-8', errors='replace')
t = t.replace('\x00', '')
import re
res = re.findall(r'test result: (ok\. \d+ passed[^\r\n]*|FAILED[^\r\n]*)', t)
total = sum(int(m.group(1)) for r in res for m in [re.search(r'(\d+) passed', r)] if m)
fail = [r for r in res if not r.startswith('ok')]
out = 'TOTAL_PASSED=%d FAILED=%d\n%s' % (total, len(fail), '\n'.join(res))
open(r'D:\TLGL\.scratch\res7.txt', 'w', encoding='utf-8').write(out)
print('done')
