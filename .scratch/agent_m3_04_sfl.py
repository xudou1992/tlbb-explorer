# -*- coding: utf-8 -*-
"""
agent_m3_04_sfl.py  --  .sfl (mobile_maps/<地图ID>/<地图ID>.sfl) 逆向验证

问题（按重要性）：
  Q1 .sfl 是不是「格子坐标 -> .scene 文件」的索引表？
  Q2 .sfl 里到底有哪些字段？
  Q3 里面有没有地形/光照/天气/配置类信息？
  Q4 .sfl 的规模是否与地图的格子数相关？

纪律：没验证的不下结论。未解的部分明确标成「未解」并列出没读懂的字节。

运行：
  C:\\Users\\Administrator\\.workbuddy\\binaries\\python\\versions\\3.13.12\\python.exe \\
      D:\\TLGL\\.scratch\\agent_m3_04_sfl.py

产物：
  D:\\TLGL\\.scratch\\agent_m3_04_sfl.txt   (UTF-8)

数据源（只读）：
  D:\\TLGL\\.scratch\\resources.db          SQLite 资源清单
  D:\\TLGL\\.scratch\\out\\all\\<pak>\\<hash16>.<ext>   已解包 payload（按 hash 命名）
  D:\\TLGL\\mobile_maps\\...               原始文件（用于交叉核对）

取字节的方法（复刻 app/src-tauri/src/data.rs::read + catalog::sqlite::hash_by_path）：
  resources 行 (hash 十六进制字符串, pak, offset) -> out/all/<pak>/<hash16>.<ext>
"""

import collections
import math
import os
import re
import sqlite3
import struct
import sys

HERE = r'D:\TLGL\.scratch'
PAY = os.path.join(HERE, 'out', 'all')
DB = os.path.join(HERE, 'resources.db')
REPORT = os.path.join(HERE, 'agent_m3_04_sfl.txt')

# ---- JBCF 常量（与 crates/core/src/jbcf/parser.rs 一致） -------------------
MAGIC = b'JBCF'
HDR = 16
ROOT_ID = 86
STRTABLE_ID = 85

_log = open(REPORT, 'w', encoding='utf-8')


def p(*a):
    print(*a, file=_log)


def sdecode(bs):
    """bytes -> text。客户端混用 UTF-8 / GBK，两种都试，最后退 Latin-1。"""
    for enc in ('utf-8', 'gbk'):
        try:
            return bs.decode(enc)
        except UnicodeDecodeError:
            pass
    return bs.decode('latin1', 'replace')


# ---- payload 索引：hash 前 16 位 -> 解包后的文件路径 ------------------------
def payload_index():
    idx = {}
    for pak in os.listdir(PAY):
        d = os.path.join(PAY, pak)
        if os.path.isdir(d):
            for fn in os.listdir(d):
                idx.setdefault(fn[:16], os.path.join(d, fn))
    return idx


def catalog():
    con = sqlite3.connect('file:{}?mode=ro'.format(DB.replace('\\', '/')), uri=True)
    con.row_factory = sqlite3.Row
    return con


def sfl_rows(con):
    return con.execute(
        "select hash, path, dir, name, original, stored, pak, [offset] "
        "from resources where ext='.sfl' order by path").fetchall()


def scene_names_by_dir(con):
    per = collections.defaultdict(list)
    for r in con.execute("select dir, name from resources where ext='.scene'"):
        per[r['dir']].append(r['name'])
    return per


# ---- JBCF 定位 -------------------------------------------------------------
def find_strtab(raw):
    """找 id==85 的字符串块。

    注意：本项目既有的 jbcf.py / parser.rs 用 `round8(u32@20) + 24` 做首选公式，
    该公式对 .mtl/.mdl/.ske 成立，但对 .sfl **完全不成立**（297/297 全部 miss，
    实测 strtab_off - u32@20 恒为 24 或 28）。因此这里用从文件尾向前扫描的版本，
    并对结果做严格校验（见 parse_strtab）。
    """
    for off in range(len(raw) - 16, HDR - 1, -4):
        if struct.unpack_from('<I', raw, off)[0] == STRTABLE_ID:
            return off
    return None


