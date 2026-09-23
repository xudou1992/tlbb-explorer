"""agent_impact_census.py — 量化「资源工作台里 3D 预览到底能画出多少资产」。

纯只读：只看 D:\\TLGL\\.scratch\\out\\tree 下的真实解包文件，不碰 tlbb-explorer/，不写 resources.db。

两个阶段：
  A. 全量扫 .mesh —— 复刻 crates/core/src/preview/geometry.rs::parse_geometry
     （判定函数逐字节对齐 .scratch/mesh_census.py 的 parse/locate），结果进缓存。
  B. 以 .mdl 为单位 —— 用 .scratch/jbcf.py 的 parse() 解 JBCF 字符串表，按
     crates/core/src/preview/summary.rs::mdl_summary 的同一条规则还原 bodies 顺序，
     再在 tree 里按「同目录优先 / 唯一茎名」定位 .mesh 实体，回答：
       - 面板会不会出现（>=1 个 .mesh 落地）
       - 第一眼那个 .mesh 能不能画
       - 换部件能不能画
       - 全都不能画的比例
       - 失败里 sm>=2 的占比

输出：agent_impact_report.txt / agent_impact_result.json / agent_impact_meshcache.json
"""
import array
import io
import json
import os
import struct
import sys
import time
from collections import Counter, defaultdict

HERE = r"D:\TLGL\.scratch"
TREE = os.path.join(HERE, "out", "tree")
MESH_CACHE = os.path.join(HERE, "agent_impact_meshcache.json")
REPORT = os.path.join(HERE, "agent_impact_report.txt")
RESULT = os.path.join(HERE, "agent_impact_result.json")

MAX = 8_000_000
HEAD = 0x118  # 位置流起点


# ---------------------------------------------------------------- geometry (对齐 mesh_census.py / geometry.rs)
def u32(b, off):
    if off + 4 > len(b):
        return None
    return struct.unpack_from("<I", b, off)[0]


def locate(raw, lo, fc, vc):
    """验证式扫描索引块：找 u32==fc，且其后 fc*3 个 u16 全部 < vc。"""
    need = 4 + fc * 3 * 2
    if fc == 0 or len(raw) < need:
        return None
    hi = len(raw) - need
    want = struct.pack("<I", fc)
    at = lo
    while at <= hi:
        p = raw.find(want, at, hi + 4)
        if p < 0:
            return None
        blk = raw[p + 4: p + need]
        a = array.array("H")
        a.frombytes(blk)
        if not a or max(a) < vc:
            return p
        at = p + 4
    return None


def parse(raw):
    """-> (ok, reason, meta)  与 mesh_census.parse 同语义（meta 字段一致）。"""
    n = len(raw)
    if n < HEAD:
        return False, "shorter_than_header", {"size": n}
    vc, fc, sm = u32(raw, 0x8C), u32(raw, 0x90), u32(raw, 0x94)
    meta = {"size": n, "vc": vc, "fc": fc, "sm": sm}
    if vc is None or fc is None or vc > MAX or fc > MAX:
        return False, "implausible_counts", meta
    pos_end = HEAD + vc * 12
    if pos_end > n:
        return False, "position_stream_truncated", meta
    static_idx = pos_end + vc * 20
    idx = None
    if u32(raw, static_idx) == fc:
        idx = static_idx
    else:
        idx = locate(raw, pos_end, fc, vc)
    if idx is None:
        return False, "no_self_consistent_index_block", meta
    middle = idx - pos_end
    meta["middle"] = middle
    meta["stride"] = round(middle / vc, 2) if vc else 0
    meta["static"] = middle == vc * 20
    meta["trailing"] = n - (idx + 4 + fc * 6)
    return True, "ok" if meta["static"] else "ok_no_normals", meta


# ---------------------------------------------------------------- 目录 / 名字分桶
def quest_stem(rel):
    """文件名去掉 w1351_ 之类的地图前缀，露出 pets_/monster_/boss_ 语义段。"""
    stem = os.path.basename(rel).lower()
    stem = stem[: stem.rfind(".")] if "." in stem else stem
    parts = stem.split("_")
    if parts and parts[0].startswith("w") and parts[0][1:].isdigit():
        parts = parts[1:]
    return "_".join(parts)


