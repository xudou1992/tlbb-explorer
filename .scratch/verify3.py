import re, collections, idautils, idc, ida_bytes, ida_segment, math

out = []
w = out.append

strs = [(x.ea, str(x)) for x in idautils.Strings()]
txts = {t for _, t in strs}

# ---------- 1. GP/Fantasy module prefixes from 'Class::Method' log strings ----------
w('=== module prefixes inferred from "Class::Function" log strings ===')
cls = collections.Counter()
for t in txts:
    m = re.match(r'^([A-Za-z_][A-Za-z0-9_]{2,60})::([A-Za-z_~][A-Za-z0-9_]{2,60})$', t)
    if m:
        cls[m.group(1)] += 1
w('distinct classes with ::style strings: %d' % len(cls))
pref = collections.Counter()
for k in cls:
    p = re.match(r'^(C|I|S|CGP|GP|KL)?[A-Za-z]{0,4}', k)
    pref[k[:6]] += 0
# group by leading acronym
g = collections.Counter()
for k in cls:
    m = re.match(r'^([A-Z]{1,4}[a-z])', k)
    g[k.split('_')[0][:10]] += 1
for k, v in cls.most_common(60):
    w('%6d  %s' % (v, k))

# ---------- 2. Lua script file references ----------
w('')
w('=== lua / script asset references ===')
for t in sorted(txts):
    if re.search(r'\.lua$|\.lua\b|Script\\\\|\\\\Script|lua_init|lua_load|luaL_|\.chan\b|\.gfx|\.mesh|\.skeleton', t, re.I) and len(t) < 120:
        w('  ' + t)

# ---------- 3. pak / resource container format ----------
w('')
w('=== resource container / format strings ===')
for t in sorted(txts):
    if re.search(r'\.pak|JPAK|PackageFile|PackageManager|FileMapping|Compress|Lzma|lzma|zlib|crc|CRC|decode key|encrypt', t) and len(t) < 130:
        w('  ' + t)

# ---------- 4. protocol / server strings ----------
w('')
w('=== protocol / session / server strings ===')
for t in sorted(txts):
    if re.search(r'login|Login|session|Session|game[_ ]?server|GameServer|protocol|Protocol|packet|Packet|socket|Socket|connect fail|handshake|heartbeat|Heartbeat', t) and len(t) < 110:
        w('  ' + t)

open(r'D:\TLGL\.scratch\v3_out.txt', 'w', encoding='utf-8').write('\n'.join(out))
print('WROTE ->v3_out.txt lines=%d' % len(out))
