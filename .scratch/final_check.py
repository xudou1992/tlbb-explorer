import subprocess, os, json, sqlite3

exe = r"D:\TLGL\.scratch\rc3\debug\tlbb-shell.exe"
env = dict(os.environ)
env["TLBB_ROOT"] = r"D:\TLGL"
env["TLBB_DB"] = r"D:\TLGL\.scratch\resources.db"

p = subprocess.run([exe, "--probe", "曹霜"], capture_output=True,
                   cwd=r"D:\TLGL", env=env, timeout=600)
txt = None
for enc in ("utf-8", "gbk"):
    try:
        txt = p.stdout.decode(enc)
        break
    except Exception:
        continue
if txt is None:
    txt = p.stdout.decode("utf-8", "replace")

with open(r"D:\TLGL\.scratch\probe_final.txt", "w", encoding="utf-8") as f:
    f.write(txt)

# Independent cross-check of the headline numbers straight from SQLite, so a wrong
# number in the panel would show up as a mismatch here rather than pass unnoticed.
con = sqlite3.connect(f"file:{env['TLBB_DB']}?mode=ro", uri=True)
c = con.cursor()
c.execute("SELECT count(*) FROM refs")
total = c.fetchone()[0]
c.execute("SELECT count(*) FROM refs WHERE to_hash IS NOT NULL")
resolved = c.fetchone()[0]
c.execute("SELECT count(*) FROM dangling")
dang = c.fetchone()[0]
c.execute("SELECT count(DISTINCT from_hash) FROM refs")
ac = c.fetchone()[0]
c.execute("SELECT count(DISTINCT from_hash) FROM refs WHERE to_hash IS NOT NULL")
acr = c.fetchone()[0]
c.execute("SELECT count(DISTINCT to_hash) FROM refs WHERE to_hash IS NOT NULL")
distinct_to = c.fetchone()[0]
con.close()

with open(r"D:\TLGL\.scratch\crosscheck.txt", "w", encoding="utf-8") as f:
    f.write(f"sqlite: refs_total={total} resolved={resolved} dangling={dang} "
            f"assets_citing={ac} assets_citing_resolved={acr} distinct_targets={distinct_to}\n")

print("ok")