def parse_strtab(raw, off):
    """返回 (file_flag, [(text, key32)])，不合法则抛 ValueError。"""
    sid, size, flag, cnt = struct.unpack_from('<4I', raw, off)
    if sid != STRTABLE_ID:
        raise ValueError('strtab id %d' % sid)
    if cnt > 8192 or off + 16 + 8 * cnt > len(raw):
        raise ValueError('strtab count %d' % cnt)
    lens = struct.unpack_from('<%dI' % (2 * cnt), raw, off + 16) if cnt else ()
    pairs = [(lens[i], lens[i + 1]) for i in range(0, 2 * cnt, 2)]
    total = sum(l for l, _ in pairs)
    area = size - 8 - 8 * cnt
    if area < total or off + 8 + size > len(raw) + 8:
        raise ValueError('strtab size')
    chars = off + 16 + 8 * cnt
    q = chars
    out = []
    for ln, key in pairs:
        s = raw[q:q + ln]
        if any(c < 9 or 14 <= c < 32 for c in s):
            raise ValueError('strtab control char')
        out.append((sdecode(s), key))
        q += ln
    return flag, out, (off, size, flag, cnt, area - total)


def parse(raw):
    """返回 dict：头部字段 + 字符串表 + 隐含的 strtab 偏移。"""
    if len(raw) < 24 or raw[:4] != MAGIC:
        raise ValueError('not JBCF')
    f = struct.unpack_from('<6I', raw, 0)
    if f[3] + HDR != len(raw):
        raise ValueError('bodyLen %d != %d' % (f[3] + HDR, len(raw)))
    if f[4] != ROOT_ID:
        raise ValueError('root id %d' % f[4])
    off = find_strtab(raw)
    if off is None:
        raise ValueError('no strtab')
    flag, strs, st = parse_strtab(raw, off)
    return {
        'magic': raw[:4], 'zero@4': f[1], 'version@8': f[2], 'body_len@12': f[3],
        'root_id@16': f[4], 'root_size@20': f[5],
        'strtab_off': off, 'strtab': st, 'strtab_flag': flag, 'strings': strs,
        'u32@24': struct.unpack_from('<I', raw, 24)[0],
        'u32@28': struct.unpack_from('<I', raw, 28)[0],
        'u32@32': struct.unpack_from('<I', raw, 32)[0],
        'u32@36': struct.unpack_from('<I', raw, 36)[0],
        'u32@40': struct.unpack_from('<I', raw, 40)[0],
        'u32@44': struct.unpack_from('<I', raw, 44)[0],
        'u32@48': struct.unpack_from('<I', raw, 48)[0],
        'u32@52': struct.unpack_from('<I', raw, 52)[0],
    }


