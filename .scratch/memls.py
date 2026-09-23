import os

d = r'D:\TLGL\.workbuddy\memory'
out = []
for f in sorted(os.listdir(d)):
    p = os.path.join(d, f)
    if os.path.isfile(p):
        out.append('%s %d bytes' % (f, os.path.getsize(p)))
open(r'D:\TLGL\.scratch\memls.txt', 'w', encoding='utf-8').write('\n'.join(out))
print('done')
