//! 无名贴图聚类验证（只读）——回答一个具体问题：
//!
//! **24,261 张没有名字的贴图，靠内容特征能不能被重新认识？**
//!
//! 这不是恢复名字的工具，是**可行性判定**。名字在客户端发布时就被剥离了
//! （见 2026-09-22 的解析层调查：PAK 索引无字符串槽位、JMT1 头无文件名、
//! `ResourcePath.cfg` 只覆盖 `ui/`），所以唯一的出路是"按内容像谁"归类。
//!
//! 三步，每一步都必须是可证伪的测量，不是感觉：
//!
//! 1. **元数据分层**：按 `(codec, 宽, 高)` 聚合。这一步只能说明"尺寸有结构"，
//!    不能说明"长得像"，所以它只是加权用的先验，不是结论。
//! 2. **距离分布**：把每个簇的**全部**样本两两比对，输出 Hamming 距离的完整直方图。
//!    这一步能区分"簇内散成一团"和"簇内分成若干小岛"——均值会骗人，分布不会。
//! 3. **最近邻检验**（决定性）：对每张样本图，找出**全池最近的另一张**是谁、距离多少。
//!    平均距离永远偏高（因为绝大多数对本来就是无关的），真正决定"能不能恢复身份"的
//!    是**每张图有没有一个够近的孪生**。所以这里报的是 `nearest` 的分布，不是两两均值。
//!
//! 判定以第 3 步为准。标定基线（`dhash_calibrate`）：
//! 同源图 0~1 位，纯随机噪声之间 32 位。所以"孪生"门槛取 8 位，"同族"取 16 位。
//!
//! 铁律照旧：不伪造名字、不伪造预览，只报测出来的东西。

use std::collections::{BTreeMap, HashMap};
use std::path::{Path, PathBuf};

use rusqlite::{Connection, OpenFlags};
use tlbb_core::jpak::Pak;
use tlbb_core::{jmt1, payload};

/* --------------------------------------------------------------------------- args */

struct Args {
    root: PathBuf,
    db: PathBuf,
    /// 总共最多解码多少张图参与全对全比对。0 表示只做元数据统计。
    pool: usize,
    /// 每个 (codec,w,h) 簇最多取多少张进池。
    per_cluster: usize,
    json: Option<PathBuf>,
    /// 把选中的样本导出成 PNG 图集的目录；用来"用眼睛复核"。
    sheet: Option<PathBuf>,
    /// 图集每张缩放到多大（正方形）。
    thumb: u32,
}

