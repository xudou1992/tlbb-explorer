p = r'D:\TLGL\.scratch\test_out12.txt'
raw = open(p, 'rb').read()
t = raw.decode('utf-16-le', errors='replace')
if 'test result' not in t and 'panicked' not in t:
    t = raw.decode('utf-8', errors='replace')
t = t.replace('\x00', '')
import re
res = re.findall(r'test result: [^\r\n]*', t)
out = '\n'.join(res) + '\n'
j = t.find('panicked')
if j >= 0:
    out += 'PANIC:\n' + t[max(0, j-500): j+900]
i = t.find('error[')
if i < 0:
    i = t.find('error:')
if i >= 0:
    out = 'COMPILE:\n' + t[max(0, i-300):i+1200] + '\n' + out
open(r'D:\TLGL\.scratch\err12.txt', 'w', encoding='utf-8').write(out)
print('done')
