import subprocess, re

EXE = r'D:\TLGL\.scratch\rc3\debug\view.exe'
r = subprocess.run([EXE, "--name=w1351_model_xianglong_b7_lf001_E.mesh", "--dump=18532"],
                   capture_output=True, timeout=120)
raw = r.stdout  # bytes
# decode best effort
txt = raw.decode('cp936', errors='replace')
# The ascii column is the trailing printable part of each dump line.
# Just scan whole text for tga/mtl references (case-insensitive).
found = set()
for m in re.finditer(r'[\w./\-]{4,}\.(?:tga|mtl|dds|mdl|ske|ani|png)', txt, re.IGNORECASE):
    found.add(m.group(0).lower())
print("embedded refs found in dump text:")
for f in sorted(found):
    print("  ", f)
print("total:", len(found))
