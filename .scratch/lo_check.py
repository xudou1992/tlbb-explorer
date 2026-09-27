import sqlite3, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
c = sqlite3.connect('file:D:/TLGL/.scratch/resources.db?mode=ro', uri=True)
rows = c.execute("select hash, filecrc from resources where named=1 limit 3000").fetchall()
eq = sum(1 for h, fc in rows if (int(h,16) & 0xffffffff) == (fc & 0xffffffff))
print(f'low32 == filecrc: {eq}/{len(rows)}')
import collections
fc_dup = collections.Counter(fc for _, fc in rows)
print('filecrc dup top3:', fc_dup.most_common(3))
