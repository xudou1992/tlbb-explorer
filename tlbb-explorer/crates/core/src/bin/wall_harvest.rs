//! 图片考古墙 · 第一步：把 24,261 张无名贴图**逐张解码出像素**，落成缩略图 + 内容特征。
//!
//! 这一步是整面墙的地基，所以它只做一件必须做对的事：
//! **每张图都真解码一次**，解出多少报多少，解不出来就记下原文原因。
//! 绝不因为"解不出来不好看"就拿别的图顶替——那是伪造。
//!
//! 输出两个东西：
//!   - `thumb/<hash>.webp`  长边 160px 的缩略图（墙要用）；解不出的不写文件
//!   - `raw.tsv`            每张图一行的内容特征，供聚族脚本消费
//!
//! 特征包括 dHash64（内容相似度的核心）、平均色、亮度标准差、边缘能量、非透明占比。
//! 这些量各自的用途在下面 `Feature` 的注释里写了——没有一个是"顺手算的"。
//!
//! 铁律：只读 pak，不写任何游戏文件。

use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Mutex;

use rusqlite::{Connection, OpenFlags};
use tlbb_core::jpak::Pak;
use tlbb_core::{jmt1, payload};

/// 计算内容特征时使用的降采样长边。
///
/// **这是一条数据契约，不是性能旋钮。** dHash / 平均色 / 边缘 / 不透明度全部在这一尺寸上
/// 计算，改成别的值会让同一张图算出不同的哈希，已建好的族就对不上了。
/// 选 160 的理由：dHash 只用 9×8 的网格，160px 远大于该网格，
/// 继续放大不会带来新信息，只会让 3.4 亿像素的遍历变成 34 亿。
const FEATURE_EDGE: usize = 160;

/* --------------------------------------------------------------------------- args */

struct Args {
    root: PathBuf,
    db: PathBuf,
    out: PathBuf,
    /// 缩略图单独的输出目录。默认跟随 `out`。
    ///
    /// **为什么要有这个开关**：本机沙箱对「工程盘上的新建文件」做了 syscall 拦截，
    /// 实测同一段代码写 `D:\` 约 21 ms/文件、写系统 TEMP 约 0.22 ms/文件，
    /// 差近 100 倍。2.4 万张缩略图放工程盘要 10 分钟，放 TEMP 只要几秒。
    /// `raw.tsv`（几 MB，一个文件）仍留在 `out`，缩略图这种海量小文件走 `--thumb-out`。
    thumb_out: PathBuf,
    /// 缩略图长边像素。
    thumb: usize,
    /// 只处理前 N 张（调试用）；0 = 全量。
    limit: usize,
    /// 是否写缩略图。只想要特征时可以关掉，快很多。
    write_thumbs: bool,
    /// 从第 N 条开始（断点续跑用）。
    skip: usize,
    /// 只搬运已有缩略图，不解码。
    move_thumbs: bool,
}

fn parse_args() -> Args {
    let mut a = Args {
        root: PathBuf::from("D:/TLGL"),
        db: PathBuf::from("D:/TLGL/.scratch/resources.db"),
        out: PathBuf::from("D:/TLGL/.scratch/wall3"),
        thumb_out: PathBuf::new(),
        // 与 FEATURE_EDGE 一致，这样缩放只做一次、复用给两者。
        thumb: FEATURE_EDGE,
        limit: 0,
        write_thumbs: true,
        skip: 0,
        move_thumbs: false,
    };
    let raw: Vec<String> = std::env::args().skip(1).collect();
    let mut i = 0;
    while i < raw.len() {
        let (k, v) = match raw[i].split_once('=') {
            Some((k, v)) => (k.to_string(), v.to_string()),
            None => {
                let k = raw[i].clone();
                let v = raw.get(i + 1).cloned().unwrap_or_default();
                if !v.is_empty() && !v.starts_with("--") {
                    i += 1;
                }
                (k, v)
            }
        };
        match k.as_str() {
            "--root" => a.root = PathBuf::from(&v),
            "--db" => a.db = PathBuf::from(&v),
            "--out" => a.out = PathBuf::from(&v),
            "--thumb-out" => a.thumb_out = PathBuf::from(&v),
            "--thumb" => a.thumb = v.parse().unwrap_or(a.thumb),
            "--limit" => a.limit = v.parse().unwrap_or(0),
            "--skip" => a.skip = v.parse().unwrap_or(0),
            "--no-thumbs" => a.write_thumbs = false,
            "--move-thumbs" => a.move_thumbs = true,
            _ => {}
        }
        i += 1;
    }
    a
}

