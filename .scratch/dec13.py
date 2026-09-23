p = r'D:\TLGL\.scratch\test_out10.txt'
raw = open(p, 'rb').read()
t = raw.decode('utf-16-le', errors='replace')
if 'test result' not in t:
    t = raw.decode('utf-8', errors='replace')
t = t.replace('\x00', '')
import re
m = re.search(r'test preview::geometry[^\r\n]*', t)
res = re.findall(r'test result: [^\r\n]*', t)
open(r'D:\TLGL\.scratch\res10.txt', 'w', encoding='utf-8').write(
    (m.group(0) if m else '?') + '\n' + '\n'.join(res[:3]))
print('done')
