p = r'D:\TLGL\.scratch\test_out11.txt'
raw = open(p, 'rb').read()
t = raw.decode('utf-16-le', errors='replace')
if 'test result' not in t and 'error' not in t:
    t = raw.decode('utf-8', errors='replace')
t = t.replace('\x00', '')
i = t.find('error[')
if i < 0:
    i = t.find('error:')
out = t[max(0, i - 300):i + 1800] if i >= 0 else t[-800:]
open(r'D:\TLGL\.scratch\err11.txt', 'w', encoding='utf-8').write(out)
print('done')
