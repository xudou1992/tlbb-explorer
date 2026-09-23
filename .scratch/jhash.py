"""Python port of sub_14059F020 — the JPAK path -> u64 hash."""
import json

M32 = 0xFFFFFFFF


def path_hash(p):
    b = p.replace('\\', '/').encode('utf-8')
    h1, h2 = 0x4E67C6A7, 0
    for c in b:
        if 65 <= c <= 90:
            c += 32
        elif c == 92:
            c = 47
        h1 ^= (c + 32 * h1 + (h1 >> 2)) & M32
        h1 &= M32
        h2 = (c + 65599 * h2) & M32
    return h1 | (h2 << 32)


if __name__ == '__main__':
    rows = json.load(open(r'D:\TLGL\.scratch\out\loose_index.json', encoding='utf-8'))
    ok = sum(1 for r in rows if path_hash(r['path']) == int(r['hash'], 16))
    print('path_hash matches %d/%d manifest records' % (ok, len(rows)))
    for r in rows[:3]:
        print('  %-40s %016x %s' % (r['path'], path_hash(r['path']),
                                    'OK' if path_hash(r['path']) == int(r['hash'], 16) else 'BAD'))