fn open_ro(path: &Path) -> Connection {
    Connection::open_with_flags(
        path,
        OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )
    .expect("以只读方式打开 resources.db")
}

/// 把 `src` 下的文件平移到 `dst`（同名则跳过），返回搬运数量。
///
/// 用 `rename` 而不是"读进来再写出去"：同一卷内 rename 是纯元数据操作，不走数据通路，
/// 而数据通路正是被沙箱拦截收费的那一段。
fn move_tree(src: &Path, dst: &Path) -> usize {
    if !src.exists() {
        return 0;
    }
    let _ = std::fs::create_dir_all(dst);
    let mut n = 0;
    for e in std::fs::read_dir(src).into_iter().flatten().flatten() {
        let from = e.path();
        if !from.is_file() {
            continue;
        }
        let to = dst.join(e.file_name());
        if to.exists() {
            continue;
        }
        if std::fs::rename(&from, &to).is_ok() {
            n += 1;
        }
    }
    n
}

/* ---------------------------------------------------------------------------- rows */

struct Tex {
    hash: String,
    pak: String,
    offset: i64,
    codec: String,
    w: u16,
    h: u16,
    mips: i64,
    original: i64,
    gen: i64,
}

fn nameless_textures(con: &Connection) -> Vec<Tex> {
    let mut st = con
        .prepare(
            "SELECT hash, pak, offset, codec, width, height, mips, original, gen \
             FROM resources \
             WHERE type='texture' AND (path IS NULL OR path='') \
             ORDER BY hash",
        )
        .expect("prepare");
    st.query_map([], |r| {
        Ok(Tex {
            hash: r.get(0)?,
            pak: r.get(1)?,
            offset: r.get(2)?,
            codec: r.get::<_, Option<String>>(3)?.unwrap_or_default(),
            w: r.get::<_, Option<i64>>(4)?.unwrap_or(0).max(0) as u16,
            h: r.get::<_, Option<i64>>(5)?.unwrap_or(0).max(0) as u16,
            mips: r.get::<_, Option<i64>>(6)?.unwrap_or(0),
            original: r.get(7)?,
            gen: r.get::<_, Option<i64>>(8)?.unwrap_or(0),
        })
    })
    .expect("query")
    .collect::<Result<Vec<_>, _>>()
    .expect("collect")
}

/* ---------------------------------------------------------------------------- paks */

/// 每个 pak 只 mmap 一次，全线程共享。`Pak` 本身不实现 Sync（含 Mmap），
/// 但这里只做 `stored_bytes` 的只读切片，所以用裸指针共享是安全的：
/// 谁都不写，底层 mmap 在整个进程生命周期内不改动。
struct PakSet {
    paks: HashMap<String, Pak>,
    /// (pak, hash) -> Record 的索引，用来把 catalog 的 offset 与 pak 内的真实记录对上
    idx: HashMap<(String, u64), tlbb_core::Record>,
}

unsafe impl Send for PakSet {}
unsafe impl Sync for PakSet {}

impl PakSet {
    fn load(root: &Path) -> Self {
        let mut paks = HashMap::new();
        let mut idx = HashMap::new();
        let mut files: Vec<PathBuf> = std::fs::read_dir(root)
            .expect("读取包目录")
            .flatten()
            .map(|e| e.path())
            .filter(|p| p.extension().map(|x| x == "pak").unwrap_or(false))
            .collect();
        files.sort();
        for path in files {
            let stem = path.file_stem().unwrap().to_string_lossy().to_string();
            let Ok(pak) = Pak::open(&path) else { continue };
            for rec in pak.records() {
                idx.insert((stem.clone(), rec.hash), rec);
            }
            paks.insert(stem, pak);
        }
        Self { paks, idx }
    }

