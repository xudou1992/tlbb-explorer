import subprocess, os, time

EXE = r"D:\TLGL\.scratch\rc3\debug\view.exe"
ENV = dict(os.environ)

def run(name):
    t0 = time.time()
    p = subprocess.run([EXE, "--name=" + name], capture_output=True, cwd=r"D:\TLGL",
                       env=ENV, timeout=600)
    wall = time.time() - t0
    try:
        o = p.stdout.decode("utf-8")
    except Exception:
        o = p.stdout.decode("gbk", "replace")
    # 只取几何段之后的部分
    i = o.find("几何段")
    return wall, o[i:] if i >= 0 else "(无几何段输出)\n" + o[-400:]

parts = []
for n in ["w1351_model_plane_c01.mesh",
          "w1351_monster_xiyuqiezei_yifu_001.mesh",
          "test_jianzhen.mesh",
          "w1351_st_fwzhongxing_001.mesh"]:
    w, o = run(n)
    parts.append("=== %s (%.2fs) ===\n%s" % (n, w, o))

open(r"D:\TLGL\.scratch\mesh_verify.txt", "w", encoding="utf-8").write("\n\n".join(parts))
print("done")
