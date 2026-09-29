//! 资源浏览（第一屏）：打开一个 data*.pak → 文件夹树 → 预览 → 导出。
//!
//! 检索视图（inspector.rs）按「资产组」组织，面向研究；本模块按「容器里的原始
//! 文件」组织，面向解包：左边选 pak，中间是原始路径的文件夹树，右边预览/导出。
//! 只读纪律与全库一致——客户端目录绝不写入；导出目录强制在客户端根之外，
//! 唯一例外是根下的 `.scratch/` 产物区（resources.db、预热缓存本来就在那里，
//! 前端默认导出目录也落在它下面）；无名文件以 16 位编号落盘，绝不编造路径。
//!
//! 名字来源只有一个：resources.db 的 resources 表（hash → 原始路径）。库不在时
//! 退化成「全部未命名」——照样能浏览、预览、导出，只是树里没有原始路径。

use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex, OnceLock};

use rusqlite::{Connection, OpenFlags};
use serde::Serialize;
use tauri::Emitter;
use tlbb_core::jmt1;
use tlbb_core::jpak::{Pak, Record};
use tlbb_core::payload;
use tlbb_core::preview::{png_bytes, scale_rgba};

use crate::inspector::{b64, roots};

// ----------------------------------------------------------------------- 返回模型

#[derive(Serialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct PakCard {
    pub name: String,
    pub size_bytes: u64,
    pub records: usize,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PakList {
    pub root: String,
    pub paks: Vec<PakCard>,
}

/// 树上的一条文件。`path` 为空表示无名：编号即身份，前端把它摆进「(未命名)」桶。
#[derive(Serialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct TreeEntry {
    pub hash: String,
    pub path: Option<String>,
    pub kind: String,
    pub ext: String,
    pub size: u32,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct TreeReply {
    pub pak: String,
    pub total: usize,
    pub named: usize,
    pub entries: Vec<TreeEntry>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct BrowsePreview {
    pub ok: bool,
    pub kind: String,
    pub mime: String,
    pub data_url: String,
    pub reason: String,
    pub info: Vec<String>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ExportReport {
    pub dest: String,
    pub written: usize,
    pub failed: Vec<String>,
    pub failed_more: usize,
}

// ----------------------------------------------------------------------- 名字表

type NameRow = (Option<String>, String, String);

/// hash（16 位小写十六进制）→ (原始路径?, 类型, 扩展名)。进程内只读一遍。
/// 无名条目（path 为 NULL）是客户端打包时剥离了文件名的那批——类型是内容
/// 分类器判定的，照实带给前端，但路径绝不编造。
fn name_table() -> Option<&'static HashMap<String, NameRow>> {
    static TABLE: OnceLock<Option<HashMap<String, NameRow>>> = OnceLock::new();
    TABLE
        .get_or_init(|| {
            let (_root, db) = roots();
            let con = Connection::open_with_flags(
                &db,
                OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
            )
            .ok()?;
            let mut out = HashMap::new();
            let mut stmt = con
                .prepare("SELECT hash, path, coalesce(type,''), coalesce(ext,'') FROM resources")
                .ok()?;
            let rows = stmt
                .query_map([], |r| {
                    Ok((
                        r.get::<_, String>(0)?,
                        r.get::<_, Option<String>>(1)?,
                        r.get::<_, String>(2)?,
                        r.get::<_, String>(3)?,
                    ))
                })
                .ok()?;
            for (h, p, t, e) in rows.flatten() {
                out.insert(h.to_ascii_lowercase(), (p, t, e));
            }
            Some(out)
        })
        .as_ref()
}

/// 只接受纯文件名，堵住路径穿越。
fn open_pak(root: &Path, name: &str) -> Result<Pak, String> {
    let safe = name.trim();
    if safe.is_empty() || safe.contains('/') || safe.contains('\\') || safe.contains("..") {
        return Err("pak 名不合法".into());
    }
    Pak::open(root.join(safe)).map_err(|e| format!("打开 {safe} 失败：{e}"))
}

/// Windows 的 canonicalize 返回 `\\?\` verbatim 前缀路径。导出校验两边都
/// canonicalize 时前缀本来一致，这里仍统一剥一遍再比——防的是将来有一侧
/// 混入非 canonicalize 的路径，出现「一边带前缀一边不带，starts_with 永远
/// 不中」的暗坑。
fn normalize_abs(p: &Path) -> PathBuf {
    let s = p.as_os_str().to_string_lossy();
    match s.strip_prefix(r"\\?\") {
        Some(rest) => PathBuf::from(rest),
        None => p.to_path_buf(),
    }
}

/// `p` 是否等于 base 或在其之下。Path::starts_with 按组件比，`.scratch2`
/// 不会被误当成 `.scratch` 的前缀——字符串比对才有那种坑。
fn under(p: &Path, base: &Path) -> bool {
    p == base || p.starts_with(base)
}

/// pak 名 → hash → 首个可读记录的进程级索引。browse_preview 每点一张图都要
/// 按 hash 找记录，直接遍历索引对十万条的 pak 是每次点击都重付一遍 O(N)；
/// 按 pak 建一次，之后 O(1)。客户端目录只读、pak 内容进程内不会变，索引
/// 不会过期；选条规则与 browse_tree/export_run 同一口径：stored>0、同 hash
/// 首个记录占位（or_insert 保留先到者，和线性 find 同序）。
fn pak_index(pak_name: &str, pak: &Pak) -> Arc<HashMap<u64, Record>> {
    static INDEX: OnceLock<Mutex<HashMap<String, Arc<HashMap<u64, Record>>>>> = OnceLock::new();
    let global = INDEX.get_or_init(|| Mutex::new(HashMap::new()));
    if let Ok(m) = global.lock() {
        if let Some(hit) = m.get(pak_name) {
            return Arc::clone(hit);
        }
    }
    // 慢路径在锁外建表，建完短锁放入。entry().or_insert 保证两个线程并发
    // 首建同一 pak 时只留一份——另一份白算一遍但结果一致，不值得为它再加
    // 一个「构建中」状态位。内存账：每条记录几十字节、全容器十几万条，和
    // data.rs 的 by_hash 同一量级，不是新的内存大头。
    let mut map: HashMap<u64, Record> = HashMap::with_capacity(pak.record_total());
    for rec in pak.records() {
        if rec.stored == 0 {
            continue; // 空位不是文件，预览/树/导出都不认
        }
        map.entry(rec.hash).or_insert(rec);
    }
    let arc = Arc::new(map);
    if let Ok(mut m) = global.lock() {
        m.entry(pak_name.to_string()).or_insert(Arc::clone(&arc));
    }
    arc
}

// ----------------------------------------------------------------------- 命令

/// 客户端根下能打开的 pak 一览。打开失败的不列——列出来也点不动。
#[tauri::command]
pub fn browse_paks() -> Result<PakList, String> {
    let (root, _db) = roots();
    let rd = std::fs::read_dir(&root).map_err(|e| format!("读不到客户端目录 {}：{e}", root.display()))?;
    let mut cards = Vec::new();
    for entry in rd.flatten() {
        let name = entry.file_name().to_string_lossy().to_string();
        if !name.to_ascii_lowercase().ends_with(".pak") {
            continue;
        }
        let Ok(pak) = Pak::open(entry.path()) else { continue };
        cards.push(PakCard {
            name,
            size_bytes: pak.file_size(),
            records: pak.record_total(),
        });
    }
    cards.sort_by(|a, b| a.name.cmp(&b.name));
    Ok(PakList {
        root: root.to_string_lossy().to_string(),
        paks: cards,
    })
}

/// 一个 pak 的全部条目（去重后）。树在前端拼：路径本来就是树。
/// 选条口径必须与 export_run 一致（stored>0 + hash 去重）——树里摆出来的
/// 每一个文件就是整包导出会落盘的每一个文件，两边数字对不上就是 bug。
#[tauri::command]
pub fn browse_tree(pak_name: String) -> Result<TreeReply, String> {
    let (root, _db) = roots();
    let pak = open_pak(&root, &pak_name)?;
    let names = name_table();
    let mut entries: Vec<TreeEntry> = Vec::with_capacity(pak.record_total());
    let mut seen: HashSet<u64> = HashSet::new();
    let mut named = 0usize;
    for rec in pak.records() {
        if rec.stored == 0 || !seen.insert(rec.hash) {
            continue;
        }
        let hex = format!("{:016x}", rec.hash);
        let (path, kind, ext) = match names.and_then(|t| t.get(&hex)) {
            Some((Some(p), t, e)) => {
                named += 1;
                (Some(p.clone()), t.clone(), e.clone())
            }
            // 无名不等于无类型：内容分类器判定过的类型照实带上。
            Some((None, t, e)) => (None, t.clone(), e.clone()),
            None => (None, String::new(), String::new()),
        };
        entries.push(TreeEntry {
            hash: hex,
            path,
            kind,
            ext,
            size: rec.original,
        });
    }
    let total = entries.len();
    Ok(TreeReply {
        pak: pak_name,
        total,
        named,
        entries,
    })
}

fn sniff(bytes: &[u8]) -> &'static str {
    if bytes.starts_with(b"JMT1") {
        "texture"
    } else if bytes.starts_with(b"DDS ") {
        "dds"
    } else if bytes.starts_with(&[0x89, b'P', b'N', b'G']) {
        "png"
    } else if bytes.starts_with(&[0xFF, 0xD8]) {
        "jpeg"
    } else if bytes.starts_with(b"RIFF") {
        "webp"
    } else {
        "other"
    }
}

