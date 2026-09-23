p = r'D:\TLGL\.scratch\test_out2.txt'
raw = open(p, 'rb').read()
t = raw.decode('utf-16-le', errors='replace')
if 'cargo' not in t[:300] and 'Compiling' not in t[:500]:
    t = raw.decode('utf-8', errors='replace')
t = t.replace('\x00', '')
i = t.find('E0382')
out = t[max(0, i - 200): i + 3000]
open(r'D:\TLGL\.scratch\err_ctx.txt', 'w', encoding='utf-8').write(out)
print('found at', i)
