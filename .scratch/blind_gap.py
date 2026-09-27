"""Can the dangling .mesh names (the 9% prop-geometry gap) be recovered by path-hash enumeration?
Read-only."""
import collections
import sys

sys.path.insert(0, r'D:\TLGL\.scratch')
from blind_reader import conn  # noqa: E402
from jhash import path_hash  # noqa: E402

C = conn()
Q = lambda s: [tuple(x) for x in C.execute(s).fetchall()]

named_paths = {r[0] for r in Q("select path from resources where path is not null")}
rows_by_hash = dict(Q("select hash, type||'/'||ifnull(subtype,'-') from resources"))
nameless = {r[0] for r in Q("select hash from resources where named=0")}
dang = [r[0] for r in Q("select name from dangling where ext='.mesh'")]
print('dangling .mesh names:', len(dang))
print('sample:', dang[:5])

# how are real .mesh in mobile_maps_source laid out?
print('\nreal mobile_maps_source .mesh paths:', Q("select path from resources where ext='.mesh' and named=1 and dir like 'mobile_maps_source%' limit 4"))
print('real data/scene .mesh paths        :', Q("select path from resources where ext='.mesh' and named=1 and dir like 'data/scene%' limit 3"))

TPL = [
    '{n}',
    'mobile_maps_source/{n}',
    'mobile_maps_source/{b}/{n}',
    'mobile_maps_source/{b}.mesh/{n}',
    'data/scene/{n}',
    'data/scene/{b}/{n}',
    'data/source/scene/{b}/{n}',
    'data/scene/dan/{b}/{n}',
]
stats = collections.Counter()
found_named = {}
found_nameless = {}
for nm in dang:
    b = nm[:-5] if nm.endswith('.mesh') else nm
    for t in TPL:
        p = t.format(n=nm, b=b)
        k = '%016x' % path_hash(p)
        if k in rows_by_hash:
            if k in nameless:
                found_nameless[k] = p
            else:
                found_named[k] = p
            stats[t] += 1
            break
print('\nrecovered by pattern:')
for t, n in stats.most_common():
    print('   %-40s %d' % (t, n))
print('total resolved: named-entity %d, nameless-entity %d, of %d dangling names'
      % (len(found_named), len(found_nameless), len(dang)))
print('sample nameless hits:', list(found_nameless.items())[:5])
print('sample named hits   :', list(found_named.items())[:3])

# reverse sanity: apply the same templates to a KNOWN named mesh, must self-resolve
tests = Q("select path,hash from resources where ext='.mesh' and named=1 and dir like 'mobile_maps_source%' limit 5")
ok = 0
for p, h in tests:
    b = p.rsplit('/', 1)[1][:-5]
    for t in TPL:
        if '%016x' % path_hash(t.format(n=p.rsplit('/', 1)[1], b=b)) == h:
            ok += 1
            break
print('\ntemplate self-test on 5 known mobile_maps_source .mesh: %d/5 resolved' % ok)
for p, _h in tests:
    print('   ', p)

# is the 9% gap about names, or about bytes actually missing?
print('\ncoverage facts:')
print('  named .mesh rows:', Q("select count(*) from resources where ext='.mesh' and named=1"))
print('  nameless .mesh rows (type=mesh, no path):', Q("select count(*), sum(original) from resources where type='mesh' and named=0"))
print('  dangling total:', Q("select ext,count(*),sum(n_refs) from dangling group by 1 order by 3 desc"))