/// 单文件预览：贴图出大图（长边 ≤1024），其他类型给事实摘要。解不出图就照实
/// 说原因，绝不拿别的图顶。
#[tauri::command]
pub fn browse_preview(pak_name: String, hash: String) -> Result<BrowsePreview, String> {
    let (root, _db) = roots();
    let pak = open_pak(&root, &pak_name)?;
    let h = u64::from_str_radix(hash.trim().trim_start_matches("0x"), 16)
        .map_err(|_| "编号格式不对".to_string())?;
    // hash→记录走进程级索引：这个 pak 的第一张图付一次全索引遍历，之后
    // 每次点击 O(1)。pak 仍要开——解字节要 mmap 里的数据。
    let rec = pak_index(&pak_name, &pak)
        .get(&h)
        .copied()
        .ok_or_else(|| "这个编号不在这个 pak 里".to_string())?;
    let dec = payload::decode(&pak, &rec).map_err(|e| format!("取字节失败：{e}"))?;
    let kind = name_table()
        .and_then(|t| t.get(&hash.trim().to_ascii_lowercase()))
        .map(|(_, t, _)| t.clone())
        .filter(|t| !t.is_empty())
        .unwrap_or_else(|| sniff(&dec.bytes).to_string());

    let mut info = vec![format!("原始大小 {} 字节", dec.bytes.len())];
    let empty = BrowsePreview {
        ok: false,
        kind: kind.clone(),
        mime: String::new(),
        data_url: String::new(),
        reason: String::new(),
        info: info.clone(),
    };
    match kind.as_str() {
        "texture" => {
            let t = match jmt1::decode(&dec.bytes) {
                Ok(t) => t,
                Err(e) => {
                    return Ok(BrowsePreview {
                        reason: format!("贴图解码失败：{e}"),
                        ..empty
                    })
                }
            };
            info.insert(0, format!("尺寸 {} × {} · 编码 {}", t.width, t.height, t.codec.as_str()));
            if let Some(w) = &t.webp {
                return Ok(BrowsePreview {
                    ok: true,
                    kind,
                    mime: "image/webp".into(),
                    data_url: format!("data:image/webp;base64,{}", b64(w)),
                    reason: String::new(),
                    info,
                });
            }
            if t.rgba.is_empty() {
                return Ok(BrowsePreview {
                    reason: format!("编码 {} 无像素，出不了图", t.codec.as_str()),
                    info,
                    ..empty
                });
            }
            let (scaled, w, h) = scale_rgba(&t.rgba, t.width as usize, t.height as usize, 1024);
            let png = png_bytes(w as u16, h as u16, &scaled, true)
                .map_err(|e| format!("编码 PNG 失败：{e}"))?;
            Ok(BrowsePreview {
                ok: true,
                kind,
                mime: "image/png".into(),
                data_url: format!("data:image/png;base64,{}", b64(&png)),
                reason: String::new(),
                info,
            })
        }
        "webp" => Ok(BrowsePreview {
            ok: true,
            kind,
            mime: "image/webp".into(),
            data_url: format!("data:image/webp;base64,{}", b64(&dec.bytes)),
            reason: String::new(),
            info,
        }),
        "jpeg" => Ok(BrowsePreview {
            ok: true,
            kind,
            mime: "image/jpeg".into(),
            data_url: format!("data:image/jpeg;base64,{}", b64(&dec.bytes)),
            reason: String::new(),
            info,
        }),
        "png" => Ok(BrowsePreview {
            ok: true,
            kind,
            mime: "image/png".into(),
            data_url: format!("data:image/png;base64,{}", b64(&dec.bytes)),
            reason: String::new(),
            info,
        }),
        "mesh" => {
            // 网格出不了「一张图」，但文件里有什么是可以说的：几何、骨架节点，
            // 以及还缺什么。骨架名字与 .ani 的骨名表能一一对上（有用例钉着），
            // 父子关系与蒙皮权重仍未解——照实写在同一行里。
            match tlbb_core::preview::parse_geometry(&dec.bytes) {
                Ok(g) => {
                    let nodes = tlbb_core::preview::parse_nodes(&dec.bytes);
                    info.push(format!(
                        "顶点 {} · 面 {} · 法线 {} · UV {}",
                        g.vertex_count,
                        g.face_count,
                        if g.normals.is_empty() { "无（前端自算）" } else { "有" },
                        if g.uvs.is_empty() { "无" } else { "有" }
                    ));
                    if nodes.is_empty() {
                        info.push("这份文件里没有骨架节点表（静态网格）".into());
                    } else {
                        let head = nodes
                            .iter()
                            .take(4)
                            .map(|n| n.name.clone())
                            .collect::<Vec<_>>()
                            .join("、");
                        info.push(format!(
                            "骨架节点 {} 个：{head} 等（名字与动作文件的骨名表对得上，每个都带绑定矩阵）",
                            nodes.len()
                        ));
                        info.push(
                            "还不能驱动模型：节点记录里没有父指针（父子关系未解），蒙皮权重也不在这份文件里"
                                .into(),
                        );
                    }
                    Ok(BrowsePreview {
                        ok: false,
                        kind,
                        info,
                        ..empty
                    })
                }
                Err(e) => {
                    info.push(format!("几何解不出来：{e}"));
                    Ok(BrowsePreview {
                        ok: false,
                        kind,
                        info,
                        ..empty
                    })
                }
            }
        }
        "JBPU" => {
            // 特效定义：驻留字符串里写着它用哪个材质、什么混合模式、什么发射器。
            // 这条链是从文件内容里读的，不是按文件名猜的——建库算 refs 用的就是
            // 同一套分类，界面上以前反而看不到。
            match tlbb_core::preview::parse_pu(&dec.bytes) {
                Some(e) => {
                    let n = &e.names;
                    let head = if n.name.is_empty() { "（没读到名字）" } else { &n.name };
                    info.push(format!("特效 {head} · 驻留字符串 {} 条", e.strings.len()));
                    let mut bits: Vec<String> = Vec::new();
                    if !n.materials.is_empty() {
                        bits.push(format!("材质 {}", n.materials.join("、")));
                    }
                    if !n.blends.is_empty() {
                        bits.push(format!("混合 {}", n.blends.join("、")));
                    }
                    if !n.renderers.is_empty() {
                        bits.push(format!("渲染器 {}", n.renderers.join("、")));
                    }
                    if !n.emitters.is_empty() {
                        bits.push(format!("发射器 {}", n.emitters.join("、")));
                    }
                    if !n.updaters.is_empty() {
                        bits.push(format!("更新器 {}", n.updaters.join("、")));
                    }
                    if !n.dynamics.is_empty() {
                        bits.push(format!("动态参数 {}", n.dynamics.len()));
                    }
                    if !bits.is_empty() {
                        info.push(bits.join(" · "));
                    }
                    let refs = n.materials.len() + n.textures.len() + n.meshes.len();
                    info.push(format!(
                        "参数块 {} 字节（{} 个像浮点的数）——字段名未解，只报数量；引用到资源 {} 个",
                        e.param_bytes, e.param_floats, refs
                    ));
                    Ok(BrowsePreview {
                        ok: false,
                        kind,
                        info,
                        ..empty
                    })
                }
                None => {
                    info.push("不是已知的 JBPU 布局（不硬猜字段）".into());
                    Ok(BrowsePreview {
                        ok: false,
                        kind,
                        info,
                        ..empty
                    })
                }
            }
        }
        "ani" => {
            // 动作文件出不了画面，但不是「没内容可看」：关键帧已能数出来。
            // 照实报账，并报清为什么还不能播。
            match tlbb_core::preview::parse_ani(&dec.bytes) {
                Some(a) => {
                    let moving = a
                        .tracks
                        .iter()
                        .filter(|t| t.rotations.windows(2).any(|w| w[0] != w[1]))
                        .count();
                    let named = a.tracks.iter().filter(|t| !t.bone.is_empty()).count();
                    info.push(format!(
                        "骨骼 {} 条 · 关键帧 {} 帧 · 帧率刻度 {}",
                        a.bones,
                        a.frames,
                        a.tick
                    ));
                    info.push(format!(
                        "会动的骨 {moving} 根（其余各帧旋转相同）· 骨名读到 {named} 条"
                    ));
                    info.push(
                        "还不能播放：父骨链与蒙皮权重不在这份文件里（.ske 是动作登记表，\
                         也没有骨架矩阵）"
                            .into(),
                    );
                    Ok(BrowsePreview {
                        ok: false,
                        kind,
                        mime: String::new(),
                        data_url: String::new(),
                        reason: String::new(),
                        info,
                    })
                }
                None => {
                    info.push("关键帧布局不认（不硬猜）".into());
                    Ok(BrowsePreview {
                        ok: false,
                        kind,
                        info,
                        ..empty
                    })
                }
            }
        }
        other => {
            let head: Vec<String> = dec
                .bytes
                .iter()
                .take(8)
                .map(|b| format!("{b:02X}"))
                .collect();
            info.push(format!(
                "文件头 {}（{} 类内部文件，暂无画面可预览，可直接导出）",
                head.join(" "),
                other
            ));
            Ok(BrowsePreview {
                ok: false,
                kind,
                mime: String::new(),
                data_url: String::new(),
                reason: String::new(),
                info,
            })
        }
    }
}

