"""决定性交叉比对：ResourcePath.cfg 的 key/路径 × 材质悬空贴图名。
两个输入文件分别由 Agent A（cfg_keys.txt / cfg_paths.txt）和 Agent C
（mtl_dangling_names.txt）落盘；本脚本等两者齐了再跑。
"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
BASE = 'D:/TLGL/.scratch/'

def load(path, strip_comment=False):
    try:
        with open(BASE + path, 'rb') as f:
            raw = f.read().decode('utf-8', errors='replace')
    except FileNotFoundError:
        return None
    lines = [l.rstrip('\r\n') for l in raw.split('\n')]
    if strip_comment:
        lines = [l for l in lines if l and not l.startswith('#')]
    else:
        lines = [l for l in lines if l]
    return lines

keys = load('cfg_keys.txt')
paths = load('cfg_paths.txt')
dangling = load('mtl_dangling_names.txt', strip_comment=True)
for label, xs in (('cfg_keys', keys), ('cfg_paths', paths), ('dangling', dangling)):
    print(f'{label}: ' + ('MISSING' if xs is None else f'{len(xs)} rows, distinct {len(set(xs))}'))
if not (keys and paths and dangling):
    sys.exit('inputs not ready')

dang_low = {d.lower() for d in dangling}
def basename(p):
    return p.replace(chr(92), '/').rsplit('/', 1)[-1]

# 1) cfg key（裸名侧）直接命中悬空名
hit_key = sorted({k for k in keys if k.lower() in dang_low})
print(f'\n[1] cfg keys 命中悬空贴图名: {len(hit_key)} / distinct dangling {len(dang_low)}')
print('    样例:', hit_key[:10])

# 2) cfg 路径的 basename 命中悬空名
path_base = {basename(p): p for p in paths}
hit_base = sorted({b for b in path_base if b.lower() in dang_low})
print(f'\n[2] cfg 路径 basename 命中悬空贴图名: {len(hit_base)}')
print('    样例:', [(b, path_base[b]) for b in hit_base[:5]])

# 3) 合计：悬空名有多少能被 cfg 任一侧解释
explained = {d for d in dang_low
             if any(k.lower() == d for k in keys) or any(b.lower() == d for b in path_base)}
print(f'\n[3] 悬空名可被 cfg 解释: {len(explained)} / {len(dang_low)}'
      f'  ({100*len(explained)/max(1,len(dang_low)):.1f}%)')

# 4) 反向：cfg 里 .tga 侧的规模
tga_paths = [p for p in paths if p.lower().endswith('.tga')]
tga_keys = [k for k in keys if k.lower().endswith('.tga')]
print(f'\n[4] cfg 中 .tga: 路径 {len(tga_paths)} 条（distinct {len(set(tga_paths))}），key {len(tga_keys)} 条')
