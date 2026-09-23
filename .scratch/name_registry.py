# -*- coding: utf-8 -*-
"""
P3-B-2 B. 「名字户口本」—— 贴图命名档案生成器

**做什么**
把客户端自己留下的贴图名字，做成一份可判读的档案表。每个名字一行，带：
    出现次数 / 类型 / 所属系统 / 是否悬空 / 有没有对应 hash / 谁引用了它 / 引用者路径

**为什么不猜主人**
hash 侧已证明没有路径（.tga 名字→实体命中率 0.3%）。所以这份档案**只陈述事实**：
名字存在、被谁引用、对不上实体。不编造"它属于哪个模型的贴图"。

**数据源（全只读）**
  resources.db : refs(name, kind, from_hash, from_path) / dangling / resources(name,hash)
  wall_v1.db   : wall_tex(hash,...)  —— 只用来核对"名字有没有对应的无名贴图候选"

**输出**
  name_registry.db   三张表 name_card / name_ref / name_bucket
  name_registry.txt  人读清单
"""
import os, sqlite3, sys, collections, re, json

SCRATCH = r"D:\TLGL\.scratch"
RES = os.path.join(SCRATCH, "resources.db")
WALL = os.path.join(SCRATCH, "wall_v1.db")
OUT_DB = os.path.join(SCRATCH, "name_registry.db")
OUT_TXT = os.path.join(SCRATCH, "name_registry.txt")

buf = []
def p(s=""):
    buf.append(s)
    sys.stdout.write(s + "\n")
    sys.stdout.flush()
def save_txt():
    with open(OUT_TXT, "w", encoding="utf-8") as f:
        f.write("\n".join(buf))

rc = sqlite3.connect("file:%s?mode=ro" % RES.replace("\\", "/"), uri=True)
wc = sqlite3.connect("file:%s?mode=ro" % WALL.replace("\\", "/"), uri=True)

# ---------------------------------------------------------------- 0. 载入事实
p("=" * 78)
p("名字户口本 —— 贴图命名档案")
p("=" * 78)
p()

# 有实体的名字（client 命名表解出来的）
named = {}          # name -> (hash, type, path)
for h, nm, ty, pa in rc.execute("""
        select hash, name, type, path from resources
        where name is not null and name<>''"""):
    named.setdefault(nm, (h, ty, pa))
p("resources 里有实体的名字：%d" % len(named))

# dangling：悬空名字
dang = {}
for nm, ext, nrefs, nsrc, cls in rc.execute("select name, ext, n_refs, n_src, cls from dangling"):
    dang[nm] = (ext, nrefs, nsrc, cls)
p("dangling 里悬空的名字：%d" % len(dang))

# refs：谁引用了这个名字
refmap = collections.defaultdict(list)   # name -> [(from_hash, from_path)]
refcnt = collections.Counter()
for nm, fh, fp in rc.execute("select name, from_hash, from_path from refs"):
    refmap[nm].append((fh, fp or ""))
    refcnt[nm] += 1
p("refs 里出现过的名字：%d（共 %d 条引用）" % (len(refmap), sum(refcnt.values())))
p()

# ---------------------------------------------------------------- 1. 系统分类
def classify_dir(fp):
    """从引用者路径推断'所属系统'。只做**路径语法**的机械归类，不做语义猜测。"""
    parts = [x for x in fp.split("/") if x]
    if not parts:
        return ("<未知>", "")
    # data/effect/textures/<系统>/...
    if len(parts) >= 4 and parts[0] == "data" and parts[1] == "effect" and parts[2] == "textures":
        return ("特效/" + parts[3], "data/effect/textures")
    if len(parts) >= 3 and parts[0] == "data" and parts[1] == "effect":
        return ("特效/" + parts[2], "data/effect")
    # data/source/<类>/<角色>/...
    if len(parts) >= 4 and parts[0] == "data" and parts[1] == "source":
        return ("角色/" + parts[2] + "/" + parts[3], "data/source")
    if len(parts) >= 3 and parts[0] == "data" and parts[1] == "source":
        return ("角色/" + parts[2], "data/source")
    if parts[0] == "ui":
        return ("UI/" + (parts[1] if len(parts) > 1 else ""), "ui")
    return (parts[0] + "/" + (parts[1] if len(parts) > 1 else ""), parts[0])

