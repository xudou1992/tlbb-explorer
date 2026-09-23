//! The current baseline of the catalog, stated as facts rather than remembered numbers.
//!
//! The catalog is rebuilt by another pipeline, so any count written down in a document goes
//! stale the moment a pak is re-scanned. This binary re-derives them from `resources.db` and
//! prints a machine-readable document, so a number in a note and a number in the workbench
//! can always be traced back to one run.
//!
//! Two rules it inherits from the rest of the project:
//!
//! * **Every fact comes through `Catalog`.** Nothing here writes its own SQL for a question
//!   the catalog already answers — the point of this tool is to *report* the brain, not to
//!   become a second one.
//! * **"Has an image" is spelled the way the workbench spells it**: texture-typed references
//!   first, then a texture sharing the directory. An asset whose only "image" is a name that
//!   never resolved counts as having none, because that is what a person would see.
//!
//! One rule it must *not* pretend to inherit: **grades here cover a different axis than the
//! workbench's.** This tool never opens a container, so it cannot know whether a body file
//! decoded; it declares that axis unmeasured (`grade_coverage.decode_unmeasured`) and grades
//! on composition and references alone. It previously substituted `!image_candidates.is_empty()`
//! for the decode flag and reported 12,134 grade D against the workbench's 0. If you need the
//! decode axis, run the workbench.
//!
//! Usage: `catalog_baseline [--db FILE] [--json OUT]`

use std::collections::BTreeMap;
use std::path::PathBuf;

use serde::Serialize;
use tlbb_core::catalog::{labels, Catalog, Group, RelationCensus, Totals};

/* ------------------------------------------------------------------------ document */

#[derive(Serialize)]
struct Count {
    key: String,
    label: String,
    n: usize,
}

#[derive(Serialize)]
struct Baseline {
    catalog: String,
    catalog_bytes: u64,
    tables: Vec<Count>,
    totals: Totals,
    kinds: Vec<Count>,
    scenarios: Vec<Count>,
    grades: Vec<Count>,
    grade_coverage: GradeCoverage,
    image_sources: Vec<Count>,
    relations: RelationCensus,
    named: Named,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    notes: Vec<String>,
}

/// Groups with no stem at all — the population a nameless wall has to serve.
#[derive(Serialize)]
struct Named {
    with_stem: usize,
    nameless: usize,
    /// Nameless *and* imageless: the group exists but nothing can be shown for it at all.
    /// This is the floor of the nameless wall, not its size — a nameless group that does
    /// have pixels is still unattributable, which is the harder half of the problem.
    nameless_without_image: usize,
}

/// How much of the grade rested on a measurable axis.
///
/// `grades` alone is not enough to compare this run against the workbench: the two count
/// over different populations unless the decode axis is declared. This makes that
/// explicit so a drifting number is visible in the document instead of only in a diff.
#[derive(Serialize)]
struct GradeCoverage {
    /// Groups graded on composition and references only, with the body-decode axis
    /// unmeasured. Always the whole catalog for this tool; a decoder-backed run would
    /// report 0 here.
    decode_unmeasured: usize,
}

/* ---------------------------------------------------------------------------- args */

struct Args {
    db: PathBuf,
    json: Option<PathBuf>,
    root: PathBuf,
}

fn parse_args(raw: &[String]) -> Args {
    let mut a = Args {
        db: PathBuf::from("D:/TLGL/.scratch/resources.db"),
        json: None,
        root: PathBuf::from("D:/TLGL"),
    };
    let mut i = 0;
    while i < raw.len() {
        match raw[i].as_str() {
            "--db" if i + 1 < raw.len() => {
                i += 1;
                a.db = PathBuf::from(&raw[i]);
            }
            "--json" if i + 1 < raw.len() => {
                i += 1;
                a.json = Some(PathBuf::from(&raw[i]));
            }
            "--root" if i + 1 < raw.len() => {
                i += 1;
                a.root = PathBuf::from(&raw[i]);
            }
            _ => {}
        }
        i += 1;
    }
    a
}

/* ------------------------------------------------------------------------- counting */

