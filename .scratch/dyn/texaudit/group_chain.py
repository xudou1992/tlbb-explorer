# -*- coding: utf-8 -*-
"""两件事（只读）：
 1) 槽位名体检：refs 里 kind='.tga' 的 name 有没有伪名（material #NN 这类），有多少；
 2) 链条口径放宽：mesh -> .mdl -> 同组（agroups/amembers）的全部 .mtl/.pu -> 贴图名，
    看「标得下去」的 mesh 从 418 只能不能抬起来。这决定「还差什么才能让人工标注最省」的第一条。
"""
import collections
import json
import os
import sqlite3

BS = chr(92)
ROOT = "D:/TLGL"
RES = os.path.join(ROOT, ".scratch/uvfit_batch/results")
OUT = os.path.join(ROOT, ".scratch/dyn/texaudit/group_chain.txt")
L = []


def say(s=""):
    L.append(str(s))


def main():
    con = sqlite3.connect("file:%s?mode=ro" % os.path.join(ROOT, ".scratch/resources.db").replace(BS, "/"), uri=True)

    say("=== 1. 槽位名体检 ===")
    names = [r[0] for r in con.execute(
        "select distinct name from refs where kind in ('.tga','.dds','.png')")]
    say("refs 贴图名去重: %d" % len(names))
    bad = [n for n in names if ("#" in n) or (" " in n) or (not n.lower().endswith((".tga", ".dds", ".png")))]
    say("含 # / 空格 / 扩展名不符的可疑名: %d 个，例: %s" % (len(bad), bad[:10]))
    say("「material #N」这类形态: %d 个" % sum(1 for n in names if n.lower().startswith("material")))
    say("defaultcompletemap / 模板名这类公共占位: %s" % [n for n in names if "default" in n.lower()][:8])
    # 这些可疑名的出处
    say("可疑名的 from_path 后缀: %s" % collections.Counter(
        (r[0] or "").replace(BS, "/").split(".")[-1].lower()
        for r in con.execute("select from_path,name from refs where kind in ('.tga','.dds','.png')")).most_common())

    say()
    say("=== 2. 放宽链条：按资产组取槽位 ===")
    scored = set(f[:-5] for f in os.listdir(RES))
    # mesh 裸名 -> gid（amembers 里 role=mesh 的成员，按 hash 与 path 对齐）
    h2path = dict(con.execute("select hash,path from resources where path is not null"))
    name2gid = collections.defaultdict(set)
    for gid, h, role in con.execute("select gid,hash,role from amembers"):
        p = h2path.get(h)
        if not p:
            continue
        b = p.replace(BS, "/").split("/")[-1].lower()
        if b.endswith(".mesh"):
            name2gid[b[:-5]].add(gid)
    say("amembers 里能按裸名对上已评分 mesh 的: %d / %d" % (
        sum(1 for s in scored if s.lower() in name2gid), len(scored)))

    # 组的成员里 .mtl/.pu 的 hash -> 声明贴图名
    tex_by_member = collections.defaultdict(set)
    for fp, n, k in con.execute("select from_path,name,kind from refs where kind in ('.tga','.dds','.png')"):
        tex_by_member[(fp or "").replace(BS, "/").split("/")[-1].lower()].add(n)
    gid_members = collections.defaultdict(lambda: collections.Counter())
    for gid, h in con.execute("select gid,hash from amembers"):
        p = h2path.get(h)
        if p:
            b = p.replace(BS, "/").split("/")[-1].lower()
            gid_members[gid][b] += 1

    look = set(n for n in tex_by_member)
    via_group = {}
    for s in scored:
        gids = name2gid.get(s.lower(), ())
        names = set()
        for g in gids:
            for b in gid_members.get(g, ()):
                if b in look:
                    names |= tex_by_member[b]
        names = {n for n in names if ("#" not in n and " " not in n and n.lower().endswith((".tga", ".dds", ".png")))}
        if names:
            via_group[s + ".mesh"] = names
    say("按「同组全部 .mtl/.pu 成员」取槽位：可标注 mesh = %d 只" % len(via_group))

    # 旧口径（mesh -> model-part -> mtl）
    mesh2mtl = collections.defaultdict(set)
    for fp, tp in con.execute(
        "select from_path,to_path from relations where rel='model-part' and lower(from_path) like '%.mesh' and lower(to_path) like '%.mtl'"):
        mesh2mtl[fp.replace(BS, "/").split("/")[-1].lower()].add(tp.replace(BS, "/").lower())
    old = {}
    for s in scored:
        nm = set()
        for mp in mesh2mtl.get(s.lower() + ".mesh", ()):
            nm |= tex_by_member.get(mp.replace(BS, "/").split("/")[-1], set())
        nm = {n for n in nm if "#" not in n and " " not in n and n.lower().endswith((".tga", ".dds", ".png"))}
        if nm:
            old[s + ".mesh"] = nm
    say("旧口径（mesh->mtl 直连）：可标注 mesh = %d 只" % len(old))
    say("放宽后新增: %d 只（合计 %d 只，占有榜 mesh 2,368 的 %.1f%%）" % (
        len(set(via_group) - set(old)),
        len(via_group), 100.0 * len(via_group) / 2368))

    # 组的 kind / 目录分布：看这批新增是不是真同一个角色的贴图集
    kind = collections.Counter()
    for gid in set(g for s in via_group for g in name2gid.get(s[:-5].lower(), ())):
        kind[con.execute("select kind from agroups where id=?", (gid,)).fetchone()[0] if con.execute(
            "select 1 from agroups where id=?", (gid,)).fetchone() else "?"] += 1
    say("涉及的组 kind 分布: %s" % kind.most_common(10))

    # 槽位名的共享度（放宽口径）
    fan = collections.Counter()
    for nm in via_group.values():
        for n in nm:
            fan[n] += 1
    say("放宽口径下槽位名去重: %d；被 >=2 只 mesh 共享的: %d 个；前 10: %s" % (
        len(fan), sum(1 for v in fan.values() if v >= 2), fan.most_common(10)))
    say("只被 1 只 mesh 声明（标一条只落一条）: %d 个" % sum(1 for v in fan.values() if v == 1))

    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    json.dump({k: sorted(v) for k, v in via_group.items()},
              open(os.path.join(ROOT, ".scratch/dyn/texaudit/mesh_slots.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