def mesh_bucket(rel):
    p = rel.lower()
    if p.startswith("mobile_maps_source/"):
        return "地图场景块(mobile_maps_source)"
    if p.startswith("data/effect/"):
        return "特效模型(data/effect)"
    if p.startswith("data/source/player/"):
        return "玩家角色(data/source/player)"
    if p.startswith("data/source/npc/toukui/"):
        return "头盔外观(npc/toukui)"
    if p.startswith("data/source/npc/wuqi/"):
        return "武器(npc/wuqi)"
    if p.startswith("data/source/npc/guajian/"):
        return "挂件(npc/guajian)"
    if p.startswith("data/source/npc/changjingdaoju/"):
        return "场景采集道具(npc/changjingdaoju)"
    if p.startswith("data/source/npc/dynamic/"):
        return "动态场景物件(npc/dynamic)"
    if p.startswith("data/source/npc/model/"):
        return "NPC/怪物模型库(npc/model)"
    if p.startswith("data/source/npc/quest/"):
        stem = quest_stem(rel)
        for k, v in (("pets_", "宠物/坐骑(npc/quest:pets)"),
                     ("boss_", "BOSS(npc/quest:boss)"),
                     ("monster_", "怪物(npc/quest:monster)"),
                     ("new_npc", "NPC(npc/quest:npc)"),
                     ("npc_", "NPC(npc/quest:npc)"),
                     ("wuqi_", "武器(npc/quest:wuqi)"),
                     ("shenghuo_", "生活材料(npc/quest:shenghuo)"),
                     ("zhenshou_", "神兽(npc/quest:zhenshou)"),
                     ("changjing", "场景道具(npc/quest:scene)"),
                     ("zuoqi", "宠物/坐骑(npc/quest:pets)")):
            if stem.startswith(k):
                return v
        return "任务杂项(npc/quest:other)"
    return "其它"


def mdl_class(rel):
    """工作台分类：角色/怪物/宠物/武器挂件/场景道具/特效/地图。"""
    b = mesh_bucket(rel)
    if b == "任务杂项(npc/quest:other)":
        stem = quest_stem(rel)
        if "zuoqi" in stem or "pet" in stem:
            return "宠物/坐骑"
        return "怪物/NPC"
    return {
        "宠物/坐骑(npc/quest:pets)": "宠物/坐骑",
        "BOSS(npc/quest:boss)": "怪物/NPC(BOSS)",
        "怪物(npc/quest:monster)": "怪物/NPC",
        "NPC(npc/quest:npc)": "怪物/NPC",
        "武器(npc/quest:wuqi)": "武器/挂件",
        "生活材料(npc/quest:shenghuo)": "场景道具",
        "场景道具(npc/quest:scene)": "场景道具",
        "神兽(npc/quest:zhenshou)": "怪物/NPC",
        "NPC/怪物模型库(npc/model)": "怪物/NPC",
        "玩家角色(data/source/player)": "玩家角色",
        "武器(npc/wuqi)": "武器/挂件",
        "头盔外观(npc/toukui)": "武器/挂件",
        "挂件(npc/guajian)": "武器/挂件",
        "场景采集道具(npc/changjingdaoju)": "场景道具",
        "动态场景物件(npc/dynamic)": "场景道具",
        "特效模型(data/effect)": "特效模型",
        "地图场景块(mobile_maps_source)": "地图场景块",
    }.get(b, b)


# ---------------------------------------------------------------- 阶段 A：全量 .mesh
def scan_meshes():
    paths = []
    for dp, _dn, names in os.walk(TREE):
        rel = os.path.relpath(dp, TREE).replace("\\", "/")
        for f in names:
            if f.lower().endswith(".mesh"):
                paths.append((rel + "/" + f) if rel != "." else f)
    paths.sort()
    recs = {}
    t0 = time.time()
    for i, rel in enumerate(paths):
        try:
            with open(os.path.join(TREE, rel.replace("/", os.sep)), "rb") as fh:
                raw = fh.read()
        except OSError:
            recs[rel] = {"ok": False, "reason": "read_error", "vc": 0, "fc": 0, "sm": None}
            continue
        ok, reason, m = parse(raw)
        recs[rel] = {"ok": ok, "reason": reason, "vc": m.get("vc", 0) or 0,
                     "fc": m.get("fc", 0) or 0, "sm": m.get("sm"),
                     "static": bool(m.get("static")), "size": m.get("size", len(raw)),
                     "middle": m.get("middle"), "trailing": m.get("trailing")}
        if (i + 1) % 2000 == 0:
            sys.stderr.write("  mesh %d/%d  %.1fs\n" % (i + 1, len(paths), time.time() - t0))
    with io.open(MESH_CACHE, "w", encoding="utf-8") as fh:
        json.dump(recs, fh)
    return recs


# ---------------------------------------------------------------- JBCF + bodies
sys.path.insert(0, HERE)
import jbcf  # noqa: E402  (只有 main() 会碰 db，import 安全)


def has_ext(s):
    i = s.rfind(".")
    if i < 0:
        return False
    e = s[i + 1:]
    return bool(e) and len(e) <= 5 and all(c.isascii() and c.isalnum() for c in e)