/// Windows 保留设备名。任何一段「点前主名」命中都拒——向 CON/NUL 写内容是
/// 写设备不是写文件，COM1 一类同理；不分大小写、带不带扩展名都算。
const RESERVED_NAMES: &[&str] = &[
    "CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8",
    "COM9", "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
];

fn reserved_name(seg: &str) -> bool {
    let stem = seg.split('.').next().unwrap_or("");
    RESERVED_NAMES
        .iter()
        .any(|r| stem.eq_ignore_ascii_case(r))
}

/// 把客户端原始路径接到导出目录下。逐段清洗：拒掉「..」、空段、盘符冒号、
/// Windows 非法字符、控制字符、保留设备名和尾点（尾点落盘会被 Windows 静默
/// 剥掉，写出的名字就和库里登记的对不上了；尾空格已被 trim 归一）；有哪一段
/// 不干净就整个放弃——宁可少导出一个文件，不写出客户端里不存在的路径。
///
/// 穿越面收口：先统一成 `/` 再切段，段里不可能再有分隔符；`..`、绝对盘符、
/// 开头分隔符都在逐段清洗里挡掉，拼接结果只会落在 dest 之内。导出总开关
/// （根内非 `.scratch` 拒绝）是最后一道防线。
///
/// 超长路径不必在这里挡：dest 是 canonicalize 出的 `\\?\` verbatim 路径，
/// 其下的拼接不受 MAX_PATH 限制；真长到越限会在写盘时收到错误、计入
/// failed——不 panic，也不逃出 dest。
fn safe_join(dest: &Path, raw: &str) -> Option<PathBuf> {
    let raw = raw.trim().replace('\\', "/");
    let mut out = dest.to_path_buf();
    for seg in raw.split('/') {
        let seg = seg.trim();
        if seg.is_empty() || seg == "." || seg == ".." {
            return None;
        }
        if seg.contains(':')
            || seg
                .bytes()
                .any(|b| matches!(b, b'<' | b'>' | b'"' | b'|' | b'?' | b'*' | 0x00..=0x1F | 0x7F))
        {
            return None;
        }
        if reserved_name(seg) || seg.ends_with('.') {
            return None;
        }
        out.push(seg);
    }
    Some(out)
}

/// 导出。`hashes` 为空表示整包。目标目录必须在客户端根之外，或客户端根下的
/// `.scratch/` 产物区——客户端目录其余部分只读。
///
/// 整包可能十几万个文件、跑好几分钟：真正的活儿在 `export_run` 里，用
/// spawn_blocking 丢进阻塞线程池，别占着 IPC 线程；进度经 `exporting` 事件
/// 边跑边广播（载荷 `{pak, done, total, written, failed}`，收尾多发一条
/// `finished: true`、`done: total`），命令本身等干完才回包。
#[tauri::command]
pub async fn browse_export(
    app: tauri::AppHandle,
    pak_name: String,
    hashes: Vec<String>,
    dest: String,
) -> Result<ExportReport, String> {
    tauri::async_runtime::spawn_blocking(move || {
        // 进度直接接到 AppHandle::emit 上；发射失败（比如窗口已关）不必让导出陪葬。
        let sink = |v: serde_json::Value| {
            let _ = app.emit("exporting", v);
        };
        export_run(&pak_name, &hashes, &dest, &sink)
    })
    .await
    .map_err(|e| format!("导出任务异常中断：{e}"))?
}

