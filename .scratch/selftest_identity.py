"""Self-test for the asset identity layers: prove the judgement table.

Only one client is installed, so a "second version" has to be synthesised.  Each case
edits one asset in the snapshot the way a real patch would, recomputes the digests with
the same helpers the builder uses, and checks that compare() reaches the verdict the
user's table demands.

usage: python identity.py --selftest     (or)  python selftest_identity.py
"""
import copy
import json
import os
import sys

import identity

HERE = os.path.dirname(os.path.abspath(__file__))
SNAP = os.path.join(HERE, 'out', 'versionA.json')


def recompute(a):
    a['id_content'] = identity.id_content_of(a['members'])
    a['id_pack'] = identity.id_pack_of(a['members'])
    a['id_struct'] = identity.id_struct_of(a['members'], a.get('rels'))
    a['id_asset'] = identity.h16(a['id_content'], a['id_struct'])
    return a


def mutate(A, gid, fn):
    B = copy.deepcopy(A)
    for a in B['assets']:
        if a['gid'] == gid:
            fn(a)
            recompute(a)
    return B


def find(A, want):
    for a in A['assets']:
        if a['stem'] == want:
            return a['gid']
    raise SystemExit('sample asset %r not in snapshot' % want)


def verdict_for(out, lines, stem):
    for row in lines:
        if row[0] == stem:
            return row[2], row[3]
    return '相同', ''


CASES = [
    ('压缩方式改变', lambda a: [m.update(crc='deadbeef') for m in a['members']], '仅重新打包'),
    ('成员顺序打乱', lambda a: a['members'].reverse(), '相同'),
    ('新增 2 个动作', lambda a: a['members'].extend(
        [{'role': 'animation', 'name': 'new_clip_a.ani', 'sha': 'a' * 16, 'crc': '11111111',
          'type': 'ani', 'w': None, 'h': None},
         {'role': 'animation', 'name': 'new_clip_b.ani', 'sha': 'b' * 16, 'crc': '22222222',
          'type': 'ani', 'w': None, 'h': None}]), '结构变化'),
    ('删除 1 个子模型', lambda a: _drop_one(a, 'mesh'), '结构变化'),
    ('替换 1 张贴图内容', lambda a: _bump(a), '内容微调'),
    ('文件改名内容不变', lambda a: a['members'][0].update(name='renamed_body.mesh'), '相同'),
]





def _drop_one(a, role):
    for i in range(len(a['members']) - 1, -1, -1):
        if a['members'][i]['role'] == role:
            del a['members'][i]
            return


def _bump(a):
    for m in a['members']:
        if m['role'] == 'texture' or m['type'] == 'texture':
            m['sha'] = 'f' * 16
            return
    a['members'][0]['sha'] = 'e' * 16

def run(A, verbose=True):
    gid = find(A, 'w1351_boss_caoshuang')
    rows, ok = [], True
    for name, fn, want in CASES:
        B = mutate(A, gid, fn)
        out, lines = identity.compare(A, B)
        verdict, detail = verdict_for(out, lines, 'w1351_boss_caoshuang')
        passed = verdict == want
        ok = ok and passed
        rows.append((name, want, verdict, detail, '通过' if passed else '失败'))
    if verbose:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        print('样本资产：w1351_boss_caoshuang（gid %d）' % gid)
        print('%-18s %-12s %-12s %-26s %s' % ('改动', '应判定', '实判定', '差异说明', '结果'))
        for r in rows:
            print('%-18s %-12s %-12s %-26s %s' % r)
        print('总体：%s' % ('全部通过' if ok else '有失败'))
    return ok


if __name__ == '__main__':
    with open(SNAP, encoding='utf-8') as f:
        A = json.load(f)
    sys.exit(0 if run(A) else 1)