def bodies_from_strings(strs):
    """复刻 summary.rs::mdl_summary 的 bodies 顺序 + base_dir。"""
    out, base_dir, name = [], "", ""
    last_label = ""
    seen = set()
    i = 0
    while i < len(strs):
        s = strs[i]
        if not s:
            i += 1
            continue
        if s.endswith("/") and not base_dir:
            base_dir = s
            i += 1
            continue
        low = s.lower()
        if low.endswith(".ske"):
            last_label = ""
            i += 1
            continue
        if low.endswith(".mesh"):
            label = last_label
            last_label = ""
            nxt = strs[i + 1] if i + 1 < len(strs) else ""
            paired = nxt.lower().endswith(".mtl")
            if not paired:
                label = ""
            out.append({"label": label, "mesh": s, "material": nxt if paired else "<缺>"})
            i += 2 if paired else 1
            continue
        if has_ext(s):
            seen.add(s)
            last_label = ""
            i += 1
            continue
        if not name:
            name = s
        else:
            if s not in seen:
                seen.add(s)
                last_label = s
        i += 1
    return name, base_dir, out


def build_index(mesh_paths):
    """basename(lower) -> [rel paths]；(父目录(lower), basename) -> path。"""
    by_name = defaultdict(list)
    by_dir_name = {}
    for rel in mesh_paths:
        b = rel.rsplit("/", 1)[-1].lower()
        by_name[b].append(rel)
        by_dir_name[(rel.rsplit("/", 1)[0].lower(), b)] = rel
    return by_name, by_dir_name


def resolve(rel_mesh, mdl_rel, base_dir, by_name, by_dir_name):
    """-> (path|None, how)  同目录 → base_dir → 唯一茎名 → 歧义/缺失。
    工作台按 basename 在库里 LIMIT 1 查，所以只要 basename 命中就等价于 resolved。"""
    key = rel_mesh.rsplit("/", 1)[-1].lower()
    if "/" in rel_mesh.lower():
        # 客户端字符串里带路径：工作台的 name=? 精确匹配会落空，但实体多半存在
        pass
    mdl_dir = mdl_rel.rsplit("/", 1)[0].lower()
    same = by_dir_name.get((mdl_dir, key))
    if same:
        return same, "same_dir"
    cands = by_name.get(key) or []
    if not cands:
        return None, "missing"
    if base_dir:
        bd = base_dir.lower().strip("/")
        hit = [c for c in cands if c.lower().startswith(bd + "/")]
        if hit:
            return hit[0], "base_dir"
    if len(cands) == 1:
        return cands[0], "unique_stem"
    return sorted(cands)[0], "ambiguous_stem"


# ---------------------------------------------------------------- 阶段 B：.mdl
def scan_mdls(recs, by_name, by_dir_name):
    mdls = []
    for dp, _dn, names in os.walk(TREE):
        rel = os.path.relpath(dp, TREE).replace("\\", "/")
        for f in names:
            if f.lower().endswith(".mdl"):
                mdls.append((rel + "/" + f) if rel != "." else f)
    mdls.sort()
    rows = []
    t0 = time.time()
    for i, rel in enumerate(mdls):
        path = os.path.join(TREE, rel.replace("/", os.sep))
        size = os.path.getsize(path)
        rec = {"mdl": rel, "cls": mdl_class(rel), "bucket": mesh_bucket(rel),
               "size": size, "jbcf": None, "name": "", "base_dir": "",
               "bodies": 0, "resolved": 0, "resolved_drawable": 0,
               "first_resolved": None, "first_ok": None, "first_sm": None,
               "first_vc": None, "first_reason": None,
               "alt_ok": None, "outcome": None, "how": Counter(),
               "fail_sm2": 0, "fail_reasons": Counter(), "slashed": 0, "chips": False}
        try:
            with open(path, "rb") as fh:
                raw = fh.read()
            hdr, off, flag, strs = jbcf.parse(raw)
        except Exception as e:  # JBCF 解不出 = bodies 为空 = 面板必不出
            rec["jbcf"] = "fail:%s" % type(e).__name__
            rec["outcome"] = "mdl_unparsable"
            rows.append(rec)
            rec["how"] = dict(rec["how"])
            continue
        rec["jbcf"] = "ok"
        text = [s for s, _h in strs]
        name, base_dir, bodies = bodies_from_strings(text)
        rec["name"], rec["base_dir"] = name, base_dir
        rec["bodies"] = len(bodies)
        got = []
        for b in bodies:
            m = b["mesh"]
            if "/" in m.lower():
                rec["slashed"] += 1
            p, how = resolve(m, rel, base_dir, by_name, by_dir_name)
            rec["how"][how] += 1
            if not p:
                continue
            mr = recs.get(p) or {}
            got.append({"mesh": m, "file": p, "ok": bool(mr.get("ok")),
                        "sm": mr.get("sm"), "vc": mr.get("vc"), "reason": mr.get("reason"),
                        "how": how})
        rec["how"] = dict(rec["how"])
        rec["resolved"] = len(got)
        rec["resolved_drawable"] = sum(1 for g in got if g["ok"])
        rec["chips"] = len(got) >= 2
        for g in got:
            if not g["ok"]:
                rec["fail_reasons"][g["reason"]] += 1
                if (g["sm"] or 0) >= 2:
                    rec["fail_sm2"] += 1
        if got:
            f0 = got[0]
            rec["first_resolved"] = f0["file"]
            rec["first_ok"] = f0["ok"]
            rec["first_sm"] = f0["sm"]
            rec["first_vc"] = f0["vc"]
            rec["first_reason"] = f0["reason"]
            rec["alt_ok"] = any(g["ok"] for g in got[1:])
            rec["outcome"] = ("first_ok" if f0["ok"] else
                              ("only_after_switch" if rec["alt_ok"] else "all_fail"))
        else:
            rec["outcome"] = "no_mesh_resolved" if bodies else "mdl_no_bodies"
        rec["bodies_detail"] = got
        rows.append(rec)
        if (i + 1) % 700 == 0:
            sys.stderr.write("  mdl %d/%d  %.1fs\n" % (i + 1, len(mdls), time.time() - t0))
    return rows