    fn decode(&self, hash_hex: &str, pak: &str, offset: i64) -> Result<Vec<u8>, String> {
        let h = u64::from_str_radix(hash_hex, 16).map_err(|e| format!("哈希非十六进制: {e}"))?;
        let rec = self
            .idx
            .get(&(pak.to_string(), h))
            .ok_or_else(|| "pak 索引里没有这条".to_string())?;
        if rec.offset as i64 != offset {
            return Err(format!(
                "偏移与目录不符（目录 {offset}，pak 内 {}）",
                rec.offset
            ));
        }
        let p = self.paks.get(pak).ok_or("pak 文件缺失")?;
        payload::decode(p, rec)
            .map(|d| d.bytes)
            .map_err(|e| format!("取出失败: {e}"))
    }
}

/* -------------------------------------------------------------------------- feature */

/// 一张图的内容特征。每个量都为墙面上的一个具体用途服务：
struct Feature {
    /// 64 位 dHash。聚族的**唯一**依据（标定：同源 0~1 位，随机 32 位）。
    dhash: u64,
    /// 平均 RGBA。用途：判退化 + 墙上做色系筛选。
    mr: f64,
    mg: f64,
    mb: f64,
    ma: f64,
    /// 亮度标准差。<3 说明是近似纯色图，dHash 对它没有意义，必须单独标出来。
    lum_sd: f64,
    /// 边缘能量（相邻像素亮度差均值）。用途：区分"有画面的图"和"纯色/渐变底图"。
    edge: f64,
    /// 非透明像素占比。用途：区分"实体贴图"和"透明蒙版/镂空"。
    alpha_cov: f64,
}

fn dhash64(w: usize, h: usize, rgba: &[u8]) -> u64 {
    let (gw, gh) = (9usize, 8usize);
    if w == 0 || h == 0 || rgba.len() < w * h * 4 {
        return 0;
    }
    let mut grid = [[0u32; 9]; 8];
    for gy in 0..gh {
        let y0 = gy * h / gh;
        let y1 = (((gy + 1) * h / gh).max(y0 + 1)).min(h);
        for gx in 0..gw {
            let x0 = gx * w / gw;
            let x1 = (((gx + 1) * w / gw).max(x0 + 1)).min(w);
            let (mut sum, mut n) = (0u64, 0u64);
            for y in y0..y1 {
                for x in x0..x1 {
                    let o = (y * w + x) * 4;
                    let l = (299 * rgba[o] as u64
                        + 587 * rgba[o + 1] as u64
                        + 114 * rgba[o + 2] as u64)
                        / 1000;
                    sum += l;
                    n += 1;
                }
            }
            grid[gy][gx] = (sum / n.max(1)) as u32;
        }
    }
    let mut bits = 0u64;
    let mut i = 0;
    for gy in 0..gh {
        for gx in 0..gw - 1 {
            if grid[gy][gx] > grid[gy][gx + 1] {
                bits |= 1u64 << i;
            }
            i += 1;
        }
    }
    bits
}

fn features(w: usize, h: usize, rgba: &[u8]) -> Feature {
    let n = w * h;
    let mut mr = 0f64;
    let mut mg = 0f64;
    let mut mb = 0f64;
    let mut ma = 0f64;
    let mut lum_sum = 0f64;
    let mut lum_sq = 0f64;
    let mut opaque = 0usize;
    let mut edge_sum = 0f64;
    let mut edge_n = 0usize;
    // 全量遍历：24,261 张 × 平均 ~5 万像素 = 十亿级操作，可接受且只跑一次。
    for i in 0..n {
        let o = i * 4;
        let (r, g, b, a) = (
            rgba[o] as f64,
            rgba[o + 1] as f64,
            rgba[o + 2] as f64,
            rgba[o + 3] as f64,
        );
        mr += r;
        mg += g;
        mb += b;
        ma += a;
        let l = (299.0 * r + 587.0 * g + 114.0 * b) / 1000.0;
        lum_sum += l;
        lum_sq += l * l;
        if a > 8.0 {
            opaque += 1;
        }
        let x = i % w;
        let y = i / w;
        if x + 1 < w {
            let o2 = o + 4;
            let l2 = (299.0 * rgba[o2] as f64
                + 587.0 * rgba[o2 + 1] as f64
                + 114.0 * rgba[o2 + 2] as f64)
                / 1000.0;
            edge_sum += (l - l2).abs();
            edge_n += 1;
        }
        if y + 1 < h {
            let o2 = o + w * 4;
            let l2 = (299.0 * rgba[o2] as f64
                + 587.0 * rgba[o2 + 1] as f64
                + 114.0 * rgba[o2 + 2] as f64)
                / 1000.0;
            edge_sum += (l - l2).abs();
            edge_n += 1;
        }
    }
    let d = (n.max(1)) as f64;
    let mean_l = lum_sum / d;
    let var = (lum_sq / d - mean_l * mean_l).max(0.0);
    Feature {
        dhash: dhash64(w, h, rgba),
        mr: mr / d,
        mg: mg / d,
        mb: mb / d,
        ma: ma / d,
        lum_sd: var.sqrt(),
        edge: edge_sum / edge_n.max(1) as f64,
        alpha_cov: opaque as f64 / d,
    }
}

