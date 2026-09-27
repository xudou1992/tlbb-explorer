# -*- coding: utf-8 -*-
"""修复 browse.js:shell 展开损坏的两处补丁。"""
import io

p = r'D:/TLGL/tlbb-explorer/app/web/browse.js'
s = io.open(p, encoding='utf-8').read()

# 查看当前损坏区域,先定位
i = s.find('if (!tree) {')
assert i > 0, 'filter guard not found'
j = s.find('自动重试')
print('--- current filter guard region ---')
print(s[i-60:i+400])
print('--- retry region exists:', j > 0)