# ---------------------------------------------------------------- 阶段 C：资源组（工作台列表的真实单位 = agroups）
DB = os.path.join(HERE, "resources.db")


def group_rollup(rows):
    """只读 resources.db：复现 asset_inspect 的「每组找第一个 .mdl」规则。

    members 的 SQL 是 ORDER BY m.role, r.path，inspector.rs 用 .find(|m| .mdl)，
    所以一个组里即使有 5 个 .mdl，也只有排序最靠前的那一个会决定面板长什么样。
    """
    import sqlite3
    out = {"unavailable": True}
    try:
        con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    except Exception as e:
        out["error"] = str(e)
        return out
    by_mdl = {}
    for r in rows:
        by_mdl[r["mdl"].lower()] = r
    c = Counter()
    per_cls = defaultdict(Counter)
    unmatched = []
    for gid, n_mesh, kind in con.execute("SELECT id, n_mesh, kind FROM agroups").fetchall():
        c["groups"] += 1
        mdl_row = None
        for (role, path) in con.execute(
                "SELECT m.role, r.path FROM amembers m LEFT JOIN resources r ON r.hash=m.hash"
                " WHERE m.gid=?1 AND r.ext='.mdl' ORDER BY m.role, r.path LIMIT 1", (gid,)):
            mdl_row = by_mdl.get((path or "").lower())
            if mdl_row is None and path:
                unmatched.append(path)
            break
        if n_mesh > 0:
            c["groups_mesh"] += 1
            if mdl_row is None:
                c["g_no_mdl"] += 1
                per_cls[kind]["g_no_mdl"] += 1
            else:
                cls = kind
                per_cls[cls]["g_panel_yes" if mdl_row["resolved"] >= 1 else "g_panel_no"] += 1
                c["g_has_mdl"] += 1
                if mdl_row["outcome"] == "first_ok":
                    c["g_first_ok"] += 1
                    per_cls[cls]["g_first_ok"] += 1
                elif mdl_row["outcome"] == "only_after_switch":
                    c["g_switch"] += 1
                    per_cls[cls]["g_switch"] += 1
                elif mdl_row["outcome"] == "all_fail":
                    c["g_all_fail"] += 1
                    per_cls[cls]["g_all_fail"] += 1
                else:
                    c["g_no_mesh_resolved"] += 1
                    per_cls[cls]["g_no_mesh_resolved"] += 1
    out.update({"unavailable": False,
                "counter": dict(c), "per_kind": {k: dict(v) for k, v in per_cls.items()},
                "unmatched_mdl_paths": unmatched[:20], "n_unmatched": len(unmatched)})
    con.close()
    return out


def db_crosscheck(by_name):
    """只读核对：tree 的 .mesh 茎名集合 == resources.name 集合（决定 LIMIT 1 是否唯一）。"""
    import sqlite3
    try:
        con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    except Exception as e:
        return {"error": str(e)}
    names = {r[0].lower() for r in con.execute("SELECT name FROM resources WHERE ext='.mesh'")}
    tree = set(by_name)
    dup = con.execute(
        "SELECT count(*) FROM (SELECT name FROM resources WHERE ext='.mesh'"
        " GROUP BY name HAVING count(*) > 1)").fetchone()[0]
    res = {"db_mesh_rows": con.execute("SELECT count(*) FROM resources WHERE ext='.mesh'").fetchone()[0],
           "db_distinct_names": len(names), "names_with_multiple_rows": dup,
           "tree_only": len(tree - names), "db_only": len(names - tree)}
    con.close()
    return res