/// 解包一个条目并写盘。建目录、写盘哪步失败都算这个文件失败，照实记下。
///
/// 落盘前先过 `WriteGuard`：目录已经建出来才校验，是因为 junction 只存在于
/// 真实文件系统里，不建目录就解析不出它指向哪儿。校验不过 → 这个文件不写，
/// 计一条 failed（客户端目录里因此多出的空目录壳由 guard 自己收走）。
fn decode_and_write(
    pak: &Pak,
    rec: &Record,
    target: &Path,
    guard: &WriteGuard,
) -> Result<(), String> {
    payload::decode(pak, rec)
        .map_err(|e| format!("解包失败：{e}"))
        .and_then(|dec| {
            if let Some(dir) = target.parent() {
                std::fs::create_dir_all(dir).map_err(|e| format!("建目录失败：{e}"))?;
            }
            let real = guard.check(target)?;
            std::fs::write(&real, &dec.bytes).map_err(|e| format!("写盘失败：{e}"))
        })
}

/// 逐文件落盘闸门。`export_run` 开头那道校验只看得出「用户指的目录」在不在
/// 客户端根里，看不出那个目录下面藏着指向根内的 junction / 符号链接：
/// `dest/data` 是一条指向 `<客户端根>/protected` 的 junction 时，名字表里的
/// `data/protected/.../x.mesh` 会一路跟着链接写进客户端目录——客户端目录是
/// 只读的，这条纪律不能靠路径写法来保证。
///
/// 办法是不信拼接结果，信解析结果：每个目标写之前解析成真实路径（canonicalize
/// 跟着链接走到底），要求它仍落在导出目录之内、且不在客户端根之内（`.scratch`
/// 例外）。链接指向根外别处也一样拦——那已经不是用户指定的导出目录了。
struct WriteGuard {
    dest: PathBuf,
    root: PathBuf,
    scratch: PathBuf,
}

/// 按路径组件逐个比、不区分大小写（Windows 本来就不区分）。`starts_with` 走
/// OsStr 逐字节比对，名字表里的大小写和磁盘上落盘的大小写不一致时会误判成
/// 「跑出去了」；字符串前缀比又有 `.scratch2` 冒充 `.scratch` 的那种坑，
/// 所以按组件切开来一段一段比。
fn under_ci(p: &Path, base: &Path) -> bool {
    let segs = |x: &Path| -> Vec<String> {
        x.components()
            .map(|c| c.as_os_str().to_string_lossy().to_ascii_lowercase())
            .collect()
    };
    let (a, b) = (segs(p), segs(base));
    a.len() >= b.len() && a[..b.len()] == b[..]
}

/// 解析到「最近一个已经存在的祖先」的真实路径，再把尚未落盘的尾部组件挂回去。
/// 尾部组件还没写出来，不可能已经是链接，所以这样得到的路径就是内核将要写入
/// 的位置。目标本身存在时直接解析它——这样连「目标已是指向别处的链接」也看得见。
fn resolve_real(target: &Path) -> Option<PathBuf> {
    let mut tail: Vec<std::ffi::OsString> = Vec::new();
    let mut cur = target;
    loop {
        if let Ok(c) = cur.canonicalize() {
            let mut p = normalize_abs(&c);
            for seg in tail.iter().rev() {
                p.push(seg);
            }
            return Some(p);
        }
        tail.push(cur.file_name()?.into());
        cur = cur.parent()?;
    }
}

impl WriteGuard {
    fn new(dest: &Path, root: &Path, scratch: &Path) -> Self {
        WriteGuard {
            dest: dest.into(),
            root: root.into(),
            scratch: scratch.into(),
        }
    }

    /// 放行返回真正要写的路径，拒绝说明理由。
    fn check(&self, target: &Path) -> Result<PathBuf, String> {
        let real = resolve_real(target).ok_or_else(|| "目标路径无法解析，已跳过".to_string())?;
        if !under_ci(&real, &self.dest) {
            return Err("导出目录里有链接/junction 指向目录之外，为不写到指定目录以外已跳过".into());
        }
        if under_ci(&real, &self.root) && !under_ci(&real, &self.scratch) {
            return Err("导出目录里有链接/junction 指回客户端目录（只读），已跳过".into());
        }
        Ok(real)
    }
}

