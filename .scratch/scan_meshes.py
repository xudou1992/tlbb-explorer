import subprocess, re

EXE = r'D:\TLGL\.scratch\rc3\debug\view.exe'

def run(args):
    r = subprocess.run([EXE] + args, capture_output=True, timeout=120)
    return r.stdout.decode('cp936', errors='replace')

# list some meshes
listing = run(["--type=mesh", "--limit=40"])
names = []
for line in listing.splitlines():
    m = re.search(r'(\S+\.mesh)', line)
    if m:
        names.append(m.group(1))
print("found meshes:", len(names))

def refs_in_dump(name):
    out = run([f"--name={name}", "--dump=200000"])
    buf = bytearray()
    for line in out.splitlines():
        mm = re.match(r'^  ([0-9a-f]{6})  (.{48}) ', line)
        if not mm: continue
        hr = mm.group(2).replace(' ', '')
        for i in range(0, len(hr), 2):
            try: buf.append(int(hr[i:i+2], 16))
            except ValueError: pass
    runs = []
    cur = bytearray()
    for c in buf:
        if 0x20 <= c <= 0x7e: cur.append(c)
        else:
            if len(cur) >= 4: runs.append(bytes(cur).decode('ascii'))
            cur = bytearray()
    if len(cur) >= 4: runs.append(bytes(cur).decode('ascii'))
    return [s for s in runs if '.' in s and re.search(r'\.(tga|mtl|dds|mdl|ske|ani|png)$', s, re.I)]

checked = 0
for n in names:
    rs = refs_in_dump(n)
    if rs:
        print(f"\n{n} HAS {len(rs)} embedded refs:")
        for s in rs[:10]:
            print("   ", s)
        checked += 1
        if checked >= 3:
            break
else:
    print("none of the listed meshes had embedded ext refs either")
