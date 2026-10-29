# 覆盖表体检：每条确认的槽是否真实、哈希是否能解、是否在候选榜里、绑到哪只网格。
# 只读；不改覆盖表、不改资源库。输出 Markdown 到 stdout。
import json, os, sqlite3, sys, datetime

ROOT = r'D:\TLGL'
OV = os.path.join(ROOT, '.scratch', 'model_texture_override.json')
DB = os.path.join(ROOT, '.scratch', 'resources.db')

def main():
    v = json.load(open(OV, encoding='utf-8'))
    ov = v.get('overrides', {})
    c = sqlite3.connect(DB)
    print('# 覆盖表贴图异常项体检')
    print()
    print(f'- 表：`{OV}`')
    print(f'- 条数：**{len(ov)}**')
    print()
    if not ov:
        print('表是空的。')
        return
    for key, e in sorted(ov.items()):
        print(f'## `{key}`')
        slot = key.split(':', 1)[1].rsplit('/', 1)[-1] if ':' in key else key
        h = (e.get('hash') or '').strip().lower().removeprefix('0x')
        print(f'- 槽名：`{slot}`')
        print(f'- 哈希：`{h}`')
        print(f'- note：{e.get("note") or "(空)"}')
        ts = e.get('ts')
        if isinstance(ts, int):
            try: print(f'- 时间：{datetime.datetime.fromtimestamp(ts)}')
            except Exception: print(f'- 时间：{ts}')
        print(f'- 绑定网格：`{e.get("mesh") or "(未绑定)"}`')
        # 槽名出现在哪些资产组
        gids = [r[0] for r in c.execute('select distinct gid from agroup_names where name=?', (slot,))]
        print(f'- 槽名所属资产组：{gids or "（没有）"}')
        # refs 来源
        refs = c.execute('select from_path, to_hash from refs where name=? limit 8', (slot,)).fetchall()
        print(f'- 引用来源：{refs or "（没有）"}')
        # 哈希资源
        row = c.execute('select path,name,type,width,height,codec,mips,pak from resources where hash=?', (h,)).fetchone()
        if row:
            print(f'- 哈希实体：type={row[2]} {row[3]}×{row[4]} {row[5]} mips={row[6]} pak={row[7]} path={row[0] or "(匿名)"}')
        else:
            print('- 哈希实体：**资源库里没有这个 hash**')
        # 候选榜名次 + 绑定网格是否存在
        for gid in gids:
            meshes = [r[0] for r in c.execute(
                "select distinct r.name from amembers m join resources r on r.hash=m.hash "
                "where m.gid=? and r.type='mesh'", (gid,))]
            print(f'- 资产组 {gid} 的网格：{meshes or "（没有网格）"}')
            bound = (e.get('mesh') or '').rsplit('/', 1)[-1]
            if bound and bound not in meshes:
                print(f'  - **绑定异常**：`{bound}` 不在这个组的网格里')
            for mesh in meshes:
                stem = mesh[:-5] if mesh.endswith('.mesh') else mesh
                rp = os.path.join(ROOT, '.scratch', 'uvfit_batch', 'results', stem + '.json')
                if not os.path.isfile(rp):
                    print(f'  - {mesh}：没有批量候选缓存')
                    continue
                d = json.load(open(rp, encoding='utf-8'))
                cands = d.get('candidates') or []
                rank = next((i + 1 for i, x in enumerate(cands) if (x.get('hash') or '').lower() == h), None)
                print(f'  - {mesh}：候选 {len(cands)} 张，目标 hash 名次 = {rank if rank else "**不在榜里**"}')
        print()
    print('## 结论')
    print('- 「槽名/键/哈希能解」与「能不能自动套回模型」是两件事：')
    print('  旧 `mesh_override_png` 只找与网格同名的槽；头发/衣服槽不同名时，确认会写进表但**永远套不上**。')
    print('- 2026-10-26 起覆盖表条目带 `mesh` 绑定，确认时由界面写入；加载时按绑定找回。')
    print('- 多条绑定同一网格时拒绝猜（mask 与基础色各一条时套错比灰模更坏）。')

if __name__ == '__main__':
    main()