/// 导出核心循环。`progress` 是进度出口：核心只管发一条进度 JSON，接到哪儿是
/// 调用者的事——命令接 AppHandle::emit，测试接 `Arc<Mutex<Vec<_>>>` 收集器
/// （测试环境拿不到 AppHandle，也不为测试去起假窗口）。
pub(crate) fn export_run(
    pak_name: &str,
    hashes: &[String],
    dest: &str,
    progress: &dyn Fn(serde_json::Value),
) -> Result<ExportReport, String> {
    let (root, _db) = roots();
    let dest_path = PathBuf::from(dest.trim());
    if dest_path.as_os_str().is_empty() {
        return Err("先填导出目录".into());
    }
    // 目标先建出来再 canonicalize：相对路径、末尾斜杠、大小写只有文件系统能
    // 归一。canonicalize 在 Windows 返回 `\\?\` verbatim 路径——保留它原样
    // 做拼接基底（verbatim 路径不受 MAX_PATH 限制），比较时才用 normalize_abs
    // 剥成统一形态。
    // 目录是不是本来就存在要先记下：拒绝导出时只收走自己刚建的空目录，
    // 不能顺手动客户端里原有的目录——哪怕只是删个空壳，也是往只读目录里动手。
    let dest_existed = dest_path.is_dir();
    std::fs::create_dir_all(&dest_path).map_err(|e| format!("建导出目录失败：{e}"))?;
    let d = dest_path.canonicalize().map_err(|e| format!("导出目录无效：{e}"))?;
    let r = root.canonicalize().map_err(|e| format!("客户端目录无效：{e}"))?;
    // 客户端目录只读：dest 在根内一律拒绝，唯一例外是根下的 `.scratch/`——
    // 既有产物区（resources.db、预热缓存、树缓存都在里面），前端默认导出
    // 目录也落在它下面。`.scratch` 还不存在时 dest 不可能在它里面，用规范化
    // 后的根拼一个同形路径兜底，保证比较两边前缀形态一致。
    let dn = normalize_abs(&d);
    let rn = normalize_abs(&r);
    let scratch = root
        .join(".scratch")
        .canonicalize()
        .map(|p| normalize_abs(&p))
        .unwrap_or_else(|_| rn.join(".scratch"));
    if under(&dn, &rn) && !under(&dn, &scratch) {
        // 只删得掉空目录，且仅限这次调用新建的：拒绝导出时不在客户端目录里
        // 留壳，也绝不碰用户指过来的已有目录。
        if !dest_existed {
            let _ = std::fs::remove_dir(&dest_path);
        }
        return Err(
            "导出目录不能放在客户端目录里——客户端目录只读，请导到客户端根下的 .scratch/ 或根之外"
                .into(),
        );
    }

    let pak = open_pak(&root, pak_name)?;
    let names = name_table();
    let want: Option<HashSet<u64>> = if hashes.is_empty() {
        None
    } else {
        Some(
            hashes
                .iter()
                .filter_map(|s| u64::from_str_radix(s.trim().trim_start_matches("0x"), 16).ok())
                .collect(),
        )
    };
    // 伪成功防线一：传了编号却一个都解析不了。照实报错——回一个
    // written=0、failed 空的「成功」包，前端只会显示「已导出 0 个文件」，
    // 用户根本无从知道是自己把编号填坏了。
    if let Some(w) = &want {
        if w.is_empty() {
            return Err("编号一个都解析不了：应为 16 位十六进制（可带 0x 前缀）".into());
        }
    }

    // 先把要导的条目数一遍：进度条的 total 必须是准数——重复条目和 stored==0
    // 的空位不是文件，拿原始记录数糊弄，进度条永远走不到头。
    let mut targets: Vec<Record> = Vec::new();
    let mut seen: HashSet<u64> = HashSet::new();
    for rec in pak.records() {
        if rec.stored == 0 || !seen.insert(rec.hash) {
            continue;
        }
        if let Some(w) = &want {
            if !w.contains(&rec.hash) {
                continue;
            }
        }
        targets.push(rec);
    }
    let total = targets.len();
    // 伪成功防线二：编号能解析、但在 pak 里一条都对不上（或全 stored==0）。
    // 整包导出（want=None）遇到空 pak 才是合法的 0 文件，按选择导出的必须出声。
    if want.is_some() && total == 0 {
        return Err(format!("这些编号在 {pak_name} 里没有可导出的条目"));
    }

    let mut written = 0usize;
    let mut failed = Vec::new();
    let mut failed_more = 0usize;
    let mut done = 0usize;
    let mut last_emit = std::time::Instant::now();
    // 逐文件闸门：开头的目录校验挡的是「指到客户端根里」，这里挡的是
    // 「指到客户端根里的那条链接」。两个面都要收，只读纪律才不是纸面规矩。
    let guard = WriteGuard::new(&dn, &rn, &scratch);
    // 同一导出路径只落第一个编号。名字表脏数据（两个不同编号挂同一条原始
    // 路径）时，谁后到谁覆盖会让幸存的内容全看排序运气；这里跳过后写的、
    // 计入 failed 并如实报出来——written 从此等于磁盘上实际多出的文件数。
    // 无名条目按各自编号落盘不会撞路径，这个闸只对名字表来的路径有意义。
    let mut used_paths: HashSet<PathBuf> = HashSet::new();
    for rec in &targets {
        let hex = format!("{:016x}", rec.hash);
        // 无名条目不在名字表里（表只收有路径的行），扩展名确实无从知道，
        // 落盘就是 编号.bin——不猜。
        let target = match names.and_then(|t| t.get(&hex)) {
            Some((Some(p), _, _)) => safe_join(&d, p),
            // 无名（库里只有编号和类型，没有路径）或完全没登记：按编号落盘，不猜名字。
            _ => Some(d.join("_未命名").join(format!("{hex}.bin"))),
        };
        let label = target
            .as_deref()
            .and_then(|t| t.strip_prefix(&d).ok())
            .map(|p| p.to_string_lossy().to_string())
            .unwrap_or_else(|| hex.clone());
        // 路径不安全也是「处理完了一个」：done 照样销账，不然进度条到不了头。
        let res = match target {
            // insert 返回 false = 路径已被前一个编号占用 → 跳过这次写。
            Some(t) if used_paths.insert(t.clone()) => decode_and_write(&pak, rec, &t, &guard),
            Some(_) => Err("同一导出路径已被另一个编号占用（名字表脏数据），为免覆盖只保留先导出的".into()),
            None => Err("路径不安全，已跳过".into()),
        };
        match res {
            Ok(()) => written += 1,
            Err(e) => {
                if failed.len() < 50 {
                    failed.push(format!("{label}：{e}"));
                } else {
                    failed_more += 1;
                }
            }
        }
        done += 1;
        // 节流：满 100 个文件或距上次 300ms 才广播一条——十几万条事件会把 IPC
        // 淹掉，几百条足够让进度条活着。进度按「处理了几个文件」计，解包前
        // 不知道字节数，按字节计就要先付一遍解包的代价。
        if done % 100 == 0 || last_emit.elapsed() >= std::time::Duration::from_millis(300) {
            last_emit = std::time::Instant::now();
            progress(serde_json::json!({
                "pak": pak_name,
                "done": done,
                "total": total,
                "written": written,
                "failed": failed.len() + failed_more,
            }));
        }
    }
    // 收尾必发一条 finished=true：进度条靠它收起，done 恒等于 total。
    progress(serde_json::json!({
        "pak": pak_name,
        "done": total,
        "total": total,
        "written": written,
        "failed": failed.len() + failed_more,
        "finished": true,
    }));

    Ok(ExportReport {
        dest: d.to_string_lossy().to_string(),
        written,
        failed,
        failed_more,
    })
}