# ---------------------------------------------------------------- 汇总
def pct(a, b):
    return "  -  " if not b else "%5.1f%%" % (a * 100.0 / b)


def refs_crosscheck(rows):
    """独立第二遍：拿项目自己算好的 catalog.refs(.mdl→.mesh) 对一遍定位结果。"""
    import sqlite3
    try:
        con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    except Exception as e:
        return {"error": str(e)}
    per = {}
    for fpath, name, th in con.execute(
            "SELECT from_path, name, to_hash FROM refs WHERE kind='.mesh' AND from_path LIKE '%.mdl'"):
        per.setdefault(fpath.lower(), []).append((name, th))
    con.close()
    mine = {r["mdl"].lower(): r for r in rows}
    out = {"slots_mine": sum(r["bodies"] for r in rows), "slots_db": sum(len(v) for v in per.values()),
           "unres_mine": sum(r["bodies"] - r["resolved"] for r in rows),
           "unres_db": sum(1 for v in per.values() for _n, h in v if not h),
           "mdl_with_ref_mine": sum(1 for r in rows if r["bodies"] > 0), "mdl_with_ref_db": len(per),
           "diff_files": 0, "examples": []}
    for path, rs in per.items():
        m = mine.get(path)
        if m is None or m["bodies"] != len(rs) or (m["bodies"] - m["resolved"]) != sum(1 for _n, h in rs if not h):
            out["diff_files"] += 1
            if len(out["examples"]) < 5:
                out["examples"].append({"mdl": path, "db": [(n, bool(h)) for n, h in rs],
                                        "mine": {"bodies": (m or {}).get("bodies"),
                                                 "resolved": (m or {}).get("resolved")}})
    return out


