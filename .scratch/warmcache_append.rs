// ----------------------------------------------------------------------- 预热缓存
//
// 预热（warm）每次启动把 13,080 组逐个做 SQLite 查询 + pak 回读，两三分钟且
// 不持久——纯内存的缓存每次重付。这里把成品 Lite 落盘成 JSON：下次启动直接
// 载入，秒级就绪。失效策略从宽：magic/版本/库指纹/组数对不上就整个弃用重跑
// 预热，绝不部分采信。

/// 缓存结构版本。DTO 或词表（场景/占位/缺口这些 &'static str 的取值集合）变动
/// 时必须 +1，旧缓存会整体作废重预热——宁可慢一次，不能摆错数据。
const WARM_CACHE_REV: u32 = 1;
const WARM_CACHE_MAGIC: &str = "TLBWARM";

#[derive(serde::Serialize, serde::Deserialize)]
struct WarmCache {
    magic: String,
    rev: u32,
    app: String,
    /// resources.db 的长度 + 修改时间：库重建过，缓存就没意义了。
    db_len: u64,
    db_mtime: i64,
    lites: Vec<LiteDto>,
}

#[derive(serde::Serialize, serde::Deserialize)]
struct LiteDto {
    group: GroupDto,
    name: String,
    subtitle: String,
    scenario: String,
    kind_zh: String,
    tags: Vec<String>,
    parts: Vec<CountDto>,
    placeholder: String,
    grade: String,
    gaps: Vec<String>,
    refs: Vec<RefDto>,
    located: usize,
    ref_total: usize,
    preview_candidates: Vec<u64>,
    hub_decoded: bool,
    rules: Vec<String>,
    members: Vec<MemberDto>,
}

#[derive(serde::Serialize, serde::Deserialize)]
struct GroupDto {
    id: i64,
    hub: String,
    hub_path: String,
    dir: String,
    stem: String,
    kind: String,
    n: i64,
    n_mesh: i64,
    n_mtl: i64,
    n_ani: i64,
    n_ske: i64,
    n_tex: i64,
}

#[derive(serde::Serialize, serde::Deserialize)]
struct CountDto {
    label: String,
    count: usize,
}

#[derive(serde::Serialize, serde::Deserialize)]
struct RefDto {
    name: String,
    kind: String,
    status: String,
    located: bool,
}

#[derive(serde::Serialize, serde::Deserialize)]
struct MemberDto {
    hash: String,
    role: String,
    path: Option<String>,
    rtype: String,
    pak: String,
    offset: i64,
    original: i64,
    ver: i64,
}

/// 把 String 固定成 &'static str（进程内泄漏，量级是词表那几十个词）。
/// Lite 的 scenario/placeholder/gaps 是 &'static str，来自代码里的固定词表；
/// 缓存里只有 String，回流时在这里重新扎根。
fn intern(s: &str) -> &'static str {
    use std::collections::HashMap;
    use std::sync::Mutex;
    static INTERN: OnceLock<Mutex<HashMap<Box<str>, &'static str>>> = OnceLock::new();
    let map = INTERN.get_or_init(|| Mutex::new(HashMap::new()));
    if let Ok(m) = map.lock() {
        if let Some(v) = m.get(s) {
            return v;
        }
        let leaked: &'static str = Box::leak(s.to_string().into_boxed_str());
        // 借用到此为止：leaked 指向泄漏的 Box，不依赖这份锁或这张表。
        m.insert(s.into(), leaked);
        return leaked;
    }
    Box::leak(s.to_string().into_boxed_str())
}

fn grade_to_letter(g: Grade) -> String {
    g.label().chars().next().unwrap_or('D').to_string()
}

fn grade_from_letter(s: &str) -> Option<Grade> {
    match s.trim().to_ascii_uppercase().as_str() {
        "A" => Some(Grade::A),
        "B" => Some(Grade::B),
        "C" => Some(Grade::C),
        "D" => Some(Grade::D),
        _ => None,
    }
}