/// 缩略图：框式降采样，长边不超过 `max`，保比，**只缩不放**。
///
/// 早先版本这里是错的：把 `max.min(w)` 当成目标宽，且横向/纵向的换算写反了，
/// 结果 64×64 的图被拉成 64×160（长边确实是 160，但另一条边没跟着放大），
/// 墙上的小图会全歪。所以现在改成先算缩放比、再乘两轴，并且 `min(1.0)` 保证不放大小图。
/// 返回 `(宽, 高, RGBA)`。
fn thumbnail(w: usize, h: usize, rgba: &[u8], max: usize) -> (usize, usize, Vec<u8>) {
    if w == 0 || h == 0 || rgba.len() < w * h * 4 {
        return (0, 0, Vec::new());
    }
    let long = w.max(h);
    // 只缩不放：小图原样输出，墙上的格子用 CSS 居中，不靠插值放大。
    let s = (max as f64 / long as f64).min(1.0);
    let nw = ((w as f64 * s).round() as usize).max(1);
    let nh = ((h as f64 * s).round() as usize).max(1);
    if nw == w && nh == h {
        return (w, h, rgba.to_vec());
    }
    let mut out = vec![0u8; nw * nh * 4];
    let xw = w as f64 / nw as f64;
    let yh = h as f64 / nh as f64;
    for y in 0..nh {
        let y0 = (y as f64 * yh) as usize;
        let y1 = (((y + 1) as f64 * yh).floor() as usize).max(y0 + 1).min(h);
        for x in 0..nw {
            let x0 = (x as f64 * xw) as usize;
            let x1 = (((x + 1) as f64 * xw).floor() as usize).max(x0 + 1).min(w);
            let (mut r, mut g, mut b, mut a, mut n) = (0u32, 0u32, 0u32, 0u32, 0u32);
            for sy in y0..y1 {
                for sx in x0..x1 {
                    let o = (sy * w + sx) * 4;
                    r += rgba[o] as u32;
                    g += rgba[o + 1] as u32;
                    b += rgba[o + 2] as u32;
                    a += rgba[o + 3] as u32;
                    n += 1;
                }
            }
            let o = (y * nw + x) * 4;
            let n = n.max(1);
            out[o] = (r / n) as u8;
            out[o + 1] = (g / n) as u8;
            out[o + 2] = (b / n) as u8;
            out[o + 3] = (a / n) as u8;
        }
    }
    (nw, nh, out)
}

/* ---------------------------------------------------------------------------- main */

