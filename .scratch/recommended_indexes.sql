-- ============================================================================
-- resources.db 索引优化建议（桌面资产浏览器上线前）
-- 只在副本上验证过；生产 db 是 Python 构建产物，请改 dbbuild.py 后重建，
-- 不要对已发布的 resources.db 就地执行本文件。
--
-- 实测汇总（副本 perf_probe.db，资源库 105,327 行 / 109.90 MB）：
--   体积   109.90 MB → 123.55 MB used（新增 8 条 +21.47 MB，删冗余 8 条 -7.82 MB）
--   构建期 建索引 419 ms → 967 ms + ANALYZE 116 ms（一次性，相对整库构建可忽略）
--   asset_cards --limit 100（热缓存稳态）177.5 ms → 134.0 ms，1.32x
--   asset_cards --limit 100（冷缓存/首启）675~840 ms → 122~140 ms，5.5x
--     对照组：不带任何新索引的同 schema 全新副本仍是 582~628 ms，排除了页布局差异
--   Catalog 单层：100 张卡的 SQL 141.80 ms → 49.44 ms，2.9x
-- 下面 A5 是收益最大的一条，只加它就能拿到端到端约一半的增益。
-- ============================================================================

-- 构建期：本库无外键，这句只表达意图。
PRAGMA foreign_keys = OFF;

-- ---------------------------------------------------------------------------
-- A. 新增：8 条
-- ---------------------------------------------------------------------------

-- A1 members(gid) —— 卡片构建里 DB 时间的大头（基线 100.65 ms/100 卡 = 71%）。
--     resources 的 hash 是 rowid 表的 TEXT 主键，命中自动索引后还要回表取整行
--     （行很宽：props/src/path 都在），这条覆盖索引让 JOIN 变成 index-only。
--     注意：必须配合 C 段的 ANALYZE，否则优化器不会选它（实测过）。
CREATE INDEX IF NOT EXISTS ix_res_hash_cover
    ON resources(hash, type, pak, offset, original, ver, path);

-- A2 by_type(type, N) —— 原来是 ix_res_type 取全部 texture 行再 temp b-tree 排序。
--     (type, hash) 与 ORDER BY hash 同序，LIMIT 可以提前停止。
CREATE INDEX IF NOT EXISTS ix_res_type_hash
    ON resources(type, hash);

-- A3 named_of_type() —— 两个 count(*)。WHERE type=? AND named=1 目前回表 10 万次。
--     (type, named) 是纯覆盖索引，count 只走索引页。
CREATE INDEX IF NOT EXISTS ix_res_type_named
    ON resources(type, named);

-- A4 groups(limit) —— 唯一的全表扫描 + 排序。ORDER BY n DESC 直接反向走索引。
CREATE INDEX IF NOT EXISTS ix_ag_n
    ON agroups(n DESC);

-- A5 textures_in_dir(dir) —— 本次审计最大的坑，务必优先落这条。
--     resources.dir 有 48,064/105,327 行是空串，其中 24,261 行是 texture。
--     旧计划 ix_res_dir + temp b-tree：dir='' 一次要扫 4.8 万条索引项、回表取宽行
--     再排序，实测 8.25 ms/次；asset_cards 每张卡至少调一次（材质引用解析不出来时
--     全靠它兜底）。新索引 (dir, type, original DESC) 与 WHERE+ORDER BY+LIMIT 完全
--     同序，实测 0.09 ms/次，92x。只加这一条，端到端 177.5 → 150.1 ms。
CREATE INDEX IF NOT EXISTS ix_res_dir_type_orig
    ON resources(dir, type, original DESC);

-- A6 tags(gid) —— WHERE gid=? ORDER BY confidence, tag 目前用 ix_tags_g 再 temp b-tree。
--     建全索引后过滤和排序一起解决；建好后 ix_tags_g 就多余了（见 B1）。
CREATE INDEX IF NOT EXISTS ix_tags_g_conf
    ON asset_tags(gid, confidence, tag);