fn lite_to_dto(l: &Lite) -> LiteDto {
    LiteDto {
        group: GroupDto {
            id: l.group.id,
            hub: format!("{:016x}", l.group.hub),
            hub_path: l.group.hub_path.clone(),
            dir: l.group.dir.clone(),
            stem: l.group.stem.clone(),
            kind: l.group.kind.clone(),
            n: l.group.n,
            n_mesh: l.group.n_mesh,
            n_mtl: l.group.n_mtl,
            n_ani: l.group.n_ani,
            n_ske: l.group.n_ske,
            n_tex: l.group.n_tex,
        },
        name: l.name.clone(),
        subtitle: l.subtitle.clone(),
        scenario: l.scenario.to_string(),
        kind_zh: l.kind_zh.clone(),
        tags: l.tags.clone(),
        parts: l
            .parts
            .iter()
            .map(|p| CountDto {
                label: p.label.clone(),
                count: p.count,
            })
            .collect(),
        placeholder: l.placeholder.to_string(),
        grade: grade_to_letter(l.grade),
        gaps: l.gaps.iter().map(|g| g.to_string()).collect(),
        refs: l
            .refs
            .iter()
            .map(|r| RefDto {
                name: r.name.clone(),
                kind: r.kind.clone(),
                status: r.status.clone(),
                located: r.located,
            })
            .collect(),
        located: l.located,
        ref_total: l.ref_total,
        preview_candidates: l.preview_candidates.clone(),
        hub_decoded: l.hub_decoded,
        rules: l.rules.clone(),
        members: l
            .members
            .iter()
            .map(|m| MemberDto {
                hash: format!("{:016x}", m.hash),
                role: m.role.clone(),
                path: m.path.clone(),
                rtype: m.rtype.clone(),
                pak: m.pak.clone(),
                offset: m.offset,
                original: m.original,
                ver: m.ver,
            })
            .collect(),
    }
}

/// 回流。任何对不上的字段（等级字母、编号格式）都返回 Err——整个缓存弃用，
/// 绝不半信半疑地摆数据。
fn lite_from_dto(d: LiteDto) -> Result<Lite, String> {
    let hub = u64::from_str_radix(&d.group.hub, 16).map_err(|_| "hub 编号坏".to_string())?;
    let grade = grade_from_letter(&d.grade).ok_or_else(|| "等级字母坏".to_string())?;
    let members = d
        .members
        .iter()
        .map(|m| {
            Ok(catalog::Member {
                hash: u64::from_str_radix(&m.hash, 16).map_err(|_| "成员编号坏".to_string())?,
                role: m.role.clone(),
                path: m.path.clone(),
                rtype: m.rtype.clone(),
                pak: m.pak.clone(),
                offset: m.offset,
                original: m.original,
                ver: m.ver,
            })
        })
        .collect::<Result<Vec<_>, String>>()?;
    Ok(Lite {
        group: catalog::Group {
            id: d.group.id,
            hub,
            hub_path: d.group.hub_path,
            dir: d.group.dir,
            stem: d.group.stem,
            kind: d.group.kind,
            n: d.group.n,
            n_mesh: d.group.n_mesh,
            n_mtl: d.group.n_mtl,
            n_ani: d.group.n_ani,
            n_ske: d.group.n_ske,
            n_tex: d.group.n_tex,
        },
        name: d.name,
        subtitle: d.subtitle,
        scenario: intern(&d.scenario),
        kind_zh: d.kind_zh,
        tags: d.tags,
        parts: d
            .parts
            .into_iter()
            .map(|p| Count {
                label: p.label,
                count: p.count,
            })
            .collect(),
        placeholder: intern(&d.placeholder),
        grade,
        gaps: d.gaps.iter().map(|g| intern(g)).collect(),
        refs: d
            .refs
            .into_iter()
            .map(|r| RefItem {
                name: r.name,
                kind: r.kind,
                status: r.status,
                located: r.located,
            })
            .collect(),
        located: d.located,
        ref_total: d.ref_total,
        preview_candidates: d.preview_candidates,
        hub_decoded: d.hub_decoded,
        rules: d.rules,
        members,
    })
}

impl AppData {
    fn warm_cache_path(&self) -> PathBuf {
        self.catalog_file
            .parent()
            .unwrap_or_else(|| Path::new("."))
            .join("warm_cache.json")
    }

    fn db_fingerprint(&self) -> (u64, i64) {
        match std::fs::metadata(&self.catalog_file) {
            Ok(m) => (
                m.len(),
                m.modified()
                    .ok()
                    .and_then(|t| {
                        t.duration_since(std::time::UNIX_EPOCH)
                            .ok()
                            .map(|d| d.as_secs() as i64)
                    })
                    .unwrap_or(0),
            ),
            Err(_) => (0, 0),
        }
    }

    /// 预热完成后把全部 Lite 写盘。失败只记日志——缓存是加速，不是数据源，
    /// 下次启动大不了重新预热。
    fn save_warm_cache(&self) {
        let lites: Vec<LiteDto> = match self.lite.lock() {
            Ok(lite) => lite.values().map(lite_to_dto).collect(),
            Err(_) => return,
        };
        let (db_len, db_mtime) = self.db_fingerprint();
        let cache = WarmCache {
            magic: WARM_CACHE_MAGIC.to_string(),
            rev: WARM_CACHE_REV,
            app: env!("CARGO_PKG_VERSION").to_string(),
            db_len,
            db_mtime,
            lites,
        };
        let path = self.warm_cache_path();
        let tmp = path.with_extension("json.tmp");
        match serde_json::to_string(&cache) {
            Ok(text) => {
                if std::fs::write(&tmp, &text).is_ok() && std::fs::rename(&tmp, &path).is_ok() {
                    eprintln!(
                        "warm-cache: saved {} lites -> {}",
                        cache.lites.len(),
                        path.display()
                    );
                }
            }
            Err(e) => eprintln!("warm-cache: 序列化失败：{e}"),
        }
    }