# ---------------------------------------------------------------- 2. 建卡
p("=" * 78)
p("一、按扩展名汇总（悬空率）")
p("=" * 78)
by_ext = collections.defaultdict(lambda: {"names": 0, "resolved": 0, "dangling": 0, "refs": 0})
for nm in refmap:
    ext = ""
    if "." in nm:
        ext = "." + nm.rsplit(".", 1)[1]
    s = by_ext[ext]
    s["names"] += 1
    s["refs"] += refcnt[nm]
    if nm in named:
        s["resolved"] += 1
    else:
        s["dangling"] += 1
p("  %-10s %8s %9s %9s %8s %9s" % ("ext", "名字数", "对上实体", "悬空", "悬空率", "引用次数"))
for ext, s in sorted(by_ext.items(), key=lambda kv: -kv[1]["refs"]):
    rate = 100.0 * s["dangling"] / max(1, s["names"])
    p("  %-10s %8d %9d %9d %7.1f%% %9d" % (ext, s["names"], s["resolved"], s["dangling"], rate, s["refs"]))
save_txt()

# ---------------------------------------------------------------- 3. 关键：贴图名字卡
p()
p("=" * 78)
p("二、贴图名字档案（.tga/.png/.dds）—— 悬空的那些")
p("=" * 78)

TEX_EXT = (".tga", ".png", ".dds", ".psd")
tex_names = [nm for nm in refmap if nm.lower().endswith(TEX_EXT)]
tex_dangling = [nm for nm in tex_names if nm not in named]
p("  贴图类名字 %d 个，其中悬空 %d 个（%.1f%%）"
  % (len(tex_names), len(tex_dangling), 100.0 * len(tex_dangling) / max(1, len(tex_names))))

# 按"所属系统"归类
sysb = collections.defaultdict(lambda: {"names": set(), "refs": 0})
for nm in tex_dangling:
    seen = set()
    for fh, fp in refmap[nm]:
        k, _ = classify_dir(fp)
        if k in seen:
            continue
        seen.add(k)
        sysb[k]["names"].add(nm)
        sysb[k]["refs"] += 1
p()
p("  悬空贴图名字，按'引用者所在系统'归类（前 40）：")
p("  %-40s %7s %8s" % ("系统（来自引用者路径）", "名字数", "引用次数"))
for k, v in sorted(sysb.items(), key=lambda kv: -len(kv[1]["names"]))[:40]:
    p("  %-40s %7d %8d" % (k, len(v["names"]), v["refs"]))
save_txt()

# ---------------------------------------------------------------- 4. 写库
if os.path.exists(OUT_DB):
    os.remove(OUT_DB)
o = sqlite3.connect(OUT_DB)
o.executescript("""
CREATE TABLE name_card(
  name      TEXT PRIMARY KEY,
  ext       TEXT,
  kind      TEXT,      -- 贴图 / 动画 / 模型 / 骨骼 / 材质 / 其它
  refs      INTEGER,   -- 被引用次数
  n_src     INTEGER,   -- 不同引用者数
  status    TEXT,      -- '有实体' / '悬空'
  hash      TEXT,      -- 对上实体时的 hash，否则空
  res_type  TEXT,      -- 对上实体时的 resources.type
  res_path  TEXT,      -- 对上实体时的客户端原文路径
  d_cls     TEXT,      -- dangling 的 shared/unique
  system    TEXT,      -- 主要引用者系统（众数）
  n_systems INTEGER,   -- 出现在几个系统里
  dirs      TEXT       -- 去重后的引用者目录（前 5 个，JSON）
);
CREATE TABLE name_ref(
  name      TEXT,
  from_hash TEXT,
  from_path TEXT,
  system    TEXT
);
CREATE TABLE name_system(
  system   TEXT PRIMARY KEY,
  n_names  INTEGER,
  n_refs   INTEGER,
  n_dangling INTEGER
);
CREATE TABLE name_meta(k TEXT PRIMARY KEY, v TEXT);
""")

