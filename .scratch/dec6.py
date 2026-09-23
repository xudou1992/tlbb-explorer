p = r'D:\TLGL\.scratch\test_out4.txt'
raw = open(p, 'rb').read()
t = raw.decode('utf-16-le', errors='replace')
if 'test result' not in t:
    t = raw.decode('utf-8', errors='replace')
t = t.replace('\x00', '')
import re
res = re.findall(r'test result: (ok\. \d+ passed[^\r\n]*|FAILED[^\r\n]*)', t)
runs = re.findall(r'Running (tests\\[^\r\n ]*|unittests [^\r\n]*)', t)
total = 0
for r in res:
    m = re.search(r'(\d+) passed', r)
    if m: total += int(m.group(1))
out = 'TOTAL_PASSED=%d\n\n' % total + '\n'.join('%s | %s' % (a, b) for a, b in zip(runs, res))
open(r'D:\TLGL\.scratch\res4.txt', 'w', encoding='utf-8').write(out)
print('done')
