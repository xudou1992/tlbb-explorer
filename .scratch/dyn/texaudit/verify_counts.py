# -*- coding: utf-8 -*-
"""贴图侧账面自洽复核（只读）。

纪律：db 以 mode=ro 打开；不写 .scratch/resources.db；不写覆盖表；
所有产物只落在本目录。输出为 UTF-8 文件（控制台是 GBK，中文不能直接打）。
"""
import hashlib
import json
import os
import sqlite3
import sys
from collections import Counter

ROOT = "D:/TLGL"
DB = os.path.join(ROOT, ".scratch/resources.db")
REHEARSAL = os.path.join(ROOT, ".scratch/resources_rehearsal.db")
BATCH = os.path.join(ROOT, ".scratch/uvfit_batch")
RESULTS = os.path.join(BATCH, "results")
MANIFEST = os.path.join(BATCH, "manifest.json")
OVERRIDE = os.path.join(ROOT, ".scratch/model_texture_override.json")
OUT = os.path.join(ROOT, ".scratch/dyn/texaudit/verify_counts.txt")

# 与 Rust 侧常量逐字对齐（preview/uvfit_batch.rs:53-67）
HIGH_SCORE, HIGH_COVER, MID_SCORE, LOW_SCORE = 6.0, 0.3, 3.0, 1.2
DEG_ADJ, DEG_COVER = 1.3, 0.9
POOL_SQL = ("select hash,width,height,codec,mips from resources "
            "where type='texture' and path is null and width>=512 and height>=512 "
            "and codec in ('RGBA32','BC3') and mips>=4 order by original desc")

lines = []


def say(s=""):
    lines.append(s)


def ro(path):
    return sqlite3.connect("file:%s?mode=ro" % path.replace("\\", "/"), uri=True)


def grade_v2(top_adjusted, coverage, has_uv):
    """复刻 grade()：v2 用 adjusted 刻度走同三个阈值。"""
    if top_adjusted is None:
        return "unknown"
    s = top_adjusted
    if s >= HIGH_SCORE and (coverage or 0.0) >= HIGH_COVER:
        return "high"
    if s >= MID_SCORE:
        return "mid"
    if s >= LOW_SCORE:
        return "low"
    return "unknown"


def unknown_cause(has_uv, top_adjusted, coverage):
    if not has_uv:
        return "noUv"
    if top_adjusted is None:
        return "noCandidateScore"
    if top_adjusted < DEG_ADJ and (coverage or 0.0) >= DEG_COVER:
        return "degenerate"
    return "lowSignal"