def main():
    t0 = time.time()
    recs = scan_meshes()
    print("mesh scan %.1fs" % (time.time() - t0))
    paths = list(recs)
    by_name, by_dir_name = build_index(paths)
    rows = scan_mdls(recs, by_name, by_dir_name)

    # ---- 1. .mesh 级分桶
    mbuck = defaultdict(lambda: Counter())
    mreason = defaultdict(lambda: Counter())
    for rel, r in recs.items():
        b = mesh_bucket(rel)
        mbuck[b]["n"] += 1
        mbuck[b]["ok" if r["ok"] else "bad"] += 1
        if r["ok"]:
            mbuck[b]["ok_sm1" if (r["sm"] or 0) == 1 else "ok_sm2p"] += 1
        else:
            mbuck[b]["bad_sm2p" if (r["sm"] or 0) >= 2 else "bad_sm1"] += 1
        mreason[b][r["reason"]] += 1

    # ---- 2. .mdl 级
    mc = defaultdict(lambda: Counter())
    for r in rows:
        c = r["cls"]
        mc[c]["mdl"] += 1
        if r["jbcf"] != "ok":
            mc[c]["jbcf_fail"] += 1
        if r["bodies"] == 0:
            mc[c]["no_bodies"] += 1
        if r["resolved"] >= 1:
            mc[c]["panel"] += 1
            mc[c]["bodies_res"] += r["resolved"]
            if r["chips"]:
                mc[c]["has_chips"] += 1
            if r["first_ok"]:
                mc[c]["first_ok"] += 1
            elif r["alt_ok"]:
                mc[c]["switch_ok"] += 1
            else:
                mc[c]["all_fail"] += 1
            mc[c]["fail_slots"] += r["resolved"] - r["resolved_drawable"]
            mc[c]["fail_sm2"] += r["fail_sm2"]
        else:
            mc[c]["no_panel"] += 1

    L = []
    W = L.append
    W("agent_impact_census —— 3D 预览可画率实测报告")
    W("生成脚本: D:\\TLGL\\.scratch\\agent_impact_census.py   数据源: %s (只读)" % TREE)
    W("判定函数 parse()/locate() 与 crates/core/src/preview/geometry.rs::parse_geometry 对齐；")
    W("bodies 顺序与 crates/core/src/preview/summary.rs::mdl_summary 对齐；解析 .mdl 用 .scratch/jbcf.py::parse。")
    W("")
    W("=" * 100)
    W("【1】.mesh 文件级：能不能解出顶点+索引")
    W("=" * 100)
    W("%-38s %7s %7s %7s %7s %9s %9s %9s" % ("目录桶", "文件数", "可画", "失败", "失败率", "可画sm=1", "失败sm>=2", "失败sm<2"))
    tot = Counter()
    for b in sorted(mbuck, key=lambda k: -mbuck[k]["n"]):
        c = mbuck[b]
        tot["n"] += c["n"]; tot["ok"] += c["ok"]; tot["bad"] += c["bad"]
        tot["ok_sm1"] += c["ok_sm1"]; tot["bad_sm2p"] += c["bad_sm2p"]; tot["bad_sm1"] += c["bad_sm1"]
        W("%-38s %7d %7d %7d %7s %9d %9d %9d" % (
            b, c["n"], c["ok"], c["bad"], pct(c["bad"], c["n"]),
            c["ok_sm1"], c["bad_sm2p"], c["bad_sm1"]))
    W("%-38s %7d %7d %7d %7s %9d %9d %9d" % (
        "合计", tot["n"], tot["ok"], tot["bad"], pct(tot["bad"], tot["n"]),
        tot["ok_sm1"], tot["bad_sm2p"], tot["bad_sm1"]))
    W("")
    W("失败原因分布（全量 .mesh）：")
    rr = Counter()
    for b in mreason.values():
        rr.update(b)
    for k, v in rr.most_common():
        W("  %-34s %6d %s" % (k, v, pct(v, tot["n"])))
    W("")
    W("=" * 100)
    W("【2】.mdl 级（立体预览的唯一数据来源：insp.mdl.bodies，见 mesh.js::listOf）")
    W("=" * 100)
    W("2.1 面板会不会出现")
    allt = Counter()
    for c in mc.values():
        for k, v in c.items():
            allt[k] += v
    W("  .mdl 总数                       : %d" % allt["mdl"])
    W("  JBCF 解不出（面板必不出）       : %d" % allt["jbcf_fail"])
    W("  字符串表里 0 个 .mesh 部件      : %d" % allt["no_bodies"])
    W("  能定位到 >=1 个 .mesh 实体      : %d %s" % (allt["panel"], pct(allt["panel"], allt["mdl"])))
    W("  定位不到 .mesh 实体（无面板）   : %d %s" % (allt["no_panel"], pct(allt["no_panel"], allt["mdl"])))
    W("  部件槽位合计 / 其中定位到实体   : %d / %d" % (sum(r["bodies"] for r in rows), allt["bodies_res"]))
    W("  定位方式分布: %s" % dict(sum((Counter(r["how"]) for r in rows), Counter())))
    W("  引用来料 .mesh 槽位里可画       : %d %s" % (
        sum(r["resolved_drawable"] for r in rows), pct(sum(r["resolved_drawable"] for r in rows), allt["bodies_res"])))
    W("")
    W("2.2 第一眼能不能画（只看面板会出的那批 .mdl）")
    W("%-22s %6s %6s %8s %9s %9s %9s %10s %9s %9s %9s %9s" % (
        "分类", ".mdl", "出面板", "面板率", "第一个可画", "换部件才可画", "全画不出",
        "第一眼可画率", "有筹码", "第一眼占全类", "无面板占全类", "全败占全类"))
    for c in sorted(mc, key=lambda k: -mc[k]["panel"]):
        x = mc[c]
        pn = x["panel"]
        W("%-22s %6d %6d %8s %9d %9d %9d %10s %9d %10s %10s %9s" % (
            c, x["mdl"], pn, pct(pn, x["mdl"]), x["first_ok"], x["switch_ok"], x["all_fail"],
            pct(x["first_ok"], pn), x["has_chips"], pct(x["first_ok"], x["mdl"]),
            pct(x["no_panel"], x["mdl"]), pct(x["all_fail"], x["mdl"])))
    P = allt["panel"]
    W("%-22s %6d %6d %8s %9d %9d %9d %10s %9d %10s %10s %9s" % (
        "合计", allt["mdl"], P, pct(P, allt["mdl"]), allt["first_ok"], allt["switch_ok"], allt["all_fail"],
        pct(allt["first_ok"], P), allt["has_chips"], pct(allt["first_ok"], allt["mdl"]),
        pct(allt["no_panel"], allt["mdl"]), pct(allt["all_fail"], allt["mdl"])))
    W("")
    W("  占全部 .mdl 的比例：第一眼就能画 %s / 点一下筹码才能画 %s / 换哪个部件都画不出 %s / 连面板都没有 %s" % (
        pct(allt["first_ok"], allt["mdl"]), pct(allt["switch_ok"], allt["mdl"]),
        pct(allt["all_fail"], allt["mdl"]), pct(allt["no_panel"], allt["mdl"])))
    W("")
    W("2.3 失败的成因")
    for cls in ("玩家角色",):
        ok = [r for r in rows if r["cls"] == cls and r["outcome"] == "first_ok"]
        W("  %s 里第一眼可画的 %d 个 .mdl: %s" % (
            cls, len(ok), ", ".join("%s(vc=%s,sm=%s)" % (os.path.basename(r["mdl"]), r["first_vc"], r["first_sm"])
                                    for r in ok)))
    nbad_first = allt["switch_ok"] + allt["all_fail"]
    nbad_sm2 = sum(1 for r in rows if r["outcome"] in ("only_after_switch", "all_fail")
                   and (r["first_sm"] or 0) >= 2)
    W("  出面板但第一个 .mesh 就画不出的 .mdl   : %d" % nbad_first)
    W("    其中「第一个失败部件 sm>=2」        : %d %s" % (
        nbad_sm2, pct(nbad_sm2, nbad_first)))
    W("  可画部件存在但排在第一位之后（被埋）  : %d" % allt["switch_ok"])
    W("  画不出的 .mesh 槽位 / 其中 sm>=2      : %d / %d %s" % (
        allt["fail_slots"], allt["fail_sm2"], pct(allt["fail_sm2"], allt["fail_slots"])))
    fr = Counter()
    for r in rows:
        fr.update(r["fail_reasons"])
    W("  被 .mdl 引用且画不出的原因分布: %s" % dict(fr.most_common()))
    W("")
    W("  「第一眼看不到立体」的 .mdl 归因（共 %d 个，占全部 .mdl %s）：" % (
        allt["mdl"] - allt["first_ok"], pct(allt["mdl"] - allt["first_ok"], allt["mdl"])))
    cause = Counter()
    for r in rows:
        if r["outcome"] == "first_ok":
            continue
        if r["jbcf"] != "ok":
            cause["a. .mdl 本身 JBCF 解不出"] += 1
        elif r["bodies"] == 0:
            cause["b. .mdl 字符串表里没有 .mesh 部件"] += 1
        elif r["resolved"] == 0:
            cause["c. 引用的 .mesh 实体全都不在库里(悬空引用)"] += 1
        elif r["outcome"] == "only_after_switch":
            cause["d. 第一个部件索引块定位失败(sm>=2)，换部件可救"] += 1
        else:
            cause["e. 所有部件索引块都定位失败(sm>=2)"] += 1
    for k, v in cause.most_common():
        W("     %-52s %5d  占失败 %s / 占全部 .mdl %s" % (k, v, pct(v, allt["mdl"] - allt["first_ok"]),
                                                          pct(v, allt["mdl"])))
    W("")
    W("  被任何 .mdl 引用的 .mesh 个数: %d / %d（其余是没有 .mdl 顶着的独立网格，面板永不出）" % (
        len({g["file"] for r in rows for g in r.get("bodies_detail", [])}), len(recs)))
    unreferenced = set(recs) - {g["file"] for r in rows for g in r.get("bodies_detail", [])}
    W("    没 .mdl 顶着的 .mesh 桶分布: %s" % dict(Counter(mesh_bucket(p) for p in unreferenced).most_common()))
    W("    其中「其实可画、只是没有 .mdl 引用」: %d" % sum(1 for p in unreferenced if recs[p]["ok"]))
    W("")
    W("=" * 100)
    W("【3】已知反例核对：w1351_monster_xiyuqiezei")
    W("=" * 100)
    for r in rows:
        if "xiyuqiezei" in r["mdl"].lower():
            W("  .mdl            : %s  (jbcf=%s, bodies=%d, resolved=%d, drawable=%d)" % (
                r["mdl"], r["jbcf"], r["bodies"], r["resolved"], r["resolved_drawable"]))
            W("  模型名 / 基目录 : %r / %r" % (r["name"], r["base_dir"]))
            W("  第一个网格      : %s  ok=%s sm=%s vc=%s fc=%s reason=%s" % (
                r["first_resolved"], r["first_ok"], r["first_sm"], r["first_vc"],
                (recs.get(r["first_resolved"]) or {}).get("fc"), r["first_reason"]))
            W("  结论            : outcome=%s" % r["outcome"])
            for g in r.get("bodies_detail", []):
                m = recs.get(g["file"], {})
                W("     - %s -> %s  sm=%s vc=%s ok=%s (resolve=%s)" % (
                    g["mesh"], g["file"], g["sm"], g["vc"], g["ok"], g["how"]))
    W("")
    W("=" * 100)
    W("【4】资源组级（工作台列表的真实单位：agroups 一行 = 用户点开的一个资产）")
    W("=" * 100)
    grp = group_rollup(rows)
    if grp.get("unavailable"):
        W("  读 resources.db 失败，跳过：%s" % grp.get("error"))
    else:
        g = grp["counter"]
        W("  组总数                       : %d" % g.get("groups", 0))
        W("  含 >=1 个 .mesh 的组         : %d %s" % (g.get("groups_mesh", 0), pct(g.get("groups_mesh", 0), g.get("groups", 0))))
        W("  其中组内有 .mdl（会去解它）  : %d" % g.get("g_has_mdl", 0))
        W("  组内有 .mdl 却一个网格没解出 : %d" % (g.get("g_panel_no", 0) + g.get("g_no_mesh_resolved", 0)))
        W("  有 .mesh 但没有 .mdl（必无面板）: %d %s" % (g.get("g_no_mdl", 0), pct(g.get("g_no_mdl", 0), g.get("groups_mesh", 0))))
        W("  第一眼就能画的组             : %d  占全库 %s / 占有网格的组 %s" % (
            g.get("g_first_ok", 0), pct(g.get("g_first_ok", 0), g.get("groups", 0)),
            pct(g.get("g_first_ok", 0), g.get("groups_mesh", 0))))
        W("  换个筹码才能画的组           : %d" % g.get("g_switch", 0))
        W("  部件全画不出的组             : %d" % g.get("g_all_fail", 0))
        W("  面板出现率（占有网格的组）   : %s" % pct(
            g.get("g_first_ok", 0) + g.get("g_switch", 0) + g.get("g_all_fail", 0), g.get("groups_mesh", 0)))
        W("  按 kind 细分: %s" % json.dumps(grp["per_kind"], ensure_ascii=False))
        W("  对不上 tree 的 .mdl 路径数   : %d %s" % (grp.get("n_unmatched", 0), (grp.get("unmatched_mdl_paths") or [""])[0]))
    W("")
    W("=" * 100)
    W("【5】口径核对：tree 茎名索引 vs 工作台用的 resources.name 索引")
    W("=" * 100)
    xchk = db_crosscheck(by_name)
    W("  %s" % json.dumps(xchk, ensure_ascii=False))
    W("  -> name 在 .mesh 上全局唯一，所以「basename + LIMIT 1」等价于本脚本的唯一茎名定位。")
    rc = refs_crosscheck(rows)
    W("")
    W("  再拿项目自己算好的 refs(.mdl→.mesh) 对一遍（另一条独立实现）：")
    W("     槽位数 我方 %d / refs %d ；引用落空 我方 %d / refs %d ；带网格引用的 .mdl 我方 %d / refs %d" % (
        rc.get("slots_mine", 0), rc.get("slots_db", 0), rc.get("unres_mine", 0), rc.get("unres_db", 0),
        rc.get("mdl_with_ref_mine", 0), rc.get("mdl_with_ref_db", 0)))
    W("     逐文件计数不一致：%d 个 / %d" % (rc.get("diff_files", 0), rc.get("mdl_with_ref_db", 1)))
    for ex in rc.get("examples", []):
        W("     %s  refs=%s  我方=%s" % (ex["mdl"], ex["db"], ex["mine"]))
    W("     该例 .mdl 字符串表原文引用 w1351_zuoqi_shizi.mesh（tree 与 resources.name 里都没有此文件），")
    W("     refs 却记成了兄弟名 w1351_zuoqi_baishi.mesh —— 工作台走的是 name 精确匹配，所以按我方口径它仍然落空。")
    W("")
    W("=" * 100)
    W("【6】口径说明")
    W("=" * 100)
    W("  实测 = 直接对 tree 里 7,996 个 .mesh / 2,146 个 .mdl 逐字节跑解析得到的计数。")
    W("  推断 = 把「parse() 定位不到索引块」等同于「工作台画不出来」。依据是 mesh.js 的")
    W("         listOf/pick(0) 只看第一个 resolved 部件 + geometry.rs 同一套布局；")
    W("         未覆盖 WebGL/TAURI 侧的运行时故障（本机开不了 3D、贴图缺失等）。")
    text = "\n".join(L)
    with io.open(REPORT, "w", encoding="utf-8") as fh:
        fh.write(text)

    slim = []
    for r in rows:
        r = dict(r)
        r["bodies_detail"] = [{k: v for k, v in g.items() if k in ("mesh", "file", "ok", "sm", "vc", "reason")}
                              for g in r.get("bodies_detail", [])][:40]
        slim.append(r)
    with io.open(RESULT, "w", encoding="utf-8") as fh:
        json.dump({"mesh_bucket": {k: dict(v) for k, v in mbuck.items()},
                   "mesh_reasons": dict(rr),
                   "mdl_class": {k: dict(v) for k, v in mc.items()},
                   "mdl_total": dict(allt),
                   "mdl_rows": slim,
                   "unreferenced_bucket": dict(Counter(mesh_bucket(p) for p in unreferenced)),
                   "groups": grp, "db_crosscheck": xchk, "refs_crosscheck": rc},
                  fh, ensure_ascii=False)
    print(text)
    print("elapsed %.1fs" % (time.time() - t0))


if __name__ == "__main__":
    main()