    /// 启动时尝试载入缓存。成功返回 true（lite 已满、ready=true，预热不再跑）。
    /// 任何一步不对就整体弃用，返回 false 走正常预热。
    pub fn try_load_warm_cache(self: &Arc<Self>) -> bool {
        let path = self.warm_cache_path();
        let Ok(text) = std::fs::read_to_string(&path) else {
            return false;
        };
        let cache: WarmCache = match serde_json::from_str(&text) {
            Ok(c) => c,
            Err(e) => {
                eprintln!("warm-cache: 读不出来（{e}），重新预热");
                return false;
            }
        };
        let (db_len, db_mtime) = self.db_fingerprint();
        if cache.magic != WARM_CACHE_MAGIC
            || cache.rev != WARM_CACHE_REV
            || cache.db_len != db_len
            || cache.db_mtime != db_mtime
            || cache.lites.len() != self.total
        {
            eprintln!("warm-cache: 指纹不匹配（库变过或结构升级），重新预热");
            return false;
        }
        let mut pairs = Vec::with_capacity(cache.lites.len());
        for d in cache.lites {
            match lite_from_dto(d) {
                Ok(l) => pairs.push((l.group.id, std::sync::Arc::new(l))),
                Err(e) => {
                    eprintln!("warm-cache: 条目回流失败（{e}），重新预热");
                    return false;
                }
            }
        }
        let n = pairs.len();
        if let Ok(mut lite) = self.lite.lock() {
            for (gid, l) in pairs {
                lite.insert(gid, l);
            }
            self.scanned.store(n, Ordering::SeqCst);
            self.ready.store(true, Ordering::SeqCst);
            eprintln!("warm-cache: 载入 {n} 组，预热跳过");
            true
        } else {
            false
        }
    }
}

#[cfg(test)]
mod warm_cache_tests {
    use super::*;

    /// 序列化→回流的字段保真。这是「缓存不许摆错数据」的底线测试。
    #[test]
    fn lite_dto_roundtrip() {
        let lite = Lite {
            group: catalog::Group {
                id: 42,
                hub: 0xaabbccdd11223344,
                hub_path: "data/source/npc/test.mdl".into(),
                dir: "data/source/npc".into(),
                stem: "test".into(),
                kind: "model".into(),
                n: 6,
                n_mesh: 1,
                n_mtl: 1,
                n_ani: 2,
                n_ske: 1,
                n_tex: 1,
            },
            name: "测试件".into(),
            subtitle: "test.mdl".into(),
            scenario: "角色",
            kind_zh: "模型".into(),
            tags: vec!["npc".into()],
            parts: vec![Count {
                label: "网格".into(),
                count: 1,
            }],
            placeholder: "角色",
            grade: Grade::B,
            gaps: vec!["贴图名对不上文件"],
            refs: vec![RefItem {
                name: "test_tex".into(),
                kind: "texture".into(),
                status: "只有名字".into(),
                located: false,
            }],
            located: 0,
            ref_total: 1,
            preview_candidates: vec![0x1234],
            hub_decoded: true,
            rules: vec!["规则一".into()],
            members: vec![catalog::Member {
                hash: 0xef01,
                role: "mesh".into(),
                path: Some("data/a.mesh".into()),
                rtype: "mesh".into(),
                pak: "data.pak".into(),
                offset: 7,
                original: 9,
                ver: 1,
            }],
        };
        let dto = lite_to_dto(&lite);
        let text = serde_json::to_string(&dto).unwrap();
        let back = lite_from_dto(serde_json::from_str(&text).unwrap()).unwrap();
        assert_eq!(back.group.id, 42);
        assert_eq!(back.group.hub, 0xaabbccdd11223344);
        assert_eq!(back.name, "测试件");
        assert_eq!(back.scenario, "角色");
        assert_eq!(back.placeholder, "角色");
        assert_eq!(back.gaps, vec!["贴图名对不上文件"]);
        assert!(matches!(back.grade, Grade::B));
        assert_eq!(back.members[0].hash, 0xef01);
        assert_eq!(back.preview_candidates, vec![0x1234]);
        assert!(back.hub_decoded);
        // &'static str 必须真的扎了根（能安全持有到进程结束）。
        let leaked: &'static str = back.scenario;
        assert_eq!(leaked, "角色");
    }

    #[test]
    fn grade_letter_rejects_garbage() {
        assert!(grade_from_letter("Q").is_none());
        assert!(grade_from_letter("A").is_some());
    }
}