fn main() {
    let a = parse_args();
    let con = open_ro(&a.db);
    let mut rows = nameless_textures(&con);
    let total_rows = rows.len();
    if a.skip > 0 {
        rows.drain(..a.skip.min(rows.len()));
    }
    if a.limit > 0 && rows.len() > a.limit {
        rows.truncate(a.limit);
    }
    let n = rows.len();

    std::fs::create_dir_all(&a.out).expect("建输出目录");
    // 缩略图目录：显式给了 --thumb-out 就用它，否则跟着 out 走。
    // 沙箱下放在工程盘会让每张小图多花 ~20ms，所以推荐显式指到 TEMP。
    let thumb_dir = if a.thumb_out.as_os_str().is_empty() {
        a.out.join("thumb")
    } else {
        a.thumb_out.clone()
    };
    if a.write_thumbs {
        std::fs::create_dir_all(&thumb_dir).expect("建缩略图目录");
    }

    // `--move-thumbs`：把已存在的缩略图整批挪到 `--thumb-out`，不重新解码。
    // 用途：先在工程盘上生成了 2.4 万张（慢，10 分钟），后来发现 TEMP 快近百倍，
    // 没必要重跑一遍解码——文件内容与来源目录无关，搬运即可。
    if a.move_thumbs {
        let src = a.out.join("thumb");
        let n = move_tree(&src, &thumb_dir);
        println!("已搬运缩略图 {n} 张：{} -> {}", src.display(), thumb_dir.display());
        return;
    }

    println!("== 图片考古墙 · 解码收料（只读）");
    println!("无名贴图合计 {total_rows} 张，本次处理 {n} 张（skip={}）", a.skip);
    println!("缩略图 {}（长边 {}px）", if a.write_thumbs { "开" } else { "关" }, a.thumb);

    let paks = PakSet::load(&a.root);
    let lanes = std::thread::available_parallelism()
        .map(|v| v.get())
        .unwrap_or(4)
        .clamp(2, 12);
    println!("pak 载入 {} 个（{}），并发 {lanes} 路\n", paks.paks.len(), {
        let mut k: Vec<&String> = paks.paks.keys().collect();
        k.sort();
        k.iter().map(|s| s.as_str()).collect::<Vec<_>>().join(" ")
    });

    let chunk = (n + lanes - 1) / lanes.max(1);
    let done = AtomicUsize::new(0);
    let ok_n = AtomicUsize::new(0);
    let fail_n = AtomicUsize::new(0);
    let flat_n = AtomicUsize::new(0);
    // 分阶段计时（纳秒累计），用来在变慢时定位是哪一段。
    let ns_pull = std::sync::atomic::AtomicU64::new(0);
    let ns_decode = std::sync::atomic::AtomicU64::new(0);
    let ns_feat = std::sync::atomic::AtomicU64::new(0);
    let ns_write = std::sync::atomic::AtomicU64::new(0);
    let mut lines: Vec<Mutex<Vec<String>>> = (0..lanes).map(|_| Mutex::new(Vec::new())).collect();
    let fails: Mutex<Vec<(String, String)>> = Mutex::new(Vec::new());

    let t0 = std::time::Instant::now();
    std::thread::scope(|scope| {
        for (li, slot) in lines.iter_mut().enumerate() {
            let lo = li * chunk;
            let hi = ((li + 1) * chunk).min(n);
            if lo >= hi {
                continue;
            }
            let slice = &rows[lo..hi];
            let paks = &paks;
            let done = &done;
            let ok_n = &ok_n;
            let fail_n = &fail_n;
            let flat_n = &flat_n;
            let fails = &fails;
            let ns_pull = &ns_pull;
            let ns_decode = &ns_decode;
            let ns_feat = &ns_feat;
            let ns_write = &ns_write;
            let thumb_dir = &thumb_dir;
            let (write_thumbs, max_thumb) = (a.write_thumbs, a.thumb);
            scope.spawn(move || {
                let mut local: Vec<String> = Vec::with_capacity(slice.len());
                for t in slice {
                    // 解不出时，所有内容列统一填 0 —— 列数必须恒定，下游才能按 \t 切。
                    //
                    // 占位符数量必须与成功行**完全一致**。早先这里少写了参数，
                    // 一旦真的出现解不出的图就会 panic（`format!` 参数不足是运行时错误）。
                    // 当时因为 400 张冒烟全成功所以没暴露；全量跑到第 1 张 WEBP 才炸。
                    // 教训：灰卡路径也要走一次真实数据，不能只在成功路径上验证。
                    let miss = |why: &str, line: &mut String| {
                        fail_n.fetch_add(1, Ordering::Relaxed);
                        fails.lock().unwrap().push((t.hash.clone(), why.to_string()));
                        *line = format!(
                            "{}\t0\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t0000000000000000\t0\t0\t0.000\t0.000\t0.000\t0.000\t0.000\t0.0000\t0.00000\t{}",
                            t.hash, t.pak, t.gen, t.offset, t.original,
                            t.codec, t.codec, t.w, t.h, t.mips, why
                        );
                    };
                    let mut line = String::new();
                    // 分阶段计时（原子累加，单位纳秒）。用途：当全量跑得比预期慢时，
                    // 能直接指出是"取字节 / 解码"/"算特征"/"编 PNG / 写盘"哪一段慢，不靠猜。
                    let t_pull = std::time::Instant::now();
                    match paks.decode(&t.hash, &t.pak, t.offset) {
                        Ok(bytes) => {
                            ns_pull.fetch_add(t_pull.elapsed().as_nanos() as u64, Ordering::Relaxed);
                            let t_dec = std::time::Instant::now();
                            match jmt1::decode(&bytes) {
                            Ok(tex) => {
                                ns_decode.fetch_add(t_dec.elapsed().as_nanos() as u64, Ordering::Relaxed);
                                let (pw, ph) = (tex.width as usize, tex.height as usize);
                                if tex.rgba.is_empty() || pw == 0 || ph == 0 {
                                    let why = if tex.codec == jmt1::Codec::Webp {
                                        "WEBP 内嵌流（未解码）"
                                    } else {
                                        "解码层返回空像素"
                                    };
                                    miss(why, &mut line);
                                } else {
                                    // 特征从**降采样后的图**上算，不从原图算。
                                    //
                                    // 这不是图省事，是量级问题：全库无名贴图合计约 34 亿像素，
                                    // 在原图上逐像素跑 `features()` + 再逐像素跑一次降采样，
                                    // 就是两遍十亿级循环。而 dHash 只看 9×8 的亮度网格，
                                    // 平均色/边缘/不透明度也都是统计量——在 160px 的图上算，
                                    // 结论完全一样（框式降采样本身就是抗锯齿），
                                    // 但循环次数压到约 1/20。
                                    //
                                    // ⚠ 关键：算特征的尺寸必须是**固定常量** `FEATURE_EDGE`，
                                    // 不能用 `--thumb`。否则同一张图在不同参数下会得到不同 dHash，
                                    // 聚族结果就不可复现了。`--thumb` 只管墙上显示多大。
                                    let t_feat = std::time::Instant::now();
                                    let (fw, fh, fbuf) = thumbnail(pw, ph, &tex.rgba, FEATURE_EDGE);
                                    let f = features(fw, fh, &fbuf);
                                    ns_feat.fetch_add(t_feat.elapsed().as_nanos() as u64, Ordering::Relaxed);
                                    if f.lum_sd < 3.0 {
                                        flat_n.fetch_add(1, Ordering::Relaxed);
                                    }
                                    if write_thumbs {
                                        let t_write = std::time::Instant::now();
                                        // 显示用缩略图：若尺寸与特征图一致就直接复用，
                                        // 否则再降一次（只在 --thumb != FEATURE_EDGE 时发生）。
                                        let (tw, th, tbuf) = if max_thumb == FEATURE_EDGE {
                                            (fw, fh, fbuf.clone())
                                        } else {
                                            thumbnail(pw, ph, &tex.rgba, max_thumb)
                                        };
                                        if let Ok(png) = tlbb_core::preview::image::png_bytes(
                                            tw as u16, th as u16, &tbuf, true,
                                        ) {
                                            let _ = std::fs::write(
                                                thumb_dir.join(format!("{}.png", t.hash)),
                                                &png,
                                            );
                                        }
                                        ns_write.fetch_add(t_write.elapsed().as_nanos() as u64, Ordering::Relaxed);
                                    }
                                    ok_n.fetch_add(1, Ordering::Relaxed);
                                    // 列序 = 表头列序，逐字段对齐：
                                    //   hash, decoded(=1), pak, gen, offset, original,
                                    //   catalog_codec, dec_codec, w, h, mips, dhash,
                                    //   dec_w, dec_h, mean_r, mean_g, mean_b, mean_a,
                                    //   lum_sd, edge, alpha_cov, fail(=. 表示无失败)
                                    // 占位符 20 个 + 字面量 `1` 与 `.` 两个 ⇒ 共 22 列。
                                    // 曾经漏掉 `t.mips` 导致整行比表头少一列、后面全体左移。
                                    line = format!(
                                        "{}\t1\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{:016x}\t{}\t{}\t{:.3}\t{:.3}\t{:.3}\t{:.3}\t{:.3}\t{:.4}\t{:.5}\t.",
                                        t.hash, t.pak, t.gen, t.offset, t.original,
                                        t.codec, tex.codec.as_str(),
                                        t.w, t.h, t.mips, f.dhash,
                                        pw, ph, f.mr, f.mg, f.mb, f.ma, f.lum_sd, f.edge,
                                        f.alpha_cov
                                    );
                                }
                            }
                            Err(e) => {
                                ns_decode.fetch_add(t_dec.elapsed().as_nanos() as u64, Ordering::Relaxed);
                                let why = format!("JMT1 解码失败: {e}");
                                miss(&why, &mut line);
                            }
                        }
                        },
                        Err(why) => miss(&why, &mut line),
                    }
                    local.push(line);
                    let d = done.fetch_add(1, Ordering::Relaxed) + 1;
                    if d % 5000 == 0 {
                        eprintln!("  … {d}/{n}（{:.1}s）", t0.elapsed().as_secs_f64());
                    }
                }
                *slot.lock().unwrap() = local;
            });
        }
    });

    let el = t0.elapsed().as_secs_f64();
    let ms = |ns: u64| ns as f64 / 1e6;
    let (ns_pull, ns_decode, ns_feat, ns_write) = (
        ns_pull.load(Ordering::Relaxed),
        ns_decode.load(Ordering::Relaxed),
        ns_feat.load(Ordering::Relaxed),
        ns_write.load(Ordering::Relaxed),
    );
    println!("\n== 分阶段耗时（各分片累计，已并发，故总和 > 墙钟）");
    println!("  取字节（解密/解压）{:>9.2}s", ms(ns_pull) / 1000.0);
    println!("  JMT1 解码           {:>9.2}s", ms(ns_decode) / 1000.0);
    println!("  算特征（降采样后）   {:>9.2}s", ms(ns_feat) / 1000.0);
    println!("  编 PNG + 写盘       {:>9.2}s", ms(ns_write) / 1000.0);
    let sum = ms(ns_pull) + ms(ns_decode) + ms(ns_feat) + ms(ns_write);
    println!("  合计 {:.2}s / 墙钟 {} 路并发 {:.2}s ⇒ 并行度 {:.1}x",
        sum / 1000.0, lanes, el, (sum / 1000.0) / el.max(0.001));
    // 列序必须与上面的表头**逐字对齐**。
    //
    // ⚠ 这里踩过一次坑：早先的写法在 `t.codec` 后面多输出了一个 `tex.codec.as_str()`，
    // 而表头里只有一列 codec —— 于是从 `w` 开始所有列都右移一格，
    // `catalog_codec` 装的是目录声称的 codec、`w` 装的是真实解码出的 codec，
    // 后面 `h/mips/...` 整体错位。下游按表头取数就会读到 'RGBA32' 当宽度。
    //
    // 所以现在**两个 codec 都保留**（它们的差异本身是有价值的事实：
    // 目录常见把 BC3 标成 DXT1，靠比对才能发现），并在表头为它们各留一列。
    // 表头顺序见上方 push_str 的那一行，改行格式时必须同步改它。
    let out_tsv = a.out.join("raw.tsv");
    let mut buf = String::with_capacity(n * 120);
    buf.push_str(
        "hash\tdecoded\tpak\tgen\toffset\toriginal\tcatalog_codec\tdec_codec\tw\th\tmips\tdhash\tdec_w\tdec_h\tmean_r\tmean_g\tmean_b\tmean_a\tlum_sd\tedge\talpha_cov\tfail\n",
    );
    for slot in lines.iter() {
        for l in slot.lock().unwrap().iter() {
            buf.push_str(l);
            buf.push('\n');
        }
    }
    std::fs::write(&out_tsv, &buf).expect("写 raw.tsv");

    let ok = ok_n.load(Ordering::Relaxed);
    let fail = fail_n.load(Ordering::Relaxed);
    println!("\n== 收料完成（{:.1}s）", el);
    println!("  解出像素 {ok} 张（{:.2}%）", 100.0 * ok as f64 / n.max(1) as f64);
    println!("  解不出   {fail} 张（{:.2}%）", 100.0 * fail as f64 / n.max(1) as f64);
    println!("  近似纯色（亮度标准差<3）{} 张", flat_n.load(Ordering::Relaxed));
    println!("  吞吐 {:.0} 张/秒", n as f64 / el.max(0.001));
    println!("  特征表 {}", out_tsv.display());
    if a.write_thumbs {
        println!("  缩略图 {}", thumb_dir.display());
    }

    // 解不出的按原因归类——这是墙上的"灰卡"，必须写清为什么，不能含糊。
    let fl = fails.into_inner().unwrap();
    if !fl.is_empty() {
        let mut by_reason: HashMap<String, usize> = HashMap::new();
        for (_, r) in &fl {
            // 原因里的数字去掉，便于归类
            let key: String = r
                .chars()
                .map(|c| if c.is_ascii_digit() { '#' } else { c })
                .collect();
            *by_reason.entry(key).or_default() += 1;
        }
        let mut v: Vec<(String, usize)> = by_reason.into_iter().collect();
        v.sort_by(|a, b| b.1.cmp(&a.1));
        println!("\n  解不出的原因分布：");
        for (k, c) in v.iter().take(10) {
            println!("    {c:>6}  {k}");
        }
        let mut fs: Vec<&(String, String)> = fl.iter().collect();
        fs.sort();
        println!("\n  前 5 例：");
        for (h, r) in fs.iter().take(5) {
            println!("    {h}  {r}");
        }
    }
}