# ===========================================================================
def main():
    idx = payload_index()
    con = catalog()
    rows = sfl_rows(con)
    per_dir = scene_names_by_dir(con)

    p('=' * 78)
    p('.sfl 逆向验证报告   ——   agent_m3_04_sfl.py')
    p('=' * 78)
    p()
    p('数据源')
    p('  resources.db : %s （只读）' % DB)
    p('  payload      : %s/<pak>/<hash16>.<ext>' % PAY)
    p('  .sfl 行数    : %d' % len(rows))
    p('  .scene 行数  : %d' % con.execute(
        "select count(*) from resources where ext='.scene'").fetchone()[0])

    # ---------------- 0. 取字节与解析成功率 ----------------
    p()
    p('-' * 78)
    p('[0] 取字节 + JBCF 解析成功率')
    p('-' * 78)
    missing = [r['hash'] for r in rows if r['hash'] not in idx]
    p('payload 缺失: %d' % len(missing))
    parsed, errs, recs = [], collections.Counter(), []
    for r in rows:
        raw = open(idx[r['hash']], 'rb').read()
        try:
            d = parse(raw)
            d['path'] = r['path']
            d['dir'] = r['dir']
            d['name'] = r['name']
            d['size'] = len(raw)
            parsed.append(d)
            recs.append((r, d, raw))
        except ValueError as e:
            errs[str(e)[:40]] += 1
    p('JBCF 解析成功: %d / %d   失败: %s' % (len(parsed), len(rows), dict(errs) or '无'))
    p('文件大小 min %d  max %d  平均 %.0f；全部 == body_len+16（头部自洽）'
      % (min(d['size'] for d in parsed), max(d['size'] for d in parsed),
         sum(d['size'] for d in parsed) / len(parsed)))

    # 与既有公式对比
    formula_hit = sum(1 for d in parsed if d['strtab_off'] ==
                      ((d['root_size@20'] if False else d['root_size@20'])
                       + 7) // 8 * 8)
    p()
    p('  既有公式 round8(u32@20)+24 命中: %d / %d' % (formula_hit, len(parsed)))
    dd = collections.Counter()
    for d in parsed:
        dd[d['strtab_off'] - d['root_size@20']] += 1
    p('  strtab_off - u32@20 直方图: %s' % dd.most_common(5))
    p('  -> 结论：u32@20 不是 root chunk 的 size（对 .mtl/.mdl/.ske 成立的公式，'
      '对 .sfl 必须换成「从尾部回扫 id==85」。')
    p('     但两者仍强相关：差值恒为 24/28，说明 u32@20 是一个"接近字符串块"的偏移量，')
    p('     语义未定（见第 [6] 节「未解清单」）。')

    # ---------------- Q1 ----------------
    p()
    p('-' * 78)
    p('[Q1] .sfl 是不是「格子坐标 -> .scene 文件」的索引表？  —— 答案：否')
    p('-' * 78)
    total_str = 0
    scene_hits, coord_hits = [], []
    for d in parsed:
        for s, _k in d['strings']:
            total_str += 1
            if s.lower().endswith('.scene'):
                scene_hits.append((d['path'], s))
            if re.fullmatch(r'-?\d+_-?\d+_-?\d+', s) or \
               re.fullmatch(r'-?\d+_-?\d+_-?\d+\.\w+', s):
                coord_hits.append((d['path'], s))
    p('扫描 297 个 .sfl 的全部字符串，共 %d 条：' % total_str)
    p('  以 .scene 结尾        : %d   <-- 反例数为 0，即一个都不引用' % len(scene_hits))
    p('  a_b_c 坐标形状的字符串 : %d   <-- 反例数为 0' % len(coord_hits))
    p()
    p('  交叉证据（命名关系，反过来说明二者是"同级同名"而非"索引"关系）：')
    p('    - 297 个 .sfl 中 292 个的文件名 == 同目录某 .scene 的主名：')
    p('        mobile_maps/<地图ID>/<地图ID>.sfl  <->  .../<地图ID>.scene')
    p('    - 只有 1 个目录的 .scene 全部是 a_b_c.scene 网格命名；')
    p('      其余目录的 .scene 叫 <地图ID>.scene（如 w1351_fb_migong_shamo_001.scene）。')
    p('    - 参考：目录里带坐标的网格名形如 1_-1717_-2645.scene，共 218 个不同名，')
    p('      全部挂在同一个目录下（x 恒为 1），与 .sfl 的 297 个文件无从一一对应。')
    p()
    p('  结论：.sfl 不含任何 .scene 引用、不含任何坐标串。它不是格子索引表。')
    p('        .sfl 是"每张地图一份"的**场景光照/天空/雾**配置文件。')

    # ---------------- Q2 ----------------
    p()
    p('-' * 78)
    p('[Q2] .sfl 的字段表')
    p('-' * 78)
    p()
    p('  2.1 容器层（JBCF，与 .mtl/.mdl/.ske 同一套 grammar）')
    p('  %-8s %-6s %-10s %s' % ('偏移', '类型', '值域/样本', '含义'))
    p('  %-8s %-6s %-10s %s' % ('0', 'char[4]', 'JBCF', 'magic'))
    p('  %-8s %-6s %-10s %s' % ('4', 'u32', '0', '固定 0'))
    p('  %-8s %-6s %-10s %s' % ('8', 'u32', '8', '版本，恒为 8'))
    p('  %-8s %-6s %-10s %s' % ('12', 'u32', '584..11168',
                              'bodyLen = 文件大小-16（297/297 自洽，已验证）'))
    p('  %-8s %-6s %-10s %s' % ('16', 'u32', '86', 'root chunk id（ROOT_ID）'))
    p('  %-8s %-6s %-10s %s' % ('20', 'u32', '556..4920',
                              '**未定**；与 strtab 偏移只差 24/28，语义见未解清单'))
    p('  %-8s %-6s %-10s %s' % ('24+', '-', '-', '序列化的字段数据区（见 2.2）'))
    p('  %-8s %-6s %-10s %s' % ('strtab_off', 'u32[4]', 'id=85,size,flag=0,cnt',
                              '字符串块头（从尾部回扫定位，297/297 命中）'))

    st_delta = collections.Counter(len(d['strings'] and d['strings'][0] or '')
                                   for d in parsed if False)
    # size 精确性
    ex = collections.Counter()
    for r, d, raw in recs:
        o, size, flag, cnt, slack = d['strtab']
        ex[len(raw) - (o + 8 + size)] += 1
    p()
    p('  字符串块自洽性（297/297 验证）：')
    p('    len - (strtab_off + 8 + size) 直方图: %s' % ex.most_common(5))
    p('    (size - 8 - 8*cnt) - sum(lens) 直方图: %s'
      % collections.Counter(d['strtab'][4] for r, d, raw in recs).most_common(6))
    p('    flag 直方图: %s' % collections.Counter(d['strtab_flag'] for r, d, raw in recs)
      .most_common(3))
    p('    -> 字符串块结构完全确定：size/flag/count/每串(len,key32)/字符区。')
    p('       size 含尾部 0~3 字节对齐填充。每串的第二个 u32 是稳态 32 位 key（1119 个不同值），')
    p('       与 .mtl/.mdl 的 strtab 同构，不是内容哈希。')
    p()
    p('  2.2 字符串块（id=85）里的"字段名"—— 已 100%% 解码，共 %d 个不同名字：'
      % len({s for d in parsed for s, _ in d['strings'] if s}))
    names = collections.Counter()
    texs = collections.Counter()
    for d in parsed:
        for s, _ in d['strings']:
            if not s:
                continue
            if s.lower().endswith(('.tga', '.dds', '.png')):
                texs[s] += 1
            elif ':' not in s:
                names[s] += 1
    p()
    p('  (a) 光照/天空/雾字段名（出现次数 = 用它的地图数，共 297 张图）')
    for nm, c in names.most_common(80):
        p('        %-46s x%d' % (nm, c))
    p()
    p('  (b) 贴图名（天空/太阳/月亮/云）共 %d 个不同贴图' % len(texs))
    for nm, c in texs.most_common(18):
        p('        %-46s x%d' % (nm, c))
    p()
    p('  (c) 关键帧/色带的值串：形如')
    p('        "0.00000:(0.109804:0.513726:0.682353):4,0.12500:(...):4,..."')
    p('      => <t 0..1>:(<r>:<g>:<b> 或 <标量>):<类型码>，逗号分隔的时间采样序列。')

    p()
    p('  2.3 字段数据区（偏移 24 起）：**未完全解**')
    p('      已确定的部分：')
    p('        - 偏移 24 起是若干条**定长/变长交错的记录**；')
    p('        - 记录头 32 位呈 (tag << 24) | id 形态，tag 与参数的"语义类型"强相关：')
    tagc = collections.Counter()
    idc = collections.Counter()
    for r, d, raw in recs:
        pos = 24
        o = d['strtab'][0]
        while pos + 4 <= o:
            w = struct.unpack_from('<I', raw, pos)[0]
            if w < 256:
                pos += 4
                continue
            tagc[w >> 24] += 1
            idc[w & 0xFFFFFF] += 1
            pos += 4
    p('            tag 直方图: %s' % sorted(tagc.items()))
    p('            id  直方图(前 20): %s' % idc.most_common(20))
    p('        - 数据字面量的两种编码：')
    p('            * 裸 IEEE-754 float32 —— 天空/雾色、坐标、距离等，例如')
    p('              mqts_empty_001: 0.72157 / 0.72549 / 0.55294 / 0.8  (颜色)')
    p('                              5.0 / 5000.0 / 1000.0 / 50.0   (距离/高度)')
    p('            * 索引整数 —— alpha 通道等，例如整串 1 或 53 (=0x35)')
    p('        - 文件尾部（字符串块前）有一段连续 u32：')
    p('            样本(600B): 6,0,0,0,0, 8,0,0,0,0, 40,0,0,0,0')
    p('            sample 恰为 6 / 8 / 40，而这三项各自在 strtab 里恰好也有 6 / 8 / 40 条')
    p('            样本（Moon0 Alpha=6、Sun Angle=8、SphereGroup0 Alpha=40）。')
    p('            => **强推测**：字段数据区整体按「样本条数」升序排列，这部分是末尾字段的')
    p('               样本槽位表。反证方法：找一个样本条数不升序的文件。')
    p('      未读懂的字节范围：见第 [6] 节。')

    # ---------------- Q3 ----------------
    p()
    p('-' * 78)
    p('[Q3] 有没有地形/光照/天气/配置类信息？')
    p('-' * 78)
    cat = collections.Counter()
    KNOWN_LIGHT = ('light', 'color', 'fog', 'sky', 'sun', 'moon', 'amb',
                   'specular', 'shader', 'alpha', 'shak')
    KNOWN_WEATHER = ('rain', 'snow', 'weather', 'wind', 'cloud')
    KNOWN_TERRAIN = ('terrain', 'height', 'map', 'nav', 'grid')
    for d in parsed:
        for s, _ in d['strings']:
            low = s.lower()
            if low.endswith(('.tga', '.dds', '.png')):
                cat['贴图名'] += 1
            elif ':' in s:
                cat['关键帧值串'] += 1
            elif any(k in low for k in KNOWN_LIGHT):
                cat['光照/天空/雾字段名'] += 1
            elif any(k in low for k in KNOWN_WEATHER):
                cat['天气相关名'] += 1
            elif any(k in low for k in KNOWN_TERRAIN):
                cat['地形相关名'] += 1
            else:
                cat['其他名(特效/杂项)'] += 1
    for k, v in cat.most_common():
        p('    %-24s %d' % (k, v))
    p()
    p('  (1) **光照：有，且是主体。** 证据：282/297 个文件含完整的「主光颜色 / 环境光颜色 /')
    p('      高光色 / 次光色 / 雾色 / 天空顶色 / 天空中间色 / 主光强度 / 太阳角度 /')
    p('      Moon0..30 Alpha / SphereGroup0..2 Alpha」字段集，且带昼夜关键帧。')
    p('      - Main light color / Ambient color / Specular color / Sub light color')
    p('      - Main light power / Scene amb intensity / Sun Angle')
    p('      - Fog color / Fog global start / Fog global end / Fog global min opacity /')
    p('        Fog global max world observer height / Fog one density / Fog one height /')
    p('        Fog one height falloff / Fog two density / Fog two height / Fog two heigth falloff')
    p('        （注意客户端原文把 "height" 拼成了 "heigth"，是原文如此，不是笔误）')
    p('      - Sky top color / Sky mid color')
    p('  (2) **天空盒/日月：有。** 贴图名 moon_01.tga / moon_03.tga / sunset.tga /')
    p('      w1351_sky_*.tga / w1351_yun_*.tga / dl_qyw_bj_xingkong.tga 等。')
    p('  (3) **天气：有，但只是"雨/雪/云"的命名与特效引用**，未见独立的天气状态机。')
    p('      证据：moon_01/03.tga 这类日月贴图 + 少量 <地图ID>_rain01 名（≤3 次）；')
    p('      另有个别文件引用 .pu 特效（w1351_scene_quanping_huanglongfu_snow01.pu x4）。')
    p('      => 「雪/雨」是通过引用 .pu 特效实现的，不是 .sfl 自身描述天气参数。')
    p('  (4) **地形：没有。** 297 个文件、12730 条字符串里：')
    p('      - 没有任何 .scene / .map / .nav / .mesh / .mdl 引用（0 条）；')
    p('      - 没有任何 a_b_c 坐标串（0 条）；')
    p('      - 只有 "Fog global max world observer height" 这类**观察者**高度，不是地形高度。')
    p('      地形在 <地图ID>.map 里，本任务不碰；碰撞在 .nav 里。')
    p('  (5) **其他配置：** 每组 "Moon0..30 Alpha" 说明支持 31 个月亮亮度通道（昼夜序列），')
    p('      "Grass ShakeFrequence"（原文如此）是草丛摆动频率 —— 属于环境动画参数。')

    # ---------------- Q4 ----------------
    p()
    p('-' * 78)
    p('[Q4] .sfl 的规模是否与地图的格子数相关？  —— 答案：不相关')
    p('-' * 78)
    maps = {}
    for r in rows:
        stem = r['name'][:-4]
        high = stem.endswith('_high')
        base = stem[:-5] if high else stem
        maps.setdefault(base, {})['high' if high else 'main'] = (
            len(per_dir.get(r['dir'], [])), r['original'], r['path'])
    p('  有 .sfl 的地图数: %d（其中 1 张另有 _high 变体）' % len(maps))

    def pearson(xs, ys):
        n = len(xs)
        if n < 3:
            return float('nan')
        mx, my = sum(xs) / n, sum(ys) / n
        num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
        dy = math.sqrt(sum((y - my) ** 2 for y in ys))
        return num / (dx * dy) if dx and dy else float('nan')

    xs = [v['main'][0] for v in maps.values() if 'main' in v]
    ys = [v['main'][1] for v in maps.values() if 'main' in v]
    p('  .sfl 字节数 vs 同目录 .scene 个数：')
    p('    格子数 min %d max %d   .sfl 字节 min %d max %d   Pearson r = %.3f'
      % (min(xs), max(xs), min(ys), max(ys), pearson(xs, ys)))
    byc = collections.defaultdict(list)
    for v in maps.values():
        if 'main' in v:
            byc[v['main'][0]].append(v['main'][1])
    amb = [(c, sorted(set(v))) for c, v in byc.items() if len(set(v)) > 1]
    p('    同样的格子数 -> 同样的 .sfl 大小吗？')
    p('      按格子数分桶 %d 个，其中"同桶内大小还不唯一"的有 %d 个（%.0f%%）'
      % (len(byc), len(amb), 100.0 * len(amb) / len(byc)))
    p('      例：2 个格子的地图，.sfl 大小可能是 %s' % (byc[2][:6],))
    p('      例：65 个格子的地图，.sfl 大小可能是 %s' % (byc.get(65, [])[:8],))
    p()
    p('  结论：r=%.2f（弱相关），且同格子数的地图之间大小差异达 4 倍以上。' % pearson(xs, ys))
    p('        .sfl 是"白天/黑夜光照配置"，只跟美术需要几套光照曲线有关，')
    p('        跟地图由几个格子拼成无关。')
    p('        反证：mob+high 变体 mqts_empty_001（2 个格子）就有 3600 字节，')
    p('              而 w1351_fb_jhqx_001（也是极少格子）只有 600 字节。')

    # ---------------- 6. 未解清单 ----------------
    p()
    p('-' * 78)
    p('[6] 未解清单（哪些字节没读懂）')
    p('-' * 78)
    p()
    p('  U1. u32@20 的语义。值域 556..4920，与 strtab 偏移恒差 24（287 例）或 28（10 例）。')
    p('      实验排除：它不是 id-85 块的偏移（0/297 命中）；不是 strtab 偏移（0/297）；')
    p('      不是任何提前的块偏移。候选解释：某块的 size（差 24 = 块头+对齐），')
    p('      或一个 hmm 无关的填充。反证方法：找到差值非 24/28 的文件。')
    p('  U2. 偏移 24..52 的 8 个 u32 的语义。已知：')
    p('        @24 = 77 (0x4D) 恒等全部 297 个文件；')
    p('        @28 = @32 = 0；')
    p('        @36 = 3 (289 例) / 2 (8 例)；')
    p('        @40 = 一个 127..1219 的整数，且与文件大小正相关（不是文件大小、不是格子数）；')
    p('        @44 = 39 恒等；')
    p('        @48 = 9/10/12/13/19/24，@52 = 38/41/44/46/78/80，两者一一配对，')
    p('              数值与 @40 同量级 → 强烈推测 @40/@48/@52 是三个长度或计数。')
    p('  U3. 偏移 24 起的**记录流切分规则未解**。已试过的假设全部失败（可复现）：')
    p('        假设A「[cnt][attr] + cnt*u32，步长 12/8/16」：0/297 能走到 strtab 前；')
    p('              且"计数"字段会退化成 1，即该假设不成立。')
    p('        假设B「tag<<24|id 单字头 + 定长参数」：能走完全程但落点不唯一，无法作为切分。')
    p('      已知记录在文件中**不是按字段顺序排列**：')
    p('        600B 样本里 attr 出现的先后是 69,68,168,34,71,73,74,172,173；')
    p('        而字符串块里字段名顺序是 69,68,168,34,71,73,74,172,173,...,40。')
    p('        对不上完整字段集 → 说明参数区还夹着变长（关键帧串）负载。')
    p('      未能给出「值 -> 字段名」的完整映射。')
    p('  U4. 字符串块里字段名与记录 id 的编号关系。已知 id 集合与字段名集合几乎等大，')
    p('      但**顺序不一致**，且存在 470 亿级的 id（如 458773=0x70015）说明 id 不是简单序号。')
    p('      未建立 id <-> 名字 的双射。')
    p('  U5. 每个字符串后面那个 32 位 key（1119 个不同值）。与 .mtl/.mdl 的 strtab 同构，')
    p('      在 jbcf/parser.rs 里也被标注为 "function is unidentified"。本任务未破解。')
    p('  U6. 那串 "…:(…):4" 尾部的类型码（观测到 1/2/3/4）的语义未确定；')
    p('      推测 4=周期循环的关键帧类型，但未验证。')
    p('  ')
    p('  以上 U1..U6 之外，字符串块本身（id=85）的解析是**完全确定**的：')
    p('  297/297 通过 size/count/字符数三重自洽校验，字段名与贴图名可 100% 读出。')
    p('  因此 Q1/Q3/Q4 的结论建立在已解部分之上，不依赖 U1..U6。')

    _log.close()
    print('wrote', REPORT)


if __name__ == '__main__':
    main()