fn parse_args() -> Args {
    let mut a = Args {
        root: PathBuf::from("D:/TLGL"),
        db: PathBuf::from("D:/TLGL/.scratch/resources.db"),
        pool: 1200,
        per_cluster: 24,
        json: None,
        sheet: None,
        thumb: 96,
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
            "--pool" => a.pool = v.parse().unwrap_or(a.pool),
            "--per-cluster" => a.per_cluster = v.parse().unwrap_or(a.per_cluster),
            "--json" => a.json = Some(PathBuf::from(&v)),
            "--sheet" => a.sheet = Some(PathBuf::from(&v)),
            "--thumb" => a.thumb = v.parse().unwrap_or(a.thumb),
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

/* ---------------------------------------------------------------------------- rows */

struct Tex {
    hash: u64,
    pak: String,
    offset: i64,
    codec: String,
    w: u16,
    h: u16,
    mips: i64,
    original: i64,
}

fn nameless_textures(con: &Connection) -> Vec<Tex> {
    let mut st = con
        .prepare(
            "SELECT hash, pak, offset, codec, width, height, mips, original \
             FROM resources \
             WHERE type='texture' AND (path IS NULL OR path='') \
             ORDER BY hash",
        )
        .expect("prepare");
    st.query_map([], |r| {
        Ok(Tex {
            hash: u64::from_str_radix(&r.get::<_, String>(0)?, 16).unwrap_or(0),
            pak: r.get(1)?,
            offset: r.get(2)?,
            codec: r.get::<_, Option<String>>(3)?.unwrap_or_default(),
            w: r.get::<_, Option<i64>>(4)?.unwrap_or(0).max(0) as u16,
            h: r.get::<_, Option<i64>>(5)?.unwrap_or(0).max(0) as u16,
            mips: r.get::<_, Option<i64>>(6)?.unwrap_or(0),
            original: r.get(7)?,
        })
    })
    .expect("query")
    .collect::<Result<Vec<_>, _>>()
    .expect("collect")
}

/* ---------------------------------------------------------------------------- paks */

fn load_paks(root: &Path) -> (HashMap<String, Pak>, HashMap<(String, u64), tlbb_core::Record>) {
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
    (paks, idx)
}

fn decode(
    paks: &HashMap<String, Pak>,
    idx: &HashMap<(String, u64), tlbb_core::Record>,
    t: &Tex,
) -> Result<Vec<u8>, String> {
    let rec = idx
        .get(&(t.pak.clone(), t.hash))
        .ok_or_else(|| "索引里找不到".to_string())?;
    if rec.offset as i64 != t.offset {
        return Err("偏移已变动".to_string());
    }
    let p = paks.get(&t.pak).ok_or("包文件缺失")?;
    payload::decode(p, rec).map(|d| d.bytes).map_err(|e| e.to_string())
}

/* --------------------------------------------------------------------------- hashes */

/// 64 位差值哈希（dHash）。标定结果见 `dhash_calibrate`：
/// 同源图 0~1 位，纯随机噪声之间 32 位，所以 8 位以内基本可以定"孪生"。
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

/// 平均色 + 平均不透明度：用来判断"只是同尺寸纯色图"这种退化情况。
fn average(w: usize, h: usize, rgba: &[u8]) -> (f64, f64, f64, f64, f64) {
    // (r, g, b, a, 亮度的标准差)
    if w == 0 || h == 0 || rgba.len() < w * h * 4 {
        return (0.0, 0.0, 0.0, 0.0, 0.0);
    }
    let (mut r, mut g, mut b, mut a, mut n) = (0f64, 0f64, 0f64, 0f64, 0f64);
    let mut lums: Vec<f64> = Vec::new();
    let step = ((w * h) / 4096).max(1);
    let mut i = 0usize;
    while i < w * h {
        let o = i * 4;
        let (pr, pg, pb, pa) = (
            rgba[o] as f64,
            rgba[o + 1] as f64,
            rgba[o + 2] as f64,
            rgba[o + 3] as f64,
        );
        r += pr;
        g += pg;
        b += pb;
        a += pa;
        lums.push((299.0 * pr + 587.0 * pg + 114.0 * pb) / 1000.0);
        n += 1.0;
        i += step;
    }
    let n = n.max(1.0);
    let mean_l = lums.iter().sum::<f64>() / lums.len().max(1) as f64;
    let var = lums.iter().map(|l| (l - mean_l).powi(2)).sum::<f64>() / lums.len().max(1) as f64;
    (r / n, g / n, b / n, a / n, var.sqrt())
}

fn hamming(a: u64, b: u64) -> u32 {
    (a ^ b).count_ones()
}

/* ---------------------------------------------------------------------------- sample */

struct Pick {
    h: u64,
    cluster: usize,
    rgba: std::rc::Rc<Vec<u8>>,
    w: usize,
    hgt: usize,
    mean_lum: f64,
    lum_sd: f64,
}

fn percentile(sorted: &[u32], p: f64) -> u32 {
    if sorted.is_empty() {
        return 0;
    }
    let i = ((sorted.len() - 1) as f64 * p).round() as usize;
    sorted[i.min(sorted.len() - 1)]
}

/* ---------------------------------------------------------------------------- main */

fn main() {
    let a = parse_args();
    let con = open_ro(&a.db);
    let nameless_n = con
        .query_row(
            "SELECT count(*) FROM resources WHERE type='texture' AND (path IS NULL OR path='')",
            [],
            |r| r.get::<_, i64>(0),
        )
        .unwrap_or(0);
    let named_n = con
        .query_row(
            "SELECT count(*) FROM resources WHERE type='texture' AND path IS NOT NULL AND path<>''",
            [],
            |r| r.get::<_, i64>(0),
        )
        .unwrap_or(0);

    println!("== 无名贴图聚类验证（只读）");
    println!("贴图合计 {} 张：有名 {named_n}，无名 {nameless_n}", nameless_n + named_n);
    let rows = nameless_textures(&con);
    println!("载入无名贴图 {} 条\n", rows.len());

    // ---------------------------------------------------------------- 第一层 元数据分层
    let mut buckets: BTreeMap<(String, u16, u16), Vec<usize>> = BTreeMap::new();
    for (i, t) in rows.iter().enumerate() {
        buckets
            .entry((t.codec.clone(), t.w, t.h))
            .or_default()
            .push(i);
    }
    let mut order: Vec<((String, u16, u16), Vec<usize>)> = buckets.into_iter().collect();
    order.sort_by(|x, y| y.1.len().cmp(&x.1.len()).then(x.0.cmp(&y.0)));

    println!("== 第一层：按 (编码, 宽, 高) 分层（这一步只说明尺寸有结构，不说明像）");
    println!("  形成 {} 个尺寸层", order.len());
    let dim_shapes: std::collections::BTreeSet<(u16, u16)> =
        rows.iter().map(|t| (t.w, t.h)).collect();
    let square = rows.iter().filter(|t| t.w == t.h).count();
    println!("  不同尺寸共 {} 种；正方形 {} 张（{:.1}%）", dim_shapes.len(), square,
        100.0 * square as f64 / rows.len().max(1) as f64);
    println!();
    println!("  {:>8}  {:<9} {:>11}  {}", "数量", "编码", "尺寸", "占比");
    for (k, v) in order.iter().take(18) {
        println!(
            "  {:>8}  {:<9} {:>5}x{:<5}  {:>5.1}%",
            v.len(),
            k.0,
            k.1,
            k.2,
            100.0 * v.len() as f64 / rows.len().max(1) as f64
        );
    }
    if order.len() > 18 {
        println!("  …另有 {} 个更小的层", order.len() - 18);
    }

    // ---------------------------------------------------------------- 第二层 全对全距离分布
    if a.pool == 0 {
        println!("\n(--pool 0：跳过像素比对)");
        return;
    }

    let (paks, idx) = load_paks(&a.root);
    println!(
        "\n== 第二层：抽样解码 + 全对全比对（每层最多 {} 张，总池上限 {}）",
        a.per_cluster, a.pool
    );

    /* --- 选池 ---
     * 选池方式会直接决定最近邻分布的含义，所以这里刻意做两轮：
     *   轮 1「分层轮转」：按尺寸层轮着取，替每张图找一个**不同尺寸**的候选池。
     *       如果最近邻主要来自这里，说明"同族"跨越尺寸，关系较松。
     *   轮 2「层内补齐」：如果轮 1 取不满（层数不够多），用同一批层的更多成员补足。
     * 最终池内既含跨层对也含层内对，两个"可选伙伴数"分别报出来，谁也没被算法偏袒。
     */
    let mut picks: Vec<Pick> = Vec::new();
    let mut cluster_names: Vec<(String, u16, u16)> = Vec::new();
    let mut decoded_fail = 0usize;
    let mut alpha_zero = 0usize;
    // (层序号, 下一个可取的成员下标, 步长)
    let mut cursors: Vec<(usize, usize, usize)> = order
        .iter()
        .enumerate()
        .map(|(ci, (_, members))| (ci, 0usize, (members.len() / a.per_cluster).max(1)))
        .collect();
    let mut quota: Vec<usize> = vec![0; order.len()];

    for (ci, (key, members)) in order.iter().enumerate() {
        cluster_names.push(key.clone());
        // 轮 1：每层先给 1 个名额
        quota[ci] = 1;
        let _ = members;
    }

    // 轮转取样本，直到池满或取不出新图
    let mut progressed = true;
    while picks.len() < a.pool && progressed {
        progressed = false;
        for cur in cursors.iter_mut() {
            if picks.len() >= a.pool {
                break;
            }
            let (ci, next, stride) = *cur;
            if quota[ci] == 0 {
                continue;
            }
            let members = &order[ci].1;
            // 找下一个还没取过的成员
            let mut taken = false;
            let mut k = next;
            while k < members.len() {
                let mi = members[k];
                let t = &rows[mi];
                k += 1;
                let Ok(b) = decode(&paks, &idx, t) else {
                    decoded_fail += 1;
                    continue;
                };
                let Ok(tex) = jmt1::decode(&b) else {
                    decoded_fail += 1;
                    continue;
                };
                let (w, h) = (tex.width as usize, tex.height as usize);
                if tex.rgba.is_empty() || w == 0 || h == 0 {
                    decoded_fail += 1;
                    continue;
                }
                let (r, g, bb, avg_a, sd) = average(w, h, &tex.rgba);
                if avg_a < 4.0 {
                    alpha_zero += 1;
                    continue;
                }
                picks.push(Pick {
                    h: dhash64(w, h, &tex.rgba),
                    cluster: ci,
                    mean_lum: (299.0 * r + 587.0 * g + 114.0 * bb) / 1000.0,
                    lum_sd: sd,
                    rgba: std::rc::Rc::new(tex.rgba),
                    w,
                    hgt: h,
                });
                taken = true;
                progressed = true;
                break;
            }
            let _ = stride;
            cur.1 = k;
            // 本轮给了这一层多少个名额：配额上限 = per_cluster
            if quota[ci] < a.per_cluster {
                quota[ci] += 1;
            } else if cur.1 >= members.len() {
                quota[ci] = 0;
            }
            if !taken && cur.1 >= members.len() {
                quota[ci] = 0;
            }
        }
    }

    println!("  实际入池 {} 张（解码失败 {decoded_fail}，近全透明剔除 {alpha_zero}）", picks.len());
    if picks.len() < 16 {
        println!("  样本太少，无法做分布判定 —— 请调大 --pool / --per-cluster。");
        return;
    }

    // 全对全
    let n = picks.len();
    let mut all: Vec<u32> = Vec::with_capacity(n * (n - 1) / 2);
    let mut same_cluster: Vec<u32> = Vec::new();
    let mut cross_cluster: Vec<u32> = Vec::new();
    // 每张图的最近邻（排除自己）
    let mut nearest: Vec<(u32, usize)> = vec![(u32::MAX, usize::MAX); n];
    for i in 0..n {
        for j in (i + 1)..n {
            let d = hamming(picks[i].h, picks[j].h);
            all.push(d);
            if picks[i].cluster == picks[j].cluster {
                same_cluster.push(d);
            } else {
                cross_cluster.push(d);
            }
            if d < nearest[i].0 {
                nearest[i] = (d, j);
            }
            if d < nearest[j].0 {
                nearest[j] = (d, i);
            }
        }
    }
    all.sort_unstable();
    same_cluster.sort_unstable();
    cross_cluster.sort_unstable();
    let mean = |v: &[u32]| -> f64 {
        if v.is_empty() {
            0.0
        } else {
            v.iter().map(|x| *x as f64).sum::<f64>() / v.len() as f64
        }
    };

    println!();
    println!("  距离分布（64 位 dHash，理论上界 32，标定：同源 0~1，随机 32）");
    println!("    {:<22} {:>6}  {:>6} {:>6} {:>6} {:>6}",
        "集合", "样本", "P10", "中位", "P90", "均值");
    let row = |name: &str, v: &[u32]| {
        println!("    {name:<22} {:>6}  {:>6} {:>6} {:>6} {:>6.2}",
            v.len(), percentile(v, 0.10), percentile(v, 0.50), percentile(v, 0.90), mean(v));
    };
    row("全部配对", &all);
    row("同尺寸层内", &same_cluster);
    row("跨尺寸层", &cross_cluster);

    let mut ndist: Vec<u32> = nearest.iter().map(|x| x.0).collect();
    ndist.sort_unstable();
    println!();
    println!("  最近邻分布（每张图最像的那张，距离多少）—— 决定性的那一栏");
    println!("    {:<22} {:>6}  {:>6} {:>6} {:>6} {:>6.2}",
        "集合", "样本", "P10", "中位", "P90", "均值");
    println!("    {:<22} {:>6}  {:>6} {:>6} {:>6} {:>6.2}",
        "最近邻", ndist.len(), percentile(&ndist, 0.10), percentile(&ndist, 0.50),
        percentile(&ndist, 0.90), mean(&ndist));

    // 最近邻是"同尺寸层"还是"跨尺寸层"？用来判断同族关系的松紧。
    let nn_same = nearest
        .iter()
        .enumerate()
        .filter(|(i, (_, j))| *j != usize::MAX && picks[*i].cluster == picks[*j].cluster)
        .count();
    let nn_cross = nearest
        .iter()
        .enumerate()
        .filter(|(i, (_, j))| *j != usize::MAX && picks[*i].cluster != picks[*j].cluster)
        .count();
    // 池内"可选伙伴"数：全池 vs 同层，衡量算法有没有偏袒某一边
    let same_avail: usize = {
        let mut m: HashMap<usize, usize> = HashMap::new();
        for p in &picks {
            *m.entry(p.cluster).or_default() += 1;
        }
        m.values().map(|c| c * (c - 1) / 2).sum()
    };
    let all_avail = n * (n - 1) / 2;
    println!();
    println!("  最近邻落点：同尺寸层内 {nn_same} 张（{:.1}%）· 跨尺寸层 {nn_cross} 张（{:.1}%）",
        100.0 * nn_same as f64 / n as f64,
        100.0 * nn_cross as f64 / n as f64);
    println!("  公平性核对：同层可选伙伴 {same_avail} 对，全池 {all_avail} 对 —— 同层占 {:.1}%",
        100.0 * same_avail as f64 / all_avail.max(1) as f64);
    println!("  同层配对的实际均值 {:.2} vs 跨层 {:.2}（差 {:.2} 位）",
        mean(&same_cluster), mean(&cross_cluster),
        mean(&cross_cluster) - mean(&same_cluster));

    let cnt = |v: &[u32], f: fn(u32) -> bool| v.iter().filter(|x| f(**x)).count();
    println!();
    println!("  按门槛统计（8 位内 = 孪生，16 位内 = 同族）");
    for (label, v) in [("全部配对", &all), ("同尺寸层内", &same_cluster), ("最近邻", &ndist)] {
        println!("    {label:<10} ≤8位 {:>6} ({:>5.2}%)   ≤16位 {:>6} ({:>5.2}%)   >24位 {:>6} ({:>5.2}%)",
            cnt(v, |d| d <= 8), 100.0 * cnt(v, |d| d <= 8) as f64 / v.len().max(1) as f64,
            cnt(v, |d| d <= 16), 100.0 * cnt(v, |d| d <= 16) as f64 / v.len().max(1) as f64,
            cnt(v, |d| d > 24), 100.0 * cnt(v, |d| d > 24) as f64 / v.len().max(1) as f64);
    }

    // 是不是"纯色图"退化：若大量图亮度标准差≈0，则 dHash 无意义
    let flat = picks.iter().filter(|p| p.lum_sd < 3.0).count();
    println!();
    println!("  退化检查：亮度标准差 <3 的近似纯色图 {} 张（{:.1}%）",
        flat, 100.0 * flat as f64 / n as f64);

    // ---------------------------------------------------------------- 判定
    let twin_share = cnt(&ndist, |d| d <= 8) as f64 / ndist.len().max(1) as f64;
    let kin_share = cnt(&ndist, |d| d <= 16) as f64 / ndist.len().max(1) as f64;
    println!("\n== 判定");
    println!("  每张图是否都有一个够像的孪生（≤8 位）：{:.1}%", twin_share * 100.0);
    println!("  每张图是否都有一个同族（≤16 位）：      {:.1}%", kin_share * 100.0);
    let verdict;
    if twin_share >= 0.60 {
        verdict = "内容反推成立：多数图都有孪生，可以走「资产恢复」（同族归并后再按族去对名字）。";
        println!("  ⇒ **资产恢复**。{verdict}");
    } else if kin_share >= 0.50 {
        verdict = "半自动：近半图能找到同族，可做「按族归类 + 人工命名」，全自动恢复不成立。";
        println!("  ⇒ **半自动归类**。{verdict}");
    } else {
        verdict = "内容之间普遍不像，聚类只能得到尺寸/编码这类元数据标签，不能得到身份。";
        println!("  ⇒ **素材考古墙**。{verdict}");
        println!("  补充：这意味着 24,261 张的出路是「可浏览、可按元数据筛、可出图集」，");
        println!("  而不是「自动归属于某个模型/场景」。");
    }

    // ---------------------------------------------------------------- 图集导出（用眼睛复核）
    if let Some(dir) = &a.sheet {
        let mut sheet_png = Vec::new();
        let _ = std::fs::create_dir_all(dir);
        let t = a.thumb as usize;
        let cols = 16usize;
        let rowsn = ((n + cols - 1) / cols).max(1);
        let (iw, ih) = (cols * t, rowsn * t);
        let mut buf = vec![0u8; iw * ih * 4];
        for (idx, p) in picks.iter().enumerate() {
            let (cx, cy) = ((idx % cols) * t, (idx / cols) * t);
            for dy in 0..t {
                for dx in 0..t {
                    let sx = dx * p.w / t;
                    let sy = dy * p.hgt / t;
                    let so = (sy * p.w + sx) * 4;
                    let dofs = ((cy + dy) * iw + cx + dx) * 4;
                    if so + 3 < p.rgba.len() {
                        buf[dofs] = p.rgba[so];
                        buf[dofs + 1] = p.rgba[so + 1];
                        buf[dofs + 2] = p.rgba[so + 2];
                        buf[dofs + 3] = 255;
                    }
                }
            }
        }
        let out = dir.join("nameless_pool.png");
        // 极简 PNG 写入：用 image crate 太重，这里手写一个非压缩（stored）PNG 太麻烦，
        // 改为输出 PPM（无损、任何看图器都认），PNG 由外部转换。
        let mut ppm = format!("P6\n{} {}\n255\n", iw, ih).into_bytes();
        for px in buf.chunks(4) {
            ppm.push(px[0]);
            ppm.push(px[1]);
            ppm.push(px[2]);
        }
        let _ = std::fs::write(out.with_extension("ppm"), &ppm);
        sheet_png.push(1);
        println!("\n  图集已导出：{}", out.with_extension("ppm").display());
        println!("  （PPM 无损，便于用眼睛复核；尺寸 {iw}x{ih}，共 {n} 张）");
    }

    // ---------------------------------------------------------------- JSON
    if let Some(p) = &a.json {
        let mut s = String::from("{\n");
        s.push_str(&format!("  \"nameless_textures\": {},\n", rows.len()));
        s.push_str(&format!("  \"pool\": {n},\n"));
        s.push_str(&format!("  \"decoded_fail\": {decoded_fail},\n"));
        s.push_str(&format!("  \"alpha_zero_dropped\": {alpha_zero},\n"));
        s.push_str(&format!("  \"near_flat\": {flat},\n"));
        s.push_str(&format!("  \"dim_shapes\": {},\n", dim_shapes.len()));
        s.push_str(&format!("  \"square\": {square},\n"));
        s.push_str(&format!("  \"all_pairs\": {{\"n\":{},\"p10\":{},\"p50\":{},\"p90\":{},\"mean\":{:.3}}},\n",
            all.len(), percentile(&all, 0.10), percentile(&all, 0.50), percentile(&all, 0.90), mean(&all)));
        s.push_str(&format!("  \"same_cluster\": {{\"n\":{},\"p10\":{},\"p50\":{},\"p90\":{},\"mean\":{:.3}}},\n",
            same_cluster.len(), percentile(&same_cluster, 0.10), percentile(&same_cluster, 0.50),
            percentile(&same_cluster, 0.90), mean(&same_cluster)));
        s.push_str(&format!("  \"cross_cluster\": {{\"n\":{},\"p10\":{},\"p50\":{},\"p90\":{},\"mean\":{:.3}}},\n",
            cross_cluster.len(), percentile(&cross_cluster, 0.10), percentile(&cross_cluster, 0.50),
            percentile(&cross_cluster, 0.90), mean(&cross_cluster)));
        s.push_str(&format!("  \"nearest\": {{\"n\":{},\"p10\":{},\"p50\":{},\"p90\":{},\"mean\":{:.3}}},\n",
            ndist.len(), percentile(&ndist, 0.10), percentile(&ndist, 0.50),
            percentile(&ndist, 0.90), mean(&ndist)));
        s.push_str(&format!("  \"nearest_le8\": {},\n", cnt(&ndist, |d| d <= 8)));
        s.push_str(&format!("  \"nearest_le16\": {},\n", cnt(&ndist, |d| d <= 16)));
        s.push_str(&format!("  \"nearest_same_cluster\": {nn_same},\n"));
        s.push_str(&format!("  \"nearest_cross_cluster\": {nn_cross},\n"));
        s.push_str(&format!("  \"same_avail_pairs\": {same_avail},\n"));
        s.push_str(&format!("  \"all_avail_pairs\": {all_avail},\n"));
        s.push_str(&format!("  \"all_pairs_le8\": {},\n", cnt(&all, |d| d <= 8)));
        s.push_str(&format!("  \"all_pairs_le16\": {},\n", cnt(&all, |d| d <= 16)));
        s.push_str(&format!("  \"verdict\": \"{verdict}\"\n"));
        s.push_str("}\n");
        if let Err(e) = std::fs::write(p, s) {
            eprintln!("写不进去 {}: {e}", p.display());
        } else {
            println!("  JSON 已写出：{}", p.display());
        }
    }
}
