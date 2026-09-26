import struct, collections, sqlite3, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
raw = open('D:/TLGL/.scratch/out/tree/ResourcePath.cfg','rb').read()
print('file size:', len(raw), 'magic:', raw[:4])
hdr = struct.unpack_from('<16I', raw, 0)
print('header u32[0:16]:', hdr)
N = hdr[9]
REC_OFF = 64
STRTAB_OFF = REC_OFF + N * 36
BLOB = 3783792
NS = (BLOB - STRTAB_OFF) // 8
print(f'N={N}  strtab@{STRTAB_OFF}  descriptors={NS} (2xN={2*N})  blob@{BLOB} bloblen={len(raw)-BLOB}')

# sanity: descriptor offsets must be monotonic and cover the blob
descs = [struct.unpack_from('<II', raw, STRTAB_OFF + 8*i) for i in range(NS)]
offs = [a for a,b in descs]
print('desc off monotonic:', all(offs[i] <= offs[i+1] for i in range(len(offs)-1)),
      'last end:', offs[-1]+descs[-1][1], 'blob len:', len(raw)-BLOB)
strings = [raw[BLOB+a : BLOB+a+b] for a,b in descs]
ctrl = sum(1 for s in strings if any(c < 9 or (14 <= c < 32) for c in s))
print('strings with control chars:', ctrl, '/', NS)

recs = [struct.unpack_from('<9I', raw, REC_OFF + 36*k) for k in range(N)]
ok = sum(1 for f in recs if f[1] < NS and f[3] < NS)
print(f'records with valid string idx: {ok}/{N}')
print('rec0 fields:', recs[0]); print('rec1 fields:', recs[1])
# other fields distribution (non-string fields)
for col in (0,2,4,5,6,7,8):
    vals = collections.Counter(f[col] for f in recs)
    top = vals.most_common(4)
    print(f'  field{col}: distinct={len(vals)} top={top}')
