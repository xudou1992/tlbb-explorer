import subprocess, os, sys, struct, shutil

EXE = r'D:\TLGL\.scratch\rc3\debug\view.exe'
PNGDIR = r'D:\TLGL\.scratch\view_png'

def run(args):
    r = subprocess.run([EXE] + args, capture_output=True, timeout=120)
    # Windows console is CP936 on zh; fall back to utf-8
    try:
        out = r.stdout.decode('cp936')
    except Exception:
        out = r.stdout.decode('utf-8', errors='replace')
    try:
        err = r.stderr.decode('cp936')
    except Exception:
        err = r.stderr.decode('utf-8', errors='replace')
    return r.returncode, out, err

cases = [
    ["--name=w1351_smeh_shandongkou_001.mtl"],
    ["--name=w1351_model_xianglong_b7_lf001_E.mesh"],
    ["--name=w1351_monster_qinhuangjingbingyong_dead.ani"],
    [f"--name=w1351_nan_s_moyuqianyou_001.tga", f"--png-out={PNGDIR}"],
]

for i, args in enumerate(cases, 1):
    print(f"\n========== CASE {i}: {' '.join(args)} ==========")
    rc, out, err = run(args)
    print("rc=", rc)
    print(out)
    if err.strip():
        print("STDERR:", err)

# verify PNG dims for case 4
print("\n========== PNG IHDR CHECK ==========")
import glob
pngs = glob.glob(os.path.join(PNGDIR, "*.png"))
print("png files:", pngs)
for p in pngs:
    with open(p, 'rb') as f:
        data = f.read(33)
    assert data[:8] == b'\x89PNG\r\n\x1a\n', "not png"
    # IHDR: 4 len, 'IHDR', width(4), height(4)
    w, h = struct.unpack('>II', data[16:24])
    print(f"{p}: {w}x{h}")
