# -*- coding: utf-8 -*-
"""
名字户口本 v2 —— 修两个口径问题

v1 的问题：
1. `n_systems` 对 `template_default.mtl` 报了 2734 —— 因为它是共享模板，
   被 2000+ 个不同目录引用。把"引用者目录数"当"系统数"是口径错误。
   ⇒ 改成两级：`n_dirs`（引用者目录数，事实）+ `system`（众数，只是**最常见**的那个）。
2. `dirs` 只取了顶层 `data`/`data/source` 这种粗粒度，没用。
   ⇒ 改成取 classify_dir 的结果（如 `data/effect/textures`），并保留 top 5。

另外补充两个对逆向真正有用的字段：
   `name_stem`   —— 去掉扩展名、去掉尾部编号，得到"系列名"（如 w1351_mask）
   `num_suffix`  —— 尾部编号（如 _c002 / _lf001），用于判断是同一系列的变体

**不改 fact 层语义，只改表达精度。**
"""
import os, sqlite3, sys, collections, re, json

SCRATCH = r"D:\TLGL\.scratch"
RES = os.path.join(SCRATCH, "resources.db")
OUT_DB = os.path.join(SCRATCH, "name_registry.db")
OUT_TXT = os.path.join(SCRATCH, "name_registry.txt")

buf = []
def p(s=""):
    buf.append(s); sys.stdout.write(s + "\n"); sys.stdout.flush()
def save():
    open(OUT_TXT, "w", encoding="utf-8").write("\n".join(buf))

rc = sqlite3.connect("file:%s?mode=ro" % RES.replace("\\", "/"), uri=True)

p("=" * 78); p("名字户口本 v2"); p("=" * 78); p()

named = {}
for h, nm, ty, pa in rc.execute("select hash,name,type,path from resources where name is not null and name<>''"):
    named.setdefault(nm, (h, ty, pa))
dang = {nm: (ext, nr, ns, cls) for nm, ext, nr, ns, cls in
        rc.execute("select name,ext,n_refs,n_src,cls from dangling")}
p("有实体名字 %d / 悬空名字 %d" % (len(named), len(dang)))

refmap = collections.defaultdict(list)
for nm, fh, fp in rc.execute("select name, from_hash, from_path from refs"):
    refmap[nm].append((fh, fp or ""))

def classify_dir(fp):
    parts = [x for x in fp.split("/") if x]
    if not parts: return ("<未知>", "")
    if len(parts) >= 4 and parts[0]=="data" and parts[1]=="effect" and parts[2]=="textures":
        return ("特效/" + parts[3], "data/effect/textures")
    if len(parts) >= 3 and parts[0]=="data" and parts[1]=="effect":
        return ("特效/" + parts[2], "data/effect")
    if len(parts) >= 4 and parts[0]=="data" and parts[1]=="source":
        return ("角色/" + parts[2] + "/" + parts[3], "data/source")
    if len(parts) >= 3 and parts[0]=="data" and parts[1]=="source":
        return ("角色/" + parts[2], "data/source")
    if parts[0] == "ui":
        return ("UI/" + (parts[1] if len(parts)>1 else ""), "ui")
    return (parts[0] + "/" + (parts[1] if len(parts)>1 else ""), parts[0])

# 系列名 / 编号
SER = re.compile(r"^(.*?)[_\-]?([a-z]{0,4}\d{2,5})$")
def split_series(stem):
    m = SER.match(stem)
    if m and len(m.group(1)) >= 3:
        return m.group(1), m.group(2)
    return stem, ""

def kind_of(ext):
    e = ext.lower()
    if e in (".tga",".png",".dds",".psd",".jpg",".jpeg",".webp"): return "贴图"
    if e in (".ani",".anis"): return "动画"
    if e == ".mesh": return "模型"
    if e == ".ske":  return "骨骼"
    if e == ".mtl":  return "材质"
    if e == ".pu":   return "参数"
    return "其它"

if os.path.exists(OUT_DB):
    os.remove(OUT_DB)
o = sqlite3.connect(OUT_DB)
o.executescript("""
CREATE TABLE name_card(
  name TEXT PRIMARY KEY, ext TEXT, kind TEXT,
  stem TEXT, series TEXT, num_suffix TEXT,
  refs INTEGER, n_src INTEGER,
  status TEXT, hash TEXT, res_type TEXT, res_path TEXT,
  d_cls TEXT,
  system TEXT,            -- 最常见的引用者系统（只是众数，不代表唯一归属）
  n_systems INTEGER,      -- 出现过几种"系统"标签
  n_dirs INTEGER,         -- 引用者目录数（事实）
  dir_kinds TEXT,         -- 去重后的目录类别（top 5, JSON）
  dirs_sample TEXT        -- 具体目录样本（top 5, JSON）
);
CREATE TABLE name_ref(name TEXT, from_hash TEXT, from_path TEXT, system TEXT);
CREATE TABLE name_system(system TEXT PRIMARY KEY, n_names INTEGER, n_refs INTEGER, n_dangling INTEGER);
CREATE TABLE name_series(series TEXT, ext TEXT, n_names INTEGER, n_refs INTEGER,
                         n_dangling INTEGER, example TEXT, PRIMARY KEY(series, ext));
CREATE TABLE name_meta(k TEXT PRIMARY KEY, v TEXT);
""")

cards = []
series_stat = collections.defaultdict(lambda: {"names": set(), "refs": 0, "dang": 0, "ex": ""})
sysstat = collections.defaultdict(lambda: {"names": set(), "refs": 0, "dang": set()})
refrows = []

