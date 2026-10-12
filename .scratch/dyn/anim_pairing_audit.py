#!/usr/bin/env python3
"""审「网格拿到了别人的动作」这个产品级风险。

先记一次自己的错：第一版我拿导出 GLB 的 `animations[].name` 去比角色名，结果 1,765 条
全"不匹配"——那是我的错，导出器会把公共前缀**剥掉**（`mesh2glb.rs` 里 `strip_prefix(&pre)`），
GLB 里存的是 `behit`/`dead` 这种短名。要审只能回源目录审。

这一版看目录事实：某目录里有 `.mesh` 也有 `.ani`（或 `ani/` 子目录）时，
数一数每份网格能配上几条**同角色**动作、又有多少条动作其实属于别人。
"""
import os, glob, collections

PARTS = {'yifu', 'shoutao', 'toufa', 'lian', 'weapon', 'prop'}


def fam(n):
    segs = n.split('_')
    while len(segs) >= 3:
        last = segs[-1]
        form = last.startswith('b') and last[1:].isdigit()
        if (last.isdigit() and len(last) <= 3) or (form and len(last) <= 4) or last.lower() in PARTS:
            segs = segs[:-1]
        else:
            break
    return '_'.join(segs)


def same(a, b):
    return a == b or b.startswith(a + '_') or a.startswith(b + '_')


def audit(root):
    dirs = sorted({os.path.dirname(p) for p in glob.glob(root + '/**/*.mesh', recursive=True)})
    both = 0
    mesh_no_own = []
    foreign_only_dirs = 0
    anis_foreign = 0
    anis_total = 0
    for d in dirs:
        meshes = glob.glob(d + '/*.mesh')
        anis = glob.glob(d + '/*.ani') + glob.glob(d + '/ani/*.ani')
        if not anis:
            continue
        both += 1
        mkeys = [fam(os.path.basename(m)[:-5]) for m in meshes]
        akeys = [fam(os.path.basename(a)[:-4]) for a in anis]
        anis_total += len(akeys)
        for mk in mkeys:
            own = [ak for ak in akeys if same(mk, ak)]
            if not own:
                mesh_no_own.append((d, mk, len(akeys)))
        for ak in akeys:
            if not any(same(mk, ak) for mk in mkeys):
                anis_foreign += 1
        if all(not any(same(mk, ak) for mk in mkeys) for ak in akeys):
            foreign_only_dirs += 1
    print('%s：有网格又有动作的目录 %d 个 · 动作文件 %d 条' % (root, both, anis_total))
    print('  一份同角色动作都配不到的网格：%d 份' % len(mesh_no_own))
    print('  不属于本目录任何网格的动作：%d 条（%.1f%%）' % (anis_foreign, 100.0 * anis_foreign / max(1, anis_total)))
    print('  「整目录动作全是别人」的目录：%d 个' % foreign_only_dirs)
    for d, mk, n in mesh_no_own[:6]:
        print('     %-46s 键 %s · 该目录动作 %d 条' % (d.replace(root + os.sep, ''), mk, n))


for r in ('.scratch/out/sidecar_tree', '.scratch/out/tree'):
    audit(r)
