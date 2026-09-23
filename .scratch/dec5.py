p = r'D:\TLGL\.scratch\test_out3.txt'
raw = open(p, 'rb').read()
t = raw.decode('utf-16-le', errors='replace')
if 'cargo' not in t[:300] and 'Compiling' not in t[:500] and 'error' not in t[:500]:
    t = raw.decode('utf-8', errors='replace')
t = t.replace('\x00', '')
i = t.find('error')
out = t[max(0, i - 300): i + 2500] if i >= 0 else t[-2500:]
open(r'D:\TLGL\.scratch\err3_ctx.txt', 'w', encoding='utf-8').write(out)
# also tally test results
import re
res = re.findall(r'test result: .*', t)
open(r'D:\TLGL\.scratch\res3.txt', 'w', encoding='utf-8').write('\n'.join(res))
print('errors_found', i >= 0, 'result_lines', len(res))
