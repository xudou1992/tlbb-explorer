# -*- coding: utf-8 -*-
"""M1 前置探针：.mdl 是 JBCF，把里面字符串全抽出来，看模型组成清单长什么样。"""
import sqlite3, sys
sys.path.insert(0, r'D:\TLGL\.scratch')
import cramjam
from pakunpack2 import REC, crc, decrypt
from jbcf import parse as jbcf_parse

rc = sqlite3.connect('file:D:/TLGL/.scratch/resources.db?mode=ro', uri=True)

NAMES = [
    'w1351_nan_s_yifu_new_dingchunqiu.mdl',   # 玩家男装
    'w1351_pets_rongyanjushou_b8.mdl',        # 宠物
    'w1351_zuoqi_menghuan.mdl',               # 坐骑
]

out = []
for nm in NAMES:
    row = rc.execute("select hash, pak, offset, original, stored, flags, method from resources where name=?",
                     (nm,)).fetchone()
    if not row:
        out.append('%s: 目录里没有' % nm)
        continue
    h, pak, off, original, stored, flags, method = row
    with open(r'D:\TLGL' + '\\' + pak + '.pak', 'rb') as f:
        f.seek(off)
        raw = f.read(stored)
    h_i = int(h, 16)
    body = decrypt(h_i, stored, raw) if (flags & 4) else raw
    if flags & 1:  # manifest 前缀
        pl = body[0]
        body = body[1 + pl + 16:]
    data = bytes(cramjam.snappy.decompress_raw(body)) if method == 0x33 else body
    out.append('=' * 76)
    out.append('%s   %s off=%d stored=%d -> %dB (flags=%x method=%x)' % (nm, pak, off, stored, len(data), flags, method))
    try:
        a, off_s, flag, strings = jbcf_parse(data)
        out.append('JBCF ok: strtab@%d count=%d' % (off_s, len(strings)))
        for s, sh in strings:
            out.append('   %r' % s)
    except ValueError as e:
        out.append('JBCF 解析失败: %s   头: %r' % (e, data[:48]))

report = '\n'.join(out)
open(r'D:\TLGL\.scratch\mdl_probe_out.txt', 'w', encoding='utf-8').write(report)
print(report[:2000])
