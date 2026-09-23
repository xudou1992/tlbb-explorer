p = r'D:\TLGL\.scratch\wb_build2.txt'
raw = open(p, 'rb').read()
t = raw.decode('utf-16-le', errors='replace')
if 'error' not in t and 'warning' not in t:
    t = raw.decode('utf-8', errors='replace')
t = t.replace('\x00', '')
i = t.find('error')
out = t[max(0, i - 200): i + 2200] if i >= 0 else t[-1200:]
open(r'D:\TLGL\.scratch\wb_err2.txt', 'w', encoding='utf-8').write(out)
print('done')