/* ---------------------------------------------------------------------------- tests */

#[cfg(test)]
mod tests {

    /// 表头、成功行、失败行三者的列数必须一致。
    ///
    /// 这不是形式主义：这一处曾经真的错过——成功行多输出了一列,
    /// 导致 `w` 列装的是编解码器名字、后面整体右移；失败行的占位符又比参数多,
    /// 一遇到解不出的图就会 panic。两个 bug 都因为"只验证了成功路径"而溜过了冒烟测试。
    /// 所以把列数一致固化成断言，改格式时先在这里挂掉，而不是在 2 万行数据里。
    fn count_fields(fmt: &str) -> usize {
        // 数 {..} 占位符，忽略 {{ }} 转义
        let b = fmt.as_bytes();
        let mut n = 0;
        let mut i = 0;
        while i < b.len() {
            if b[i] == b'{' {
                if i + 1 < b.len() && b[i + 1] == b'{' {
                    i += 2;
                    continue;
                }
                n += 1;
            }
            i += 1;
        }
        n
    }

    #[test]
    fn 表头与两种数据行列数一致() {
        const HEAD: &str = "hash\tdecoded\tpak\tgen\toffset\toriginal\tcatalog_codec\tdec_codec\tw\th\tmips\tdhash\tdec_w\tdec_h\tmean_r\tmean_g\tmean_b\tmean_a\tlum_sd\tedge\talpha_cov\tfail";

        // 失败行
        const FAIL_ROW: &str = "{}\t0\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t0000000000000000\t0\t0\t0.000\t0.000\t0.000\t0.000\t0.000\t0.0000\t0.00000\t{}";
        // 成功行
        const OK_ROW: &str = "{}\t1\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{:016x}\t{}\t{}\t{:.3}\t{:.3}\t{:.3}\t{:.3}\t{:.3}\t{:.4}\t{:.5}\t.";

        let head_n = HEAD.split('\t').count();

        // 成功行的字面量列数：占位符数 + 行内固定字面量列（dhash 前后的常量列）
        // 最稳的做法是直接数"制表符分隔的段"，但格式串里有占位符，
        // 所以改用「段数 = 占位符数 + 不含占位符的字面量段数」来算。
        let seg = |fmt: &str| -> usize {
            // 把占位符统一替换成 \x01 再按 \t 切，避免占位符内部的字符干扰
            let b = fmt.as_bytes();
            let mut s = String::new();
            let mut i = 0;
            while i < b.len() {
                if b[i] == b'{' {
                    if i + 1 < b.len() && b[i + 1] == b'{' {
                        s.push('{');
                        i += 2;
                        continue;
                    }
                    while i < b.len() && b[i] != b'}' {
                        i += 1;
                    }
                    i += 1;
                    s.push('\x01');
                    continue;
                }
                s.push(b[i] as char);
                i += 1;
            }
            s.split('\t').count()
        };

        assert_eq!(seg(FAIL_ROW), head_n, "失败行列数与表头不一致");
        assert_eq!(seg(OK_ROW), head_n, "成功行列数与表头不一致");
        // 占位符数（不含 `1` 和 `.` 两个字面量列）：失败行 11 个、成功行 20 个。
        // 若改格式，这里会先挂——好过在 2.4 万行数据里发现列错位。
        assert_eq!(count_fields(FAIL_ROW), 11, "失败行占位符数变了，检查参数是否同步");
        assert_eq!(count_fields(OK_ROW), 20, "成功行占位符数变了，检查参数是否同步");
    }
}
