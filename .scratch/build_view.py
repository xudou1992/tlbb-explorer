import subprocess, os, sys, shutil

CWD = r'D:\TLGL\tlbb-explorer'
TARGET = r'D:\TLGL\.scratch\rc3'
LOG = r'D:\TLGL\.scratch\build_view.log'

env = dict(os.environ)
env['CARGO_TARGET_DIR'] = TARGET
cargo = shutil.which('cargo') or r'C:\Users\Administrator\.cargo\bin\cargo.exe'

def run(args, label):
    sys.stderr.write(f"=== {label} ===\n")
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write(f"\n########## {label} ##########\n")
    r = subprocess.run([cargo] + args, cwd=CWD, capture_output=True,
                       text=True, encoding='utf-8', errors='replace',
                       env=env, timeout=900)
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write(f"----- {label} exit={r.returncode} -----\n")
        f.write("===== STDOUT =====\n")
        f.write(r.stdout)
        f.write("\n===== STDERR =====\n")
        f.write(r.stderr)
    return r

open(LOG, 'w', encoding='utf-8').close()
r = run(['build', '-p', 'tlbb-core', '--bin', 'view', '--jobs', '1'], 'BUILD view')
print("BUILD exit:", r.returncode)
lines = (r.stdout + r.stderr).splitlines()
errs = [l for l in lines if 'error[' in l or l.strip().startswith('error:')]
print("ERROR LINES:", len(errs))
for l in errs[:80]:
    print(l)