for nm, rows in refmap.items():
    ext = "." + nm.rsplit(".", 1)[1] if "." in nm else ""
    stem = nm.rsplit(".", 1)[0]
    ser, num = split_series(stem)
    scnt = collections.Counter(); dk = set(); ds = set()
    for fh, fp in rows:
        k, d = classify_dir(fp)
        scnt[k] += 1
        if d: dk.add(d)
        if fp: ds.add(fp)
        refrows.append((nm, fh, fp, k))
    main_sys = scnt.most_common(1)[0][0] if scnt else "<未知>"
    is_named = nm in named
    h, ty, pa = named.get(nm, (None, None, None))
    dc = dang.get(nm)
    cards.append((nm, ext, kind_of(ext), stem, ser, num,
                  len(rows), len(set(fh for fh, _ in rows)),
                  "有实体" if is_named else "悬空",
                  h or "", ty or "", pa or "",
                  dc[3] if dc else "",
                  main_sys, len(scnt), len(ds),
                  json.dumps(sorted(dk)[:5], ensure_ascii=False),
                  json.dumps(sorted(ds)[:5], ensure_ascii=False)))
    st = series_stat[(ser, ext)]
    st["names"].add(nm); st["refs"] += len(rows)
    if not is_named:
        st["dang"] += 1; st["ex"] = nm
    for k, c in scnt.items():
        sysstat[k]["names"].add(nm); sysstat[k]["refs"] += c
        if not is_named: sysstat[k]["dang"].add(nm)

# 列数必须与 name_card 的 18 列**逐字对齐**（v1 这里写成 17 会直接报
# "table name_card has 18 columns but 17 values were supplied"）。
# 教训同 P3-B 的 raw.tsv：表结构与占位符数量要有一处断言，别靠手数。
CARD_COLS = 18
o.executemany("insert into name_card values (%s)" % ",".join("?" * CARD_COLS), cards)
o.executemany("insert into name_ref values (?,?,?,?)", refrows)
o.executemany("insert into name_system values (?,?,?,?)",
              [(k, len(v["names"]), v["refs"], len(v["dang"])) for k, v in sysstat.items()])
o.executemany("insert into name_series values (?,?,?,?,?,?)",
              [(k[0], k[1], len(v["names"]), v["refs"], v["dang"], v["ex"]) for k, v in series_stat.items()])
o.executemany("insert into name_meta values (?,?)", [
    ("生成时间", "2026-09-22"),
    ("来源", "resources.db: refs / dangling / resources"),
    ("口径", "只陈述事实：名字存在、被谁引用、是否对得上实体。不猜测归属。"),
    ("system 说明", "众数，仅表示'最常见的引用者系统'，不代表唯一归属"),
    ("名字总数", str(len(cards))),
    ("悬空名字数", str(sum(1 for c in cards if c[8]=="悬空"))),
    ("有实体名字数", str(sum(1 for c in cards if c[8]=="有实体"))),
    ("引用总条数", str(sum(c[6] for c in cards))),
    ("系列数", str(len(set(k[0] for k in series_stat)))),
])
for ix in ("status", "kind", "system", "series", "ext"):
    o.execute("CREATE INDEX ix_card_%s ON name_card(%s)" % (ix, ix))
o.execute("CREATE INDEX ix_ref_name ON name_ref(name)")
o.commit()

p()
p("库已写出 %s" % OUT_DB)
for t in ("name_card","name_ref","name_system","name_series"):
    p("  %-14s %6d 行" % (t, o.execute("select count(*) from %s" % t).fetchone()[0]))

p()
p("=" * 78)
p("一、贴图系列（series）—— 这是人工判读最有用的粒度")
p("=" * 78)
p("  %-40s %8s %8s %8s  %s" % ("系列", "名字数", "悬空", "引用", "示例"))
for r in o.execute("""select series, n_names, n_dangling, n_refs, example from name_series
                      where ext like '%.tga' or ext like '%.dds' or ext like '%.png'
                      order by n_names desc limit 40"""):
    p("  %-40s %8d %8d %8d  %s" % r)

p()
p("=" * 78)
p("二、悬空贴图的系统分布（引用者路径语法）")
p("=" * 78)
p("  %-36s %7s %8s %9s" % ("系统", "名字数", "悬空", "引用次数"))
for r in o.execute("""select system, count(*),
                             sum(case when status='悬空' then 1 else 0 end), sum(refs)
                      from name_card where kind='贴图'
                      group by 1 order by 2 desc limit 30"""):
    p("  %-36s %7d %8d %9d" % r)

p()
p("=" * 78)
p("三、修正说明：v1 的 n_systems=2734 是口径错误")
p("=" * 78)
r = o.execute("select name,n_systems,n_dirs,dir_kinds from name_card where name='template_default.mtl'").fetchone()
p("  template_default.mtl:")
p("     n_systems = %d （出现过多少种'系统'标签）" % r[1])
p("     n_dirs    = %d （被多少个不同目录引用 —— 这才是事实）" % r[2])
p("     引用者目录类别 = %s" % r[3])
p("  ⇒ 它是共享模板，被上千个目录引用。'系统数'本身没有意义，改名为 n_systems 并")
p("     明确标注'只是众数'，同时保留 n_dirs 作为事实。")
save()
o.close()
p()
p("人读清单：%s" % OUT_TXT)
