"""Confirm: for the 25 gids, does the NEW build's candidate come from the texture member?

Prints gid + the expected texture hash so we can cross-check against the shell.
"""
import sqlite3, subprocess, re, os

DB = r"D:\TLGL\.scratch\resources.db"
con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
rows = list(con.execute(
    "SELECT m.gid, m.hash, r.path FROM amembers m "
    "LEFT JOIN resources r ON r.hash = m.hash "
    "WHERE m.role='texture' ORDER BY m.gid"
))
con.close()

exe = r"D:\TLGL\.scratch\rc_app\debug\tlbb-shell.exe"
env = dict(os.environ, TLBB_ROOT="D:/TLGL", TLBB_DB=DB)

out = []
out.append("== 25 texture-member gids, expected hash ==")
for gid, h, path in rows:
    out.append(f"  gid={gid:<6} hash={h}  {path}")

# Run the shell probe and look for these gids in its detail lines, which print 图：WxH fmt
out.append("")
out.append("== shell probe output (raw, utf8-decoded) ==")
for word in ["yifu", "shukuang", "feilongchengfeng"]:
    try:
        p = subprocess.run([exe, "--probe", word], capture_output=True, env=env, timeout=600)
        raw = p.stdout
        try:
            txt = raw.decode("utf-8")
        except UnicodeDecodeError:
            txt = raw.decode("gbk", errors="replace")
        out.append(f"--- probe {word} (exit={p.returncode}) ---")
        for line in txt.splitlines():
            if re.search(r"图：|统计|等级|warm:", line):
                out.append("   " + line)
    except Exception as e:
        out.append(f"--- probe {word} FAILED: {e}")

open(r"D:\TLGL\.scratch\verify25.txt", "w", encoding="utf-8").write("\n".join(out))
print("ok")