// ----------------------------------------------------------------------- 测试
// 直接吃本机真数据（TLBB_ROOT 默认 D:/TLGL）：这是「打开→树→预览→导出」四件事
// 的功能闭环测试，比截图可靠。没有客户端的机器上会因 browse_paks 报错而跳过。

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::{Arc, Mutex};

    /// 进度事件收集器：export_run 发的每条 JSON 都攒下来给断言用。AppHandle
    /// 在测试环境拿不到（也不为测试去起一个假窗口），所以进度出口抽成了
    /// 闭包参数——命令接 emit，测试接这里，核心循环只有一份。
    type EventLog = Arc<Mutex<Vec<serde_json::Value>>>;

    fn sink_of(log: &EventLog) -> impl Fn(serde_json::Value) + '_ {
        let log = Arc::clone(log);
        move |v| log.lock().unwrap().push(v)
    }

    #[test]
    fn paks_listed_and_tree_named() {
        let list = browse_paks().expect("browse_paks 应能列出客户端根下的 pak");
        assert!(!list.paks.is_empty(), "客户端根下应有 pak");
        let name = list.paks[0].name.clone();
        let tree = browse_tree(name).expect("browse_tree 应能遍历 pak");
        assert!(tree.total > 0, "条目数应大于 0");
        if name_table().is_some() {
            assert!(tree.named > 0, "有名字表时必须有条目带上原始路径");
        }
    }

    #[test]
    fn preview_and_export_roundtrip() {
        let list = browse_paks().expect("browse_paks");
        let name = list.paks[0].name.clone();
        let tree = browse_tree(name.clone()).expect("browse_tree");

        // 找一张有名贴图试预览：本机基线里贴图一定能解出像素。
        if let Some(tex) = tree.entries.iter().find(|e| e.kind == "texture") {
            let pv = browse_preview(name.clone(), tex.hash.clone()).expect("browse_preview 调用");
            assert!(pv.ok, "贴图应出图，实际原因：{}", pv.reason);
            assert!(pv.data_url.starts_with("data:image/"));
        }

        // 导出一个有名文件到系统临时目录（必在客户端根之外）。
        let some = tree
            .entries
            .iter()
            .find(|e| e.path.is_some())
            .expect("有名字表时应有有名条目");
        let dest = std::env::temp_dir().join("tlbb_browse_export_test");
        let log = EventLog::default();
        let rep = export_run(
            &name,
            std::slice::from_ref(&some.hash),
            &dest.to_string_lossy().to_string(),
            &sink_of(&log),
        )
        .expect("export_run 调用");
        assert_eq!(rep.written, 1, "应导出 1 个文件");
        assert!(rep.failed.is_empty(), "不应有失败：{:?}", rep.failed);

        // 进度事件是真从核心循环里发出来的：最后一条必须是收尾包——
        // finished=true、done=total，成功数与回包一致。
        let evs = log.lock().unwrap();
        assert!(!evs.is_empty(), "导出至少要广播一次进度事件");
        let last = evs.last().unwrap();
        assert_eq!(last["finished"], true, "最后一条事件应 finished=true：{last}");
        assert_eq!(last["done"], last["total"], "收尾包 done 应等于 total：{last}");
        assert_eq!(last["total"], 1, "只导一个文件，total 应为 1：{last}");
        assert_eq!(last["written"], 1, "收尾包成功数应与回包一致：{last}");
        drop(evs);

        // 只读纪律：导出目录在客户端根内必须被拒。
        let (root, _) = roots();
        let quiet = |_: serde_json::Value| {};
        assert!(
            export_run(&name, &[], &root.to_string_lossy().to_string(), &quiet).is_err(),
            "导出到客户端根内必须报错"
        );
        std::fs::remove_dir_all(&dest).ok();
    }

    #[test]
    fn export_dest_rules_root_vs_scratch() {
        let list = browse_paks().expect("browse_paks");
        let name = list.paks[0].name.clone();
        let tree = browse_tree(name.clone()).expect("browse_tree");
        let some = tree
            .entries
            .iter()
            .find(|e| e.path.is_some())
            .expect("有名字表时应有有名条目");
        let (root, _) = roots();
        let quiet = |_: serde_json::Value| {};
        let one = std::slice::from_ref(&some.hash);

        // 根内、不在 .scratch：拒绝——前端默认导出目录历史上就栽在这条规则上。
        let inside = root.join("unpacked_tlbb_browse_test");
        assert!(
            export_run(&name, one, &inside.to_string_lossy().to_string(), &quiet).is_err(),
            "导出到客户端根内非 .scratch 必须报错"
        );
        // 拒绝时不留壳：刚建出来的空目录要被收尾清掉。
        assert!(
            !inside.exists(),
            "被拒的导出不应在客户端目录里留下空目录"
        );

        // 根内 .scratch：产物区（resources.db、预热缓存都在那里），允许，
        // 真导一个验证能落盘。
        let scratch_dest = root.join(".scratch").join("tlbb_browse_export_test");
        let rep = export_run(&name, one, &scratch_dest.to_string_lossy().to_string(), &quiet)
            .expect("导出到 root/.scratch 应被允许");
        assert_eq!(rep.written, 1, ".scratch 导出应落盘 1 个文件");
        assert!(rep.failed.is_empty(), "不应有失败：{:?}", rep.failed);
        // 清理只清自己刚写的产物目录——.scratch 是公区，别整树删。
        std::fs::remove_dir_all(&scratch_dest).ok();
    }

    #[test]
    fn export_refuses_pseudo_success_and_keeps_preexisting_dir() {
        let list = browse_paks().expect("browse_paks");
        let name = list.paks[0].name.clone();
        let (root, _) = roots();
        let quiet = |_: serde_json::Value| {};
        let dest = std::env::temp_dir().join("tlbb_browse_export_guard_test");

        // 伪成功防线一：传了编号却一个都解析不了 → 报错，而不是
        // written=0、failed 空的「成功」包。
        let bad = vec!["nothex".to_string(), "zzz".to_string()];
        assert!(
            export_run(&name, &bad, &dest.to_string_lossy().to_string(), &quiet).is_err(),
            "编号全不可解析必须报错"
        );
        // 伪成功防线二：编号能解析、但 pak 里一条都对不上 → 报错。
        let absent = vec!["deadbeefdeadbeef".to_string()];
        assert!(
            export_run(&name, &absent, &dest.to_string_lossy().to_string(), &quiet).is_err(),
            "编号在 pak 里不存在必须报错"
        );
        std::fs::remove_dir_all(&dest).ok();

        // 拒绝导出只收走自己刚建的目录：客户端里本来就存在的空目录必须原样
        // 保留——只读纪律对空壳目录同样生效。
        let preexisting = root.join("tlbb_browse_preexisting_dir_test");
        std::fs::create_dir_all(&preexisting).expect("预置空目录");
        assert!(
            export_run(&name, &[], &preexisting.to_string_lossy().to_string(), &quiet).is_err(),
            "导出到客户端根内非 .scratch 必须报错"
        );
        assert!(
            preexisting.exists(),
            "被拒的导出不得删除客户端里已存在的目录"
        );
        std::fs::remove_dir_all(&preexisting).ok();
    }

    #[test]
    fn safe_join_rejects_dirty_segments() {
        let base = PathBuf::from(r"\\?\C:\dest");
        let ok = |s: &str| safe_join(&base, s).is_some();
        let no = |s: &str| safe_join(&base, s).is_none();
        assert!(ok("data/source/npc/a.tga"), "正常路径应放行");
        assert!(ok("data/file name (1).mesh"), "空格和括号是合法名字");
        assert!(no("a/../b"), "段中 .. 必须拒");
        assert!(no(".."), "整段 .. 必须拒");
        assert!(no(r"\abs\path"), "绝对路径切出来首段为空，必须拒");
        assert!(no("c:/windows/x"), "盘符冒号必须拒");
        assert!(no("data/CON"), "保留设备名必须拒");
        assert!(no("data/con.tga"), "保留名不分大小写、不管扩展名");
        assert!(no("data/NUL.txt"), "NUL 是设备名");
        assert!(no("data/a\u{0000}b"), "控制字符必须拒");
        assert!(no("data/a\u{001F}b"), "控制字符必须拒");
        assert!(no("data/a\u{007F}b"), "DEL 也是控制字符");
        assert!(no("data/trail."), "尾点落盘会被 Windows 剥掉，名字会对不上");
        // 无论怎么洗，结果都必须还落在 base 之内（没有一段能带出分隔符）。
        if let Some(p) = safe_join(&base, "data/./x.y") {
            assert!(p.starts_with(&base), "放行的路径必须仍在导出目录内");
        }
    }

    /// 造一条 junction（不需要管理员权限；符号链接 symlink_dir 要）。
    /// 造不出来就返回 false，让用例自己跳过——闸门要能验红，不能靠猜。
    #[cfg(windows)]
    fn make_junction(link: &Path, target: &Path) -> bool {
        std::process::Command::new("cmd")
            .args([
                "/C",
                "mklink",
                "/J",
                &link.to_string_lossy(),
                &target.to_string_lossy(),
            ])
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::null())
            .status()
            .map(|s| s.success())
            .unwrap_or(false)
    }

    #[test]
    #[cfg(windows)]
    fn write_guard_sees_through_junction_into_client_root() {
        // 假客户端根 + 假导出目录，全在临时目录里，不碰真客户端一眼。
        let base = std::env::temp_dir().join("tlbb_write_guard_test");
        std::fs::remove_dir_all(&base).ok();
        let fake_root = base.join("client");
        let fake_scratch = fake_root.join(".scratch");
        let protected = fake_root.join("protected");
        let dest = base.join("dest");
        for d in [&fake_root, &fake_scratch, &protected, &dest] {
            std::fs::create_dir_all(d).expect("预置临时目录");
        }
        let guard = WriteGuard::new(
            &normalize_abs(&dest.canonicalize().unwrap()),
            &normalize_abs(&fake_root.canonicalize().unwrap()),
            &normalize_abs(&fake_scratch.canonicalize().unwrap()),
        );

        // 正常路径照常放行。
        assert!(guard.check(&dest.join("data/x.mesh")).is_ok(), "导出目录内的正常路径必须放行");

        // dest/link → root/protected：跟着链接写就等于写客户端目录，必须拦。
        let link = dest.join("link");
        if !make_junction(&link, &protected) {
            eprintln!("跳过：本机造不出 junction");
            std::fs::remove_dir_all(&base).ok();
            return;
        }
        let thru = guard.check(&link.join("effect/x.mesh"));
        assert!(
            thru.is_err(),
            "junction 指进客户端根必须被拦，实际放行：{:?} 落在 {:?}",
            thru.as_ref().err(),
            thru.as_ref().ok(),
        );

        // 导出目录本身就在 .scratch 里（合法）时，链接指回根内非 .scratch 同样拦。
        let scratch_dest = fake_scratch.join("export");
        std::fs::create_dir_all(&scratch_dest).unwrap();
        let guard2 = WriteGuard::new(
            &normalize_abs(&scratch_dest.canonicalize().unwrap()),
            &normalize_abs(&fake_root.canonicalize().unwrap()),
            &normalize_abs(&fake_scratch.canonicalize().unwrap()),
        );
        let link2 = scratch_dest.join("back");
        if make_junction(&link2, &protected) {
            assert!(
                guard2.check(&link2.join("x.mesh")).is_err(),
                "从 .scratch 里用链接写回客户端根必须被拦"
            );
        }
        // .scratch 内正常路径仍放行（别把产物区一起拦死）。
        assert!(guard2.check(&scratch_dest.join("a/x.png")).is_ok());
        std::fs::remove_dir_all(&base).ok();
    }

    /// 动作文件的预览回包：出不了画面，但关键帧的账要报得出、不能播的原因要写明。
    /// 吃本机真数据（`.ani` 在 data*.pak 里）；找不到动作条目就跳过。
    #[test]
    fn preview_reports_ani_keys_and_says_why_it_cannot_play() {
        let list = browse_paks().expect("browse_paks");
        let mut found = None;
        for card in list.paks.iter().take(2) {
            let tree = browse_tree(card.name.clone()).expect("browse_tree");
            if let Some(e) = tree.entries.iter().find(|e| e.kind == "ani") {
                found = Some((card.name.clone(), e.hash.clone()));
                break;
            }
        }
        let Some((pak, hash)) = found else {
            eprintln!("跳过：这两只容器里没有 kind=ani 的条目");
            return;
        };
        let pv = browse_preview(pak, hash).expect("browse_preview");
        assert!(!pv.ok, "动作文件没有画面可出，ok 必须是 false");
        let joined = pv.info.join(" | ");
        assert!(joined.contains("骨骼"), "应报骨骼数：{joined}");
        assert!(joined.contains("关键帧"), "应报帧数：{joined}");
        assert!(joined.contains("会动的骨"), "应报哪几根在动：{joined}");
        assert!(joined.contains("还不能播放"), "必须说清为什么点不出动画：{joined}");
        assert!(joined.contains("蒙皮权重"), "原因要落到权重/骨链这一层：{joined}");
    }

    /// 全库通用性闸门：随机抽一批 `.ani` 真条目，要求绝大多数按这套布局解得开，
    /// 并且骨骼数不是恒等于 46（否则「布局认得对」可能只是撞对了这一副骨架）。
    /// 关键帧格式是今天新解的，只靠 4 份手挑样本作证太薄——这条就是补的那道闸。
    #[test]
    fn ani_keyframe_layout_holds_across_the_library() {
        use std::collections::BTreeMap;
        let list = browse_paks().expect("browse_paks");
        let (root, _) = roots();
        let mut counts: BTreeMap<usize, usize> = BTreeMap::new();
        let (mut parsed, mut failed) = (0usize, 0usize);
        let (mut quat_total, mut quat_ok) = (0usize, 0usize);
        let mut budget = 60usize;
        for card in list.paks.iter() {
            if budget == 0 {
                break;
            }
            let tree = match browse_tree(card.name.clone()) {
                Ok(t) => t,
                Err(_) => continue,
            };
            let pak = match open_pak(&root, &card.name) {
                Ok(p) => p,
                Err(_) => continue,
            };
            for e in tree.entries.iter().filter(|e| e.kind == "ani") {
                if budget == 0 {
                    break;
                }
                budget -= 1;
                let Ok(hex) = u64::from_str_radix(e.hash.trim_start_matches("0x"), 16) else {
                    continue;
                };
                let Some(rec) = pak.records().find(|r| r.hash == hex && r.stored > 0) else {
                    continue;
                };
                let bytes = match tlbb_core::payload::decode(&pak, &rec) {
                    Ok(d) => d.bytes,
                    Err(_) => {
                        failed += 1;
                        continue;
                    }
                };
                match tlbb_core::preview::parse_ani(&bytes) {
                    Some(a) => {
                        parsed += 1;
                        *counts.entry(a.bones).or_default() += 1;
                        // 解开了就必须自洽：轨道数 = 骨骼数，每条帧数齐。
                        assert_eq!(a.tracks.len(), a.bones);
                        assert!(a.tracks.iter().all(|t| t.rotations.len() == a.frames));
                        // 「布局对」的判据不能只是「按尺寸切得开」——切得开不代表
                        // 切出来的是四元数。这里数一遍单位长（全零算静止骨）。
                        for t in &a.tracks {
                            for q in &t.rotations {
                                quat_total += 1;
                                if tlbb_core::preview::anim::is_unit_quat(q) {
                                    quat_ok += 1;
                                }
                            }
                        }
                    }
                    None => failed += 1,
                }
            }
        }
        if parsed == 0 {
            eprintln!("跳过：本机没有可解的 .ani 条目");
            return;
        }
        let total = parsed + failed;
        assert!(
            parsed * 10 >= total * 9,
            "全库抽样 {total} 份只有 {parsed} 份按这套布局解开，布局口径不成立：{counts:?}",
        );
        assert!(counts.keys().len() > 1, "骨骼数只有一种（{counts:?}）——样本太单一，换不出结论");
        // 四元数占比：不到 99% 就说明某个字段切错位了（错位会立刻打散单位长）。
        assert!(
            quat_total > 0 && quat_ok * 100 >= quat_total * 99,
            "抽样的旋转字段只有 {quat_ok}/{quat_total} 是单位长，切分口径有问题"
        );
        eprintln!(
            "ani 抽样：{parsed}/{total} 解开，旋转 {quat_ok}/{quat_total} 单位长，骨骼数分布 {counts:?}"
        );
    }

    /// 特效文件的预览回包：材质链与发射器/混合模式要报得出来，
    /// 参数块必须说「字段名未解、只报数量」，不许把浮点个数当成参数值。
    #[test]
    fn preview_reports_effect_definition() {
        let list = browse_paks().expect("browse_paks");
        let mut found = None;
        for card in list.paks.iter().take(3) {
            let tree = match browse_tree(card.name.clone()) {
                Ok(t) => t,
                Err(_) => continue,
            };
            if let Some(e) = tree.entries.iter().find(|e| e.kind == "JBPU") {
                found = Some((card.name.clone(), e.hash.clone()));
                break;
            }
        }
        let Some((pak, hash)) = found else {
            eprintln!("跳过：这几只容器里没有 kind=JBPU 的条目");
            return;
        };
        let pv = browse_preview(pak, hash).expect("browse_preview");
        let joined = pv.info.join(" | ");
        assert!(joined.contains("特效"), "应报特效名：{joined}");
        assert!(joined.contains("驻留字符串"), "应报字符串条数：{joined}");
        assert!(joined.contains("参数块"), "应报参数块与「字段名未解」：{joined}");
        assert!(joined.contains("字段名未解"), "参数含义没解就必须这么说：{joined}");
    }

    /// 骨架节点名交叉核对：同一只怪的 `.mesh` 尾部节点名，必须盖住它 `.ani`
    /// 骨名表里的每一根骨。两边来自不同容器、不同解析路径，能对上就说明
    /// 「骨架在 mesh 尾部」不是猜的。父子关系仍未解，这里不验也不猜。
    #[test]
    fn mesh_tail_node_names_cover_the_ani_bones() {
        use tlbb_core::preview::{node_names, parse_ani};
        let (root, _db) = roots();
        let pak = match open_pak(&root, "data") {
            Ok(p) => p,
            Err(_) => {
                eprintln!("跳过：本机没有 data.pak");
                return;
            }
        };
        let bytes_of = |hash: u64| -> Option<Vec<u8>> {
            let rec = pak.records().find(|r| r.hash == hash && r.stored > 0)?;
            payload::decode(&pak, &rec).ok().map(|d| d.bytes)
        };
        // w1351_monster_xiyuqiezei_yifu_001.mesh / _behit01.ani
        let (mesh, ani) = match (bytes_of(0xbcd65050a62986b7), bytes_of(0x361180fe30a07e32)) {
            (Some(m), Some(a)) => (m, a),
            _ => {
                eprintln!("跳过：这只怪的 mesh 或动作不在这台机器的容器里");
                return;
            }
        };
        let names = node_names(&mesh);
        assert!(names.len() >= 40, "尾部节点太少（{} 个），不像骨架表", names.len());
        for want in ["origin", "top", "bip01", "bip01_pelvis", "bip01_head"] {
            assert!(names.iter().any(|n| n == want), "节点名里该有 {want}，实际前 12：{:?}", &names[..12.min(names.len())]);
        }
        let a = parse_ani(&ani).expect("动作应能解出");
        let missing: Vec<&String> = a
            .tracks
            .iter()
            .map(|t| &t.bone)
            .filter(|b| !b.is_empty() && !names.iter().any(|n| n == *b))
            .collect();
        assert!(
            missing.is_empty(),
            ".ani 里有 {} 根骨在 mesh 尾部找不到：{:?}",
            missing.len(),
            missing
        );
        eprintln!("骨架节点：mesh 尾部 {} 个，覆盖 .ani 的 {} 根骨", names.len(), a.bones);
    }

    /// 96 字节节点记录（名字 + 行主序 4×4 绑定矩阵）在两份真样本上逐字节成立。
    /// 一份只有 `bone001` 一根骨，一份只有 `origin` + `top`——最小骨架最容易看清结构。
    #[test]
    fn node_records_parse_on_minimal_skeletons() {
        use tlbb_core::preview::parse_nodes;
        let (root, _db) = roots();
        let pak = match open_pak(&root, "data") {
            Ok(p) => p,
            Err(_) => {
                eprintln!("跳过：本机没有 data.pak");
                return;
            }
        };
        let bytes_of = |hash: u64| -> Option<Vec<u8>> {
            let rec = pak.records().find(|r| r.hash == hash && r.stored > 0)?;
            payload::decode(&pak, &rec).ok().map(|d| d.bytes)
        };
        let cases = [
            (0x04c6552e00b465bdu64, vec!["bone001"]),
            (0x04349dc783c71228u64, vec!["origin", "top"]),
        ];
        for (hash, want) in cases {
            let Some(raw) = bytes_of(hash) else {
                eprintln!("跳过：{hash:016x} 不在这台机器的容器里");
                return;
            };
            let nodes = parse_nodes(&raw);
            let got: Vec<&str> = nodes.iter().map(|n| n.name.as_str()).collect();
            assert_eq!(got, want, "{hash:016x} 节点表读错");
            for n in &nodes {
                assert!(
                    n.bind[12].abs() < 1e-5 && n.bind[15] - 1.0 < 1e-3,
                    "{} 的矩阵末行不是 (0,0,0,1)：{:?}",
                    n.name,
                    &n.bind[12..]
                );
            }
        }
        // 大骨架那只怪：节点数不该少于动作文件的 45 根骨
        let yifu = bytes_of(0xbcd65050a62986b7).expect("yifu mesh 应在");
        let nodes = parse_nodes(&yifu);
        assert!(nodes.len() >= 45, "yifu 尾部只读出 {} 个节点，少于动作文件的 45 根骨", nodes.len());
        eprintln!("yifu 节点 {} 个，前 4：{:?}", nodes.len(), nodes.iter().take(4).map(|n| n.name.clone()).collect::<Vec<_>>());
    }

    #[test]
    fn preview_index_agrees_with_linear_scan() {        let list = browse_paks().expect("browse_paks");
        let name = list.paks[0].name.clone();
        let (root, _) = roots();
        let pak = open_pak(&root, &name).expect("打开 pak");
        let idx = pak_index(&name, &pak);
        // 按同一条规则（stored>0、同 hash 首个占位）手工线性建一份，逐键对照。
        let mut expect: HashMap<u64, Record> = HashMap::new();
        for rec in pak.records() {
            if rec.stored > 0 {
                expect.entry(rec.hash).or_insert(rec);
            }
        }
        assert_eq!(idx.len(), expect.len(), "索引条数应与线性扫描一致");
        for (h, rec) in &expect {
            let got = idx
                .get(h)
                .unwrap_or_else(|| panic!("索引缺条目 {:016x}", h));
            // Record 没有 PartialEq（core 冻结），按定位字段比对——同 hash 同
            // offset/stored 就是同一条记录。
            assert_eq!(got.offset, rec.offset, "hash {h:016x} 应指向同一条记录");
            assert_eq!(got.stored, rec.stored, "hash {h:016x} 应指向同一条记录");
            assert_eq!(got.original, rec.original, "hash {h:016x} 应指向同一条记录");
        }
        // 第二次取同一个 pak 必须命中缓存，返回同一份索引。
        let again = pak_index(&name, &pak);
        assert!(Arc::ptr_eq(&idx, &again), "第二次取应命中缓存返回同一份");
    }
}
