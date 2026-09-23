"""Synthesise a plausible "next version" snapshot so the comparison path is exercised
end to end.  Only one client is installed here, so a real second version is not
available; this builds a fixture with known ground truth instead.

usage: python makedemo.py            # writes versions/示例_下一版.json
"""
import copy
import json
import os
import random

import identity

HERE = os.path.dirname(os.path.abspath(__file__))
A = os.path.join(HERE, 'out', 'versionA.json')
OUTD = os.path.join(HERE, 'versions')


def recompute(a):
    a['id_content'] = identity.id_content_of(a['members'])
    a['id_pack'] = identity.id_pack_of(a['members'])
    a['id_struct'] = identity.id_struct_of(a['members'], a.get('rels'))
    a['id_asset'] = identity.id_asset_of(a['id_content'], a['id_struct'])
    return a


def main():
    rnd = random.Random(20260922)
    src = json.load(open(A, encoding='utf-8'))
    B = copy.deepcopy(src)
    assets = B['assets']
    truth = {'仅重新打包': 0, '新增成员': 0, '删除成员': 0, '内容替换': 0, '消失': 0}

    pool = list(range(len(assets)))
    rnd.shuffle(pool)

    def pop(k):
        return [pool.pop() for _ in range(min(k, len(pool)))]

    for i in pop(12):
        truth['消失'] += 1
        assets[i] = None
    for i in pop(400):
        a = assets[i]
        for m in a['members']:
            m['crc'] = '%08x' % rnd.getrandbits(32)
        truth['仅重新打包'] += 1
        recompute(a)
    for i in pop(40):
        a = assets[i]
        for _ in range(rnd.randint(1, 3)):
            a['members'].append({'role': 'animation', 'name': 'clip_new%d.ani' % i,
                                 'sha': '%016x' % rnd.getrandbits(64),
                                 'crc': '%08x' % rnd.getrandbits(32), 'type': 'ani',
                                 'w': None, 'h': None})
        truth['新增成员'] += 1
        recompute(a)
    for i in pop(25):
        a = assets[i]
        if len(a['members']) > 2:
            del a['members'][rnd.randrange(len(a['members']))]
            truth['删除成员'] += 1
            recompute(a)
    for i in pop(30):
        a = assets[i]
        m = a['members'][rnd.randrange(len(a['members']))]
        m['sha'] = '%016x' % rnd.getrandbits(64)
        m['crc'] = '%08x' % rnd.getrandbits(32)
        truth['内容替换'] += 1
        recompute(a)
    for _ in range(8):
        assets.append(recompute({
            'gid': max(x['gid'] for x in assets if x) + 1, 'stem': 'new_asset_%d' % _,
            'kind': 'npc', 'dir': 'data/source/npc/newly', 'hub_path': '',
            'rels': {}, 'names': [],
            'members': [{'role': r, 'name': '%s_%d' % (r, _), 'sha': '%016x' % rnd.getrandbits(64),
                         'crc': '%08x' % rnd.getrandbits(32), 'type': r, 'w': None, 'h': None}
                        for r in ('model', 'skeleton', 'material', 'animation')]}))
    B['assets'] = [a for a in assets if a]
    os.makedirs(OUTD, exist_ok=True)
    p = os.path.join(OUTD, '示例_下一版.json')
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(B, f, ensure_ascii=False, separators=(',', ':'))
    out, _ = identity.compare(json.load(open(A, encoding='utf-8')), B)
    print('written %s (%.1f MB)' % (p, os.path.getsize(p) / 1e6))
    print('%-12s %8s %8s' % ('判定', '预期', '实测'))
    for k in ('仅重新打包', '结构变化', '内容微调', '资产消失', '新资产出现', '相同'):
        want = {'仅重新打包': truth['仅重新打包'],
                '结构变化': truth['新增成员'] + truth['删除成员'],
                '内容微调': truth['内容替换'], '资产消失': truth['消失'],
                '新资产出现': 8, '相同': None}.get(k)
        print('%-12s %8s %8d' % (k, want if want is not None else '-', out.get(k, 0)))


if __name__ == '__main__':
    main()
