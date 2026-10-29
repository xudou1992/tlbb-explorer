# 第 3 条「无记录骨骨位」的 Rust 侧静态复核（只读本轮 skel_dump 出的 JSON）。
# 记录里的判决实验 __jointDiag / __dropAndMeasure 是 three.js 浏览器探针，没有 Rust 对应；
# 这里退一步问同一件事：没有 96B 记录的那些骨，有没有任何一张影响表挂在它们身上？
import io, json, sys

path = sys.argv[1] if len(sys.argv) > 1 else \
    r'D:/TLGL/.scratch/dyn/verify13/w1351_monster_guifengzhuangke_lian_001.skel.json'
d = json.load(io.open(path, encoding='utf-8'))

chain = [e['name'] for e in (d.get('parentChain') or [])]
nodes = d.get('nodes') or []
node_names = [n['name'] for n in nodes]
with_inf = [n['name'] for n in nodes if n.get('influences')]
no_record = [b for b in chain if b not in set(node_names)]
tot_w = sum(sum(e for e in (n['influences']['weights'] if n.get('influences') else []))
            for n in nodes)

print('%s' % path.replace('\\', '/').split('/')[-1])
print('父骨链 %d 根 · 节点记录 %d 条（含 origin/top 前奏）· 带影响表 %d 条' % (len(chain), len(nodes), len(with_inf)))
print('没有 96B 记录的骨：%d 根 → %s' % (len(no_record), no_record))
print('这些无记录骨里，有任何一根挂着影响表吗：%s'
      % ('有（判断不成立）' if set(no_record) & set(with_inf) else '没有一张（零权重，与记录一致）'))
print('全部影响表的权重合计（求和后 round）：%.1f' % tot_w)