def main():
    say("=== 0. 只读闸门 ===")
    con = ro(DB)
    say("db: %s  size=%d  mtime=%s" % (DB, os.path.getsize(DB),
                                       __import__("time").strftime("%Y-%m-%d %H:%M:%S",
                                                                   __import__("time").localtime(os.path.getmtime(DB)))))
    say("journal mode 检查：以 ro uri 打开，任何写操作都会抛异常")
    try:
        con.execute("update resources set width=width")
        say("!! 写入成功了 —— 只读闸门没生效")
    except Exception as e:
        say("写入被拒：%s" % e)

    # ---- 1. 库侧计数 ----------------------------------------------------
    say()
    say("=== 1. 库侧计数（resources.db）===")
    one = lambda s: con.execute(s).fetchone()[0]
    anon = one("select count(*) from resources where type='texture' and path is null")
    named_path = one("select count(*) from resources where type='texture' and path is not null")
    named_like = one("select count(*) from resources where name like '%.tga' or name like '%.dds' or name like '%.png'")
    pool = len(con.execute(POOL_SQL).fetchall())
    say("匿名贴图 path is null           : %d   (记录 24,261)" % anon)
    say("候选池 SQL(lib 原文,含 height)  : %d   (记录 1,650)" % pool)
    say("候选池 SQL(README 口径,无 height): %d" % one(
        "select count(*) from resources where type='texture' and path is null and width>=512 and codec in ('RGBA32','BC3') and mips>=4"))
    say("带名字贴图 path is not null     : %d   (记录 2,271)" % named_path)
    say("带名字贴图 name like '.tga/.dds/.png': %d" % named_like)
    say("带名字 codec 分布               : %s" % con.execute(
        "select codec,count(*) from resources where type='texture' and path is not null group by codec order by 2 desc").fetchall())
    say("带名字且 width>=512 且 height>=512: %d  (记录 0)" % one(
        "select count(*) from resources where type='texture' and path is not null and width>=512 and height>=512"))
    say("带名字且 (width>=512 或 height>=512): %d  —— 「≥512 一张都没有」只在双维口径下成立" % one(
        "select count(*) from resources where type='texture' and path is not null and (width>=512 or height>=512)"))
    say("带名字最大边长                 : %s" % (con.execute(
        "select max(width),max(height) from resources where type='texture' and path is not null").fetchone(),))

    # named ∩ anon 四条通道
    say()
    say("named ∩ anon 四条通道（都应为 0）")
    say("  同 hash（trivially 0，hash 是主键）: %d" % one(
        "select count(*) from resources where type='texture' and path is null and name in (select name from resources where type='texture' and path is not null)"))
    say("  同 filecrc                         : %d" % one(
        "select count(*) from resources where type='texture' and path is null and filecrc in (select filecrc from resources where type='texture' and path is not null and filecrc is not null)"))
    say("  同 sha（blobs 内容指纹自连接）      : %d" % one(
        """select count(*) from resources r join blobs b on b.hash=r.hash
           where r.type='texture' and r.path is null and b.sha in
           (select b2.sha from resources r2 join blobs b2 on b2.hash=r2.hash
             where r2.type='texture' and r2.path is not null)"""))
    say("  池内 ∩ named（同 sha）              : %d" % one(
        """select count(*) from resources r join blobs b on b.hash=r.hash
           where r.type='texture' and r.path is null and r.width>=512 and r.height>=512
             and r.codec in ('RGBA32','BC3') and r.mips>=4 and b.sha in
           (select b2.sha from resources r2 join blobs b2 on b2.hash=r2.hash
             where r2.type='texture' and r2.path is not null)"""))

    # 入边普查
    say()
    say("匿名贴图的入边（都应为 0）")
    say("  refs 里 .tga 行 / 解出 hash: %s" % (con.execute(
        "select count(*),sum(to_hash is not null) from refs where kind='.tga'").fetchone(),))
    say("  relations use-tex 边: %s" % con.execute(
        "select count(*) from relations where rel='use-tex'").fetchone()[0])
    anon_set_sql = "select hash from resources where type='texture' and path is null"
    say("  relations to_hash 命中匿名贴图: %d" % con.execute(
        "select count(*) from relations where to_hash in (%s)" % anon_set_sql).fetchone()[0])
    say("  refs to_hash 命中匿名贴图     : %d" % con.execute(
        "select count(*) from refs where to_hash in (%s)" % anon_set_sql).fetchone()[0])
    say("  amembers 贴图成员 / 其中匿名  : %s" % (con.execute(
        """select count(*),sum(r.path is null) from amembers m join resources r on r.hash=m.hash
           where r.type='texture'""").fetchone(),))
    say("  assets.primary_hash 命中匿名  : %d" % con.execute(
        "select count(*) from assets where primary_hash in (%s)" % anon_set_sql).fetchone()[0])
    say("  dangling 表贴图名（.tga/.dds/.png 去重）: %d" % one(
        "select count(distinct name) from dangling where ext in ('.tga','.dds','.png')"))
    say("  refs 未解析贴图名（去重）              : %d" % one(
        "select count(distinct name) from refs where to_hash is null and kind in ('.tga','.dds','.png')"))

    # mesh 清单（试贴分母）
    say()
    say("mesh 清单（uvfit_batch 的分母）")
    names = [r[0] for r in con.execute(
        "select distinct name from refs where kind='.mesh' and lower(from_path) like '%.mdl' order by name")]
    say("  refs 里 .mdl 声明的 mesh 去重: %d  (记录 2,818)" % len(names))
    resolved = 0
    for n in names:
        if con.execute("select hash from resources where lower(path) like '%/'||lower(?) limit 1", (n,)).fetchone():
            resolved += 1
    say("  其中 path 能解出 hash        : %d" % resolved)

    # ---- 2. 覆盖表 ------------------------------------------------------
    say()
    say("=== 2. 人工标注覆盖表 ===")
    raw = open(OVERRIDE, "rb").read()
    md5 = hashlib.md5(raw).hexdigest()
    d = json.loads(raw.decode("utf-8"))
    ov = d.get("overrides", {})
    say("md5=%s 基线=7e81f32cd3f595b7f079944b086bae0b  一致=%s  字节=%d" % (md5, md5 == "7e81f32cd3f595b7f079944b086bae0b", len(raw)))
    say("标注条数=%d  (记录 0)" % len(ov))
    # 别处是否也存了标注（只查不改）
    alt = con.execute("select count(*) from sqlite_master where name like '%override%'").fetchone()[0]
    say("库里 override 相关表: %d" % alt)

    # ---- 3. results/*.json 重算分桶 -------------------------------------
    say()
    say("=== 3. 逐份重算（.scratch/uvfit_batch/results/*.json）===")
    files = sorted(os.listdir(RESULTS))
    say("结果文件数=%d" % len(files))
    rows = {}
    cand_slots = 0
    cand_distinct = Counter()
    top1_distinct = Counter()
    per_mesh = {}
    bad = 0
    for f in files:
        p = os.path.join(RESULTS, f)
        try:
            v = json.loads(open(p, "r", encoding="utf-8").read())
        except Exception:
            bad += 1
            continue
        mesh = v.get("mesh") or (f[:-5] + ".mesh")
        has_uv = bool(v.get("hasUv"))
        cov = v.get("coverage")
        cands = v.get("candidates") or []
        cand_slots += len(cands)
        for i, c in enumerate(cands):
            cand_distinct[c["hash"]] += 1
            if i == 0:
                top1_distinct[c["hash"]] += 1
        top_score = cands[0]["score"] if cands else None
        adj_vals = [c.get("adjustedScore") for c in cands if c.get("adjustedScore") is not None]
        top_adj = max(adj_vals) if adj_vals else None
        g1 = grade_v2(top_score, cov, has_uv)
        g2 = grade_v2(top_adj, cov, has_uv)
        cause = unknown_cause(has_uv, top_adj, cov) if g2 == "unknown" else None
        rows[mesh] = dict(has_uv=has_uv, cov=cov, top=top_score, adj=top_adj, g1=g1, g2=g2, cause=cause)
        per_mesh[mesh] = dict(top1=(cands[0]["hash"] if cands else None),
                              cands=cands, cov=cov, has_uv=has_uv, adj=top_adj, g2=g2, cause=cause)
    say("解析失败=%d" % bad)
    g1 = Counter(r["g1"] for r in rows.values())
    g2 = Counter(r["g2"] for r in rows.values())
    split = Counter(r["cause"] for r in rows.values() if r["cause"])
    with_uv = sum(1 for r in rows.values() if r["has_uv"])
    tryable = len(rows) - split["noUv"] - split["degenerate"] - split["noCandidateScore"]
    say("graded(v1)   = %s   (记录 high2070/mid284/low14/unknown450)" % dict(g1))
    say("gradedV2     = %s   (记录 high1560/mid386/low57/unknown815)" % dict(g2))
    say("withUv       = %d   (记录 2,376)" % with_uv)
    say("unknownSplit = %s   (记录 noUv442/degenerate263/noCandidateScore8/lowSignal102)" % dict(split))
    say("tryableByUv  = %d   (记录 2,105)" % tryable)
    say("候选槽位=%d  去重候选=%d  (记录 28,180 / 419)" % (cand_slots, len(cand_distinct)))

    # 与 manifest 统计块对账
    say()
    say("与 manifest.json 统计块对账：")
    last = None
    man_rows = {}
    with open(MANIFEST, "r", encoding="utf-8") as fh:
        for ln in fh:
            ln = ln.strip()
            if not ln:
                continue
            j = json.loads(ln)
            if "total" in j:
                last = j
            else:
                man_rows[j["mesh"]] = j
    if last:
        st = last
        say("  manifest: total=%s withUv=%s candidates=%s graded=%s gradedV2=%s" % (
            st["total"], st["withUv"], st["candidates"], st["graded"], st["gradedV2"]))
        say("  manifest: unknownSplit=%s tryableByUv=%s" % (st["unknownSplit"], st["tryableByUv"]))
        say("  manifest: thresholds=%s" % st.get("thresholds"))
        mism = []
        for m, r in rows.items():
            mr = man_rows.get(m)
            if mr is None:
                mism.append((m, "manifest 缺行"))
                continue
            if (bool(mr["hasUv"]) != r["has_uv"] or (mr["coverage"] or 0) != (r["cov"] or 0)
                    or (mr["topScore"] or 0) != round((r["top"] or 0), 3)
                    or mr["graded"] != r["g1"] or mr["gradedV2"] != r["g2"]):
                mism.append((m, "行不一致 %s vs %s" % (mr, {k: r[k] for k in ("has_uv", "cov", "top", "g1", "g2")})))
        say("  manifest 行 vs results 行不一致: %d" % len(mism))
        for m, why in mism[:5]:
            say("    %s: %s" % (m, why))
        miss_manifest = set(rows) - set(man_rows)
        miss_results = set(man_rows) - set(rows)
        say("  清单差异：manifest 独有 %d / results 独有 %d" % (len(miss_results), len(miss_manifest)))

    # mesh 清单 vs 结果文件
    say()
    want = set(names)
    have = set(rows)
    say("refs(.mdl) 清单 %d 个 vs 结果 %d 个：缺 %d / 多 %d" % (len(want), len(have), len(want - have), len(have - want)))
    if want - have:
        say("  缺例：%s" % sorted(want - have)[:8])
    if have - want:
        say("  多例：%s" % sorted(have - want)[:8])

    # ---- 4. 分布（给选样用） --------------------------------------------
    say()
    say("=== 4. adjusted 刻度分布（阈值重标用）===")
    adj = sorted(r["adj"] for r in rows.values() if r["adj"] is not None)
    def pct(a, p):
        if not a:
            return None
        i = min(len(a) - 1, int(round(p / 100.0 * (len(a) - 1))))
        return a[i]
    say("有分份数=%d  p05=%.3f p25=%.3f p50=%.3f p75=%.3f p90=%.3f max=%.3f" % (
        len(adj), pct(adj, 5), pct(adj, 25), pct(adj, 50), pct(adj, 75), pct(adj, 90), adj[-1]))
    for cut in (LOW_SCORE, MID_SCORE, HIGH_SCORE):
        below = sum(1 for v in adj if v < cut)
        say("  阈值 %.1f：低于 %d 份 (%.1f%%) / 不低于 %d 份" % (cut, below, 100.0 * below / len(adj), len(adj) - below))
    near = []
    for cut in (LOW_SCORE, MID_SCORE, HIGH_SCORE):
        band = [(m, r) for m, r in rows.items() if r["adj"] is not None and abs(r["adj"] - cut) / cut <= 0.08]
        band.sort(key=lambda kv: abs(kv[1]["adj"] - cut) / cut)
        near.append((cut, len(band), band[:3]))
    say("  阈值 ±8%% 带内份数：%s" % [(c, n) for c, n, _ in near])

    # ---- 5. 换库风险：rehearsal 副本 ------------------------------------
    say()
    say("=== 5. 若按 Oct-12 的 path 回填换库（resources_rehearsal.db）会怎样 ===")
    if os.path.exists(REHEARSAL):
        rc = ro(REHEARSAL)
        try:
            r_anon = rc.execute("select count(*) from resources where type='texture' and path is null").fetchone()[0]
            r_pool = len(rc.execute(POOL_SQL).fetchall())
            r_named = rc.execute("select count(*) from resources where type='texture' and path is not null").fetchone()[0]
            say("  rehearsal: 匿名 %d (旧 %d) / 池 %d (旧 %d) / named %d (旧 %d)" % (
                r_anon, anon, r_pool, pool, r_named, named_path))
            say("  rehearsal 池里被补上路径的匿名贴图: %d" % (anon - r_anon))
        except Exception as e:
            say("  rehearsal 查询失败：%s" % e)
    else:
        say("  没有 rehearsal 副本")

    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
