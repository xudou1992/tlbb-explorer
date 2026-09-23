import subprocess, os, sys, shutil

CWD = r'D:\TLGL\tlbb-explorer'
TARGET = r'D:\TLGL\.scratch\rc3'
LOG = r'D:\TLGL\.scratch\tests.log'

env = dict(os.environ)
env['CARGO_TARGET_DIR'] = TARGET
cargo = shutil.which('cargo') or r'C:\Users\Administrator\.cargo\bin\cargo.exe'

r = subprocess.run([cargo, 'test', '-p', 'tlbb-core', '--lib', '--jobs', '1'],
                   cwd=CWD, capture_output=True, text=True,
                   encoding='utf-8', errors='replace', env=env, timeout=900)
with open(LOG, 'w', encoding='utf-8') as f:
    f.write(f"exit={r.returncode}\n")
    f.write("===== STDOUT =====\n"); f.write(r.stdout)
    f.write("\n===== STDERR =====\n"); f.write(r.stderr)
print("TEST exit:", r.returncode)
lines = (r.stdout + r.stderr).splitlines()
# print test result summary lines
for l in lines:
    if 'test result' in l or l.strip().startswith('error') or 'panicked' in l:
        print(l)