/// The workbench's own notion of a preview candidate, kept identical on purpose.
///
/// `refs_from_group` spans every member, which is what makes a texture reachable when it
/// hangs off a `.mtl` rather than the hub. When that yields nothing the directory fallback
/// applies — the same order the card and the workbench use, so all three agree on which
/// assets "have an image".
fn image_candidates(cat: &Catalog, g: &Group, by_dir: &BTreeMap<&str, Vec<u64>>) -> Vec<u64> {
    let mut out: Vec<u64> = cat
        .refs_from_group(g.id)
        .unwrap_or_default()
        .into_iter()
        .filter(|r| labels::is_texture_name(&r.name))
        .filter_map(|r| r.to)
        .collect();
    if out.is_empty() {
        if let Some(hits) = by_dir.get(g.dir.as_str()) {
            out.extend(hits.iter().copied());
        }
    }
    out.sort_unstable();
    out.dedup();
    out
}

fn counter(m: &mut BTreeMap<String, usize>, k: impl Into<String>) {
    *m.entry(k.into()).or_default() += 1;
}

fn finish(m: BTreeMap<String, usize>, zh: fn(&str) -> String) -> Vec<Count> {
    let mut v: Vec<Count> = m
        .into_iter()
        .map(|(key, n)| Count { label: zh(&key), key, n })
        .collect();
    v.sort_by(|a, b| b.n.cmp(&a.n).then(a.key.cmp(&b.key)));
    v
}

fn scenario_of(kind: &str) -> String {
    match kind {
        "model" | "npc" | "monster" | "pet" => "角色",
        "weapon" | "equip" | "item" => "物件",
        "map" | "scene" | "building" => "场景",
        "effect" | "skill" => "特效",
        "ui" | "icon" => "界面",
        _ => "其他",
    }
    .to_string()
}

fn main() {
    let raw: Vec<String> = std::env::args().skip(1).collect();
    let a = parse_args(&raw);

    if !a.db.exists() {
        eprintln!("catalog not found: {}", a.db.display());
        std::process::exit(2);
    }
    let cat = match Catalog::open_ro(&a.db) {
        Ok(c) => c,
        Err(e) => {
            eprintln!("{e}");
            std::process::exit(2);
        }
    };

    let groups = cat.groups(50_000).unwrap_or_default();
    let totals = cat.totals().unwrap_or_default();
    let relations = cat.relation_census().unwrap_or_default();
    let (with_stem, group_total) = cat.stem_counts().unwrap_or((0, groups.len()));

    // One directory index, built once, so the fallback is a lookup rather than a query per
    // group — 13,080 round trips is a crawl, not a measurement.
    let mut by_dir: BTreeMap<&str, Vec<u64>> = BTreeMap::new();
    for (h, d) in cat.textures_all().unwrap_or_default() {
        // Only directories something actually names are worth indexing, and the borrow has
        // to outlive the map, so leak the leaf directory strings deliberately: this is a
        // short-lived reporting binary.
        let key: &'static str = Box::leak(d.into_boxed_str());
        by_dir.entry(key).or_default().push(h);
    }

    let mut kinds: BTreeMap<String, usize> = BTreeMap::new();
    let mut scenarios: BTreeMap<String, usize> = BTreeMap::new();
    let mut grades: BTreeMap<String, usize> = BTreeMap::new();
    let mut image_sources: BTreeMap<String, usize> = BTreeMap::new();

    let (mut with_image, mut no_candidate_because_nameless) = (0usize, 0usize);
    // How many grades were reached without measuring the body-decode axis. On this
    // catalog it is every group, because this tool does not open containers.
    let mut unmeasured = 0usize;

    for g in &groups {
        counter(&mut kinds, g.kind.clone());
        counter(&mut scenarios, scenario_of(&g.kind));

        let cands = image_candidates(&cat, g, &by_dir);
        // Which route found the pixels, because the two mean different things: a reference
        // that resolved is evidence, a same-directory texture is a guess that happens to be
        // in the right place.
        let (tex_total, tex_located) = cat.texture_refs(g.id).unwrap_or((0, 0));
        if !cands.is_empty() {
            with_image += 1;
            counter(&mut image_sources, if tex_located > 0 { "引用定位" } else { "同目录兜底" });
        } else if g.stem.is_empty() {
            no_candidate_because_nameless += 1;
        }

        // Evidence grade, from the same constructor the card uses, so the distribution
        // here is the distribution the user would see.
        //
        // This tool never opens a container, so the "did the body decode" axis is
        // genuinely unmeasurable here and is declared as such. It used to pass
        // `!cands.is_empty()` instead — the answer to a different question ("is there a
        // texture in this directory"), which made this binary report 12,134 D against the
        // workbench's 0. Declaring the axis unmeasured lets the shared constructor grade
        // on composition and references alone, which is what this tool can actually see.
        let members = cat.members(g.id).unwrap_or_default();
        let facts = tlbb_core::catalog::EvidenceFacts {
            hub_decoded: tlbb_core::catalog::Decode::Unmeasured,
            roles: members.iter().map(|m| m.role.clone()).collect(),
            members: members.len(),
            refs_total: tex_total,
            refs_located: tex_located,
        };
        if facts.unmeasured_decode() {
            unmeasured += 1;
        }
        counter(&mut grades, facts.grade().label().to_string());
    }

    let mut notes = Vec::new();
    if with_image == 0 {
        notes.push("没有任何资产产出图像候选 —— 引用链路可能已断".to_string());
    }
    if relations.self_refs == 0 {
        notes.push("refs 里零条自引用 —— 过滤规则没有东西可过滤，值得复核".to_string());
    }
    if totals.groups == 0 {
        notes.push("agroups 为空 —— 库可能是半成品".to_string());
    }

    let doc = Baseline {
        catalog: a.db.display().to_string(),
        catalog_bytes: std::fs::metadata(&a.db).map(|m| m.len()).unwrap_or(0),
        tables: cat
            .table_counts()
            .unwrap_or_default()
            .into_iter()
            .map(|(key, n)| Count { label: key.clone(), key, n })
            .collect(),
        totals,
        kinds: finish(kinds, |k| labels::kind_zh(k).to_string()),
        scenarios: finish(scenarios, |s| s.to_string()),
        grades: {
            let mut v = finish(grades, |g| g.to_string());
            // Stable A/B/C/D order rather than by count, so a grade moving between two
            // runs shows up at the same row instead of shuffling.
            v.sort_by_key(|c| c.key.chars().next().unwrap_or('Z') as u8);
            v
        },
        grade_coverage: GradeCoverage { decode_unmeasured: unmeasured },
        image_sources: finish(image_sources, |s| s.to_string()),
        relations,
        named: Named {
            with_stem,
            nameless: group_total.saturating_sub(with_stem),
            nameless_without_image: no_candidate_because_nameless,
        },
        notes,
    };

    let json = serde_json::to_string_pretty(&doc).expect("serialise");
    if let Some(p) = &a.json {
        if let Err(e) = std::fs::write(p, &json) {
            eprintln!("cannot write {}: {e}", p.display());
            std::process::exit(2);
        }
    } else {
        println!("{json}");
    }

    print_human(&doc);
    let _ = a.root;
}

