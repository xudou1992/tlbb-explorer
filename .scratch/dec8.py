p = r'D:\TLGL\.scratch\test_out6.txt'
raw = open(p, 'rb').read()
t = raw.decode('utf-16-le', errors='replace')
if 'test result' not in t and 'error' not in t:
    t = raw.decode('utf-8', errors='replace')
t = t.replace('\x00', '')
i = t.find('error')
out = t[max(0, i - 400): i + 2500] if i >= 0 else '(no error found) ' + t[-1500:]
import re
res = re.findall(r'test result: [^\r\n]*', t)
out += '\n\nRESULT_LINES=%d\n' % len(res) + '\n'.join(res[:30])
open(r'D:\TLGL\.scratch\err6.txt', 'w', encoding='utf-8').write(out)
print('done')
