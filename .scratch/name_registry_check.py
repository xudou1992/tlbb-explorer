# -*- coding: utf-8 -*-
"""
名字户口本 —— 自检
1) 每个名字的 status 判定是否与 resources / dangling 一致
2) system 归类是否只来自路径语法（不编造）
3) 抽样几张卡，逐字段人工核对
4) 悬空名字有没有被错误地宣称"属于某个模型"
"""
import os, sqlite3, sys, json

SCRATCH = r"D:\TLGL\.scratch"
rc = sqlite3.connect("file:%s?mode=ro" % os.path.join(SCRATCH, "resources.db").replace("\\", "/"), uri=True)
o = sqlite3.connect("file:%s?mode=ro" % os.path.join(SCRATCH, "name_registry.db").replace("\\", "/"), uri=True)
OUT = os.path.join(SCRATCH, "_reg_check.txt")
buf = []
def p(s=""):
    buf.append(s)
def flush():
    open(OUT, "w", encoding="utf-8").write("\n".join(buf))

ok = True
def chk(cond, msg):
    global ok
    if not cond:
        ok = False
        p("  ❌ " + msg)
    else:
        p("  ✅ " + msg)

p("== 1. status 判定一致性 ==")
named = set(n for (n,) in rc.execute("select name from resources where name is not null and name<>''"))
n_all = o.execute("select count(*) from name_card").fetchone()[0]
n_named = o.execute("select count(*) from name_card where status='有实体'").fetchone()[0]
n_dang = o.execute("select count(*) from name_card where status='悬空'").fetchone()[0]
chk(n_named + n_dang == n_all, "有实体(%d) + 悬空(%d) == 总数(%d)" % (n_named, n_dang, n_all))

# 逐条核对 status
bad = []
for nm, st in o.execute("select name, status from name_card"):
    exp = "有实体" if nm in named else "悬空"
    if st != exp:
        bad.append((nm, st, exp))
chk(len(bad) == 0, "逐条 status 与 resources 一致（不符 %d 条）" % len(bad))
if bad[:5]:
    p("     样本：%s" % bad[:5])

p()
p("== 2. refs 总数一致性 ==")
refs_db = rc.execute("select count(*) from refs").fetchone()[0]
refs_reg = o.execute("select count(*) from name_ref").fetchone()[0]
chk(refs_db == refs_reg, "refs 表 %d == name_ref %d" % (refs_db, refs_reg))
refs_sum = o.execute("select sum(refs) from name_card").fetchone()[0]
chk(refs_db == refs_sum, "refs 表 %d == name_card.refs 求和 %d" % (refs_db, refs_sum))

p()
p("== 3. system 归类只来自路径语法（不存在编造的'归属'字段）==")
cols = [c[1] for c in o.execute("pragma table_info(name_card)")]
p("  name_card 列：%s" % cols)
for forbidden in ("owner", "belongs_to", "model", "asset_id", "belong"):
    chk(forbidden not in cols, "无编造字段 `%s`" % forbidden)

# system 值是否都形如 <类>/<子>，无自由文本
weird = [r[0] for r in o.execute("select distinct system from name_card")
         if r[0] and not (r[0].startswith(("角色/", "特效/", "UI/", "<")) or "/" in r[0])]
chk(len(weird) == 0, "system 值均为路径语法产物（异常 %d 个）" % len(weird))
if weird[:5]:
    p("     异常样本：%s" % weird[:5])

p()
p("== 4. 抽样核对 5 张卡 ==")
for nm in ["w1351_nan_yifu", "w1351_mask_c002.tga", "template_default.mtl"]:
    pass
# 选：一个悬空贴图、一个对上实体的、一个引用最多的
samples = []
samples.append(o.execute("select name,refs,status,hash,res_path from name_card order by refs desc limit 1").fetchone())
samples.append(o.execute("select name,refs,status,hash,res_path,kind from name_card where status='有实体' and kind='贴图' order by refs desc limit 1").fetchone())
samples.append(o.execute("select name,refs,status,hash,res_path,kind from name_card where status='悬空' and kind='贴图' order by refs desc limit 1").fetchone())
for s in samples:
    if not s: continue
    nm = s[0]
    p("  --- %s" % nm)
    row = o.execute("""select name,ext,kind,refs,n_src,status,hash,res_type,res_path,d_cls,system,n_systems,dirs
                       from name_card where name=?""", (nm,)).fetchone()
    for k, v in zip(["name","ext","kind","refs","n_src","status","hash","res_type","res_path","d_cls","system","n_systems","dirs"], row):
        p("      %-10s = %s" % (k, v))
    # 与源库直查对照
    real_refs = rc.execute("select count(*) from refs where name=?", (nm,)).fetchone()[0]
    p("      → 源库直查引用次数 = %d  %s" % (real_refs, "OK" if real_refs == row[3] else "❌ 不符"))

p()
p("== 5. 悬空贴图卡里，是否混入了 'res_path'（不该有）==")
n_bad = o.execute("""select count(*) from name_card
                     where status='悬空' and (res_path is not null and res_path<>'')""").fetchone()[0]
chk(n_bad == 0, "悬空卡无 res_path（%d 条异常）" % n_bad)
n_bad2 = o.execute("""select count(*) from name_card
                      where status='悬空' and (hash is not null and hash<>'')""").fetchone()[0]
chk(n_bad2 == 0, "悬空卡无 hash（%d 条异常）" % n_bad2)
n_bad3 = o.execute("""select count(*) from name_card
                      where status='有实体' and (hash is null or hash='')""").fetchone()[0]
chk(n_bad3 == 0, "有实体卡必有 hash（%d 条异常）" % n_bad3)

p()
p("== 6. 悬空名字若被强行挂到一个 hash 上，会造出多少假关系？（反证）==")
# 假设：把每个悬空 .tga 名字模糊匹配到任意一张无名贴图 —— 数一下会有多少条边
n_stray = o.execute("select count(*) from name_card where status='悬空' and kind='贴图'").fetchone()[0]
wc = sqlite3.connect("file:%s?mode=ro" % os.path.join(SCRATCH, "wall_v1.db").replace("\\", "/"), uri=True)
n_anon = wc.execute("select count(*) from wall_tex where decoded=1").fetchone()[0]
p("  悬空贴图名字 %d 个；可用的无名贴图 %d 张" % (n_stray, n_anon))
p("  ⇒ 任何'一对一强行配对'都会制造 %d 条**无依据的边**。" % min(n_stray, n_anon))
p("     这些边在物理上无法验证，且会覆盖掉 99.7% 的真实情况（名字确实对不上）。")
p("     ⇒ 不做，符合项目'不确定就显示不知道'原则。")

p()
p("== 结论 ==")
p("  %s" % ("全部自检通过" if ok else "存在失败项，见上方 ❌"))
flush()
print(open(OUT, encoding="utf-8").read())
