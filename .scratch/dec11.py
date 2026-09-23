p = r'D:\TLGL\.scratch\test_out8.txt'
raw = open(p, 'rb').read()
t = raw.decode('utf-16-le', errors='replace')
if 'error' not in t and 'test result' not in t:
    t = raw.decode('utf-8', errors='replace')
t = t.replace('\x00', '')
i = t.find('error')
out = (t[max(0, i - 300): i + 2000] if i >= 0 else '(no compile error)\n')
import re
res = re.findall(r'test result: [^\r\n]*', t)
out += '\n'.join(res)
# test failures detail
j = t.find('panicked')
if j >= 0:
    out += '\n\nPANIC:\n' + t[max(0, j-300): j+800]
open(r'D:\TLGL\.scratch\err8.txt', 'w', encoding='utf-8').write(out)
print('done')