fn print_human(d: &Baseline) {
    println!();
    println!("数据源 · {}", d.catalog);
    println!("库大小 · {:.1} MiB", d.catalog_bytes as f64 / 1_048_576.0);
    println!();
    println!("== 规模 ==");
    println!("  资源组        {:>8}", d.totals.groups);
    println!("  成员          {:>8}", d.totals.members);
    println!("  资源          {:>8}", d.totals.resources);
    println!("  引用名        {:>8}", d.totals.names);
    println!();
    println!("== 关系 ==");
    let r = &d.relations;
    println!("  raw refs      {:>8}", r.raw_refs);
    println!("  自引用        {:>8}", r.self_refs);
    println!("  同组内部边    {:>8}", r.internal_group_edges);
    println!("  取证关系      {:>8}  (use-* + ref)", r.forensic);
    println!("  推断关系      {:>8}  (model-part + same-stem)", r.inferred);
    println!("  relations 合计{:>8}", r.all_relations);
    println!("  悬空名        {:>8}", d.totals.dangling);
    println!();
    println!("== 命名 ==");
    println!("  有茎名        {:>8}", d.named.with_stem);
    println!("  无名组        {:>8}", d.named.nameless);
    println!("  无名且无图    {:>8}", d.named.nameless_without_image);
    println!("  有图组        {:>8}", d.totals.groups.saturating_sub(d.named.nameless_without_image));
    println!();
    println!("== 图像来源（有图组） ==");
    if d.image_sources.is_empty() {
        println!("  （无）");
    }
    for c in &d.image_sources {
        println!("  {:12} {:>6}", c.label, c.n);
    }
    println!();
    println!("== 定位等级 ==");
    for c in &d.grades {
        println!("  {:12} {:>6}", c.label, c.n);
    }
    println!();
    println!("== 场景 ==");
    for c in &d.scenarios {
        println!("  {:12} {:>6}", c.label, c.n);
    }
    println!();
    println!("== 类型 ==");
    for c in d.kinds.iter().take(20) {
        println!("  {:14} {:>6}", c.label, c.n);
    }
    if !d.notes.is_empty() {
        println!();
        println!("== 注意 ==");
        for n in &d.notes {
            println!("  · {n}");
        }
    }
}