-- A7 amembers：把驱动侧也做成覆盖 + 与 ORDER BY role 同序；替代 ix_am_g。
CREATE INDEX IF NOT EXISTS ix_am_g_role
    ON amembers(gid, role, hash);

-- A8 refs：WHERE from_hash=? ORDER BY kind, name。避免 temp b-tree。
CREATE INDEX IF NOT EXISTS ix_refs_from_kind
    ON refs(from_hash, kind, name, to_hash);

-- ---------------------------------------------------------------------------
-- B. 删除：冗余索引（左前缀已被主键/唯一索引覆盖，只拖慢构建期写入）
-- ---------------------------------------------------------------------------

-- B1 asset_tags PRIMARY KEY(gid, tag) 的自动索引左前缀就是 gid。
DROP INDEX IF EXISTS ix_tags_g;

-- B2 agroup_names UNIQUE(gid, name) 的自动索引同理。
DROP INDEX IF EXISTS ix_an_g;

-- B3 amembers UNIQUE(gid, hash) 的自动索引同理（且已被 A7 取代）。
DROP INDEX IF EXISTS ix_am_g;

-- B4 asset_fingerprint.gid 是 INTEGER PRIMARY KEY = rowid，按它建索引完全等价于主键。
DROP INDEX IF EXISTS ix_fingerprint_g;

-- B5 relations PRIMARY KEY(from_hash, to_hash, rel) 左前缀就是 from_hash。
DROP INDEX IF EXISTS ix_rel_from;

-- B6 refs.kind 只有 ~5 个取值，没有任何查询按 kind 过滤；选择性极低。
DROP INDEX IF EXISTS ix_refs_kind;

-- B7 被 A5 取代（dir 单列索引是 (dir,type,original) 的左前缀）。
DROP INDEX IF EXISTS ix_res_dir;

-- B8 被 A2/A3 取代：(type) 单列索引是 (type, hash) 和 (type, named) 的左前缀。
--     实测删掉后 counts()/by_type()/named_of_type() 的计划与耗时完全不变。
DROP INDEX IF EXISTS ix_res_type;

-- B9 没有查询按 ext 过滤（sqlite.rs 全量核对过）。若构建脚本也不用，可删；
--     保守起见我留成注释，请 grep dbbuild.py 里 ext 的用法后再决定。
-- DROP INDEX IF EXISTS ix_res_ext;

-- 冗余索引的根因在构建脚本：D:\TLGL\.scratch\dbbuild.py:692 那行
--   c.execute('CREATE INDEX ix_%s ON %s(gid)' % (table[6:] + '_g', table))
-- 对 asset_tags / agroup_names / asset_fingerprint 无差别建 (gid) 索引，
-- 而这三张表的 gid 分别是 PRIMARY KEY(gid,tag) 前缀、UNIQUE(gid,name) 前缀、
-- INTEGER PRIMARY KEY(=rowid)。请改这里，别只改 db。

-- ---------------------------------------------------------------------------
-- C. 必须执行：ANALYZE
-- ---------------------------------------------------------------------------
-- 本库当前没有 sqlite_stat1（实测确认）。没有统计信息时，SQLite 优化器会
-- 拒绝使用下面这条覆盖索引 ix_res_hash_cover，members(gid) 仍走"主键索引 +
-- 回表取宽行"，实测慢 1.8 倍。建完索引一定要 ANALYZE，否则 A1 等于白建。
ANALYZE;

-- ---------------------------------------------------------------------------
-- D. 明确不建议
-- ---------------------------------------------------------------------------
-- records(hash)：确实没有索引，按 hash 查 records 是全表扫（实测 3.0 ms/次）。
-- 但 Rust 侧目前根本不查这张表（asset_cards 用 pak.records() 线性扫，
-- preview-scan 用内存 HashMap）。若确实要在 SQL 里按 hash 取记录，再建：
-- CREATE INDEX ix_rec_hash ON records(hash);
-- 否则不要建，它只服务 114,975 行的构建期写入。
