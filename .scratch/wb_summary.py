import os

p = r'D:\TLGL\.scratch\wb_build.txt'
raw = open(p, 'rb').read()
t = raw.decode('utf-16-le', errors='replace')
if 'Compiling' not in t and 'cargo' not in t[:300] and 'Finished' not in t:
    t = raw.decode('utf-8', errors='replace')
t = t.replace('\x00', '')
lines = t.splitlines()
keep = []
for l in lines:
    s = l.strip()
    if ('warning' in s.lower() or 'error' in s.lower() or 'Finished' in s
            or 'Compiling tlbb' in s or 'Compiling tlbb-shell' in s):
        keep.append(s)
open(r'D:\TLGL\.scratch\wb_build_summary.txt', 'w', encoding='utf-8').write('\n'.join(keep[-40:]))
print('kept', len(keep))

# locate the produced exe
for cand in [r'D:\TLGL\.scratch\rc3\debug\tlbb-shell.exe',
             r'D:\TLGL\tlbb-explorer\app\src-tauri\target\debug\tlbb-shell.exe',
             r'D:\TLGL\tlbb-explorer\app\target\debug\tlbb-shell.exe']:
    if os.path.exists(cand):
        print('EXE', cand, os.path.getsize(cand), os.path.getmtime(cand))
