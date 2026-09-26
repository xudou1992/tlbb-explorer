import struct, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
raw = open('D:/TLGL/.scratch/out/tree/ResourcePath.cfg','rb').read()
# record area starts at 24 (root chunk body) or 64? dump both
print('u32[24:64] :', struct.unpack_from('<10I', raw, 24))
print('u32[64:104]:', struct.unpack_from('<10I', raw, 64))
for at in (2619520, 2619524, 2619528, 2619548, 2619552, 2619556, 2619560):
    print(f'u32@{at}:', struct.unpack_from('<6I', raw, at))