def kind_of(ext):
    e = ext.lower()
    if e in (".tga", ".png", ".dds", ".psd", ".jpg", ".jpeg", ".webp"):
        return "贴图"
    if e == ".ani" or e == ".anis":
        return "动画"
    if e == ".mesh":  return "模型"
    if e == ".ske":   return "骨骼"
    if e == ".mtl":   return "材质"
    if e == ".pu":    return "参数"
    return "其它"

cards = []
sysstat = collections.defaultdict(lambda: {"names": set(), "refs": 0, "dang": set()})

for nm, rows in refmap.items():
    ext = "." + nm.rsplit(".", 1)[1] if "." in nm else ""
    dirs = []
    scnt = collections.Counter()
    for fh, fp in rows:
        k, d = classify_dir(fp)
        scnt[k] += 1
        if d:
            dirs.append(d)
    main_sys = scnt.most_common(1)[0][0] if scnt else "<未知>"
    is_named = nm in named
    h, ty, pa = named.get(nm, (None, None, None))
    dc = dang.get(nm)
    cards.append((
        nm, ext, kind_of(ext), refcnt[nm], len(set(fh for fh, _ in rows)),
        "有实体" if is_named else "悬空",
        h or "", ty or "", pa or "",
        dc[3] if dc else "",
        main_sys, len(scnt),
        json.dumps(sorted(set(dirs))[:5], ensure_ascii=False),
    ))
    for k in scnt:
        sysstat[k]["names"].add(nm)
        sysstat[k]["refs"] += scnt[k]
        if not is_named:
            sysstat[k]["dang"].add(nm)

o.executemany("insert into name_card values (%s)" % ",".join("?" * 13), cards)
o.executemany("insert into name_ref values (?,?,?,?)",
              [(nm, fh, fp, classify_dir(fp)[0]) for nm, rows in refmap.items() for fh, fp in rows])
o.executemany("insert into name_system values (?,?,?,?)",
              [(k, len(v["names"]), v["refs"], len(v["dang"])) for k, v in sysstat.items()])
o.executemany("insert into name_meta values (?,?)", [
    ("生成时间", "2026-09-22"),
    ("来源", "resources.db: refs / dangling / resources"),
    ("口径", "只陈述事实：名字存在、被谁引用、是否对得上实体；不猜测归属"),
    ("名字总数", str(len(cards))),
    ("悬空名字数", str(sum(1 for c in cards if c[5] == "悬空"))),
    ("有实体名字数", str(sum(1 for c in cards if c[5] == "有实体"))),
    ("引用总条数", str(sum(c[3] for c in cards))),
])
o.execute("CREATE INDEX ix_card_status ON name_card(status)")
o.execute("CREATE INDEX ix_card_kind ON name_card(kind)")
o.execute("CREATE INDEX ix_card_system ON name_card(system)")
o.execute("CREATE INDEX ix_ref_name ON name_ref(name)")
o.commit()

p()
p("=" * 78)
p("三、库已写出 %s" % OUT_DB)
p("=" * 78)
for t in ("name_card", "name_ref", "name_system"):
    n = o.execute("select count(*) from %s" % t).fetchone()[0]
    p("  %-14s %d 行" % (t, n))

p()
p("  按 kind 分（name_card）：")
for r in o.execute("""select kind, count(*), sum(refs),
                             sum(case when status='悬空' then 1 else 0 end)
                      from name_card group by 1 order by 2 desc"""):
    p("     %-8s 名字 %6d  引用 %7d  悬空 %6d" % r)

p()
p("  贴图类悬空名字，按 system 排（前 25）：")
for r in o.execute("""select system, count(*), sum(refs) from name_card
                      where kind='贴图' and status='悬空'
                      group by 1 order by 2 desc limit 25"""):
    p("     %-40s %6d %7d" % r)

o.close()
save_txt()
p()
p("人读清单：%s" % OUT_TXT)
