//! View models crossing the IPC boundary. Keys stay English because they are code; the
//! values the user can see are plain Chinese, and the terms that are not for players
//! (identifiers, container names, byte offsets) only ever appear inside `Tech`.

use serde::{Deserialize, Serialize};

#[derive(Serialize, Clone, Debug)]
#[serde(rename_all = "camelCase")]
pub struct Count {
    pub label: String,
    pub count: usize,
}

#[derive(Serialize, Clone, Debug)]
#[serde(rename_all = "camelCase")]
pub struct RefItem {
    pub name: String,
    /// 贴图 / 材质 / 模型 / ...
    pub kind: String,
    /// 已找到 or 只有名字
    pub status: String,
    pub located: bool,
}

#[derive(Serialize, Clone, Debug)]
#[serde(rename_all = "camelCase")]
pub struct Card {
    pub gid: i64,
    /// Verbatim stem from the client. The shipped client carries no Chinese display
    /// name, so this is never translated.
    pub name: String,
    pub subtitle: String,
    pub kind: String,
    pub scenario: String,
    pub grade: String,
    pub grade_word: String,
    pub grade_note: String,
    pub tags: Vec<String>,
    pub parts: Vec<Count>,
    pub placeholder: String,
    pub member_total: usize,
    pub ref_total: usize,
    pub located_total: usize,
    /// 这组「材质写了贴图名、清单没登记路径」里，有几个能按客户端 `convert/*`
    /// 换算对上真实贴图文件。界面拿它把「缺」和「其实解得出来」分开说——
    /// 之前两者混在一个计数里，「缺什么 2 处」里有一处就写着「可按转换路径解出」。
    pub tex_solvable: usize,
    /// 有没有能对人说的名字。false 时界面写「未命名资源」，不把编号摆成标题。
    pub named: bool,
    /// Best candidate for a real image; `None` means nothing was even referenced.
    pub preview_hash: Option<String>,
}

#[derive(Serialize, Clone, Debug)]
#[serde(rename_all = "camelCase")]
pub struct MemberItem {
    pub role_word: String,
    pub name: String,
    pub has_image: bool,
    pub hash: String,
}

#[derive(Serialize, Clone, Debug)]
#[serde(rename_all = "camelCase")]
pub struct Tech {
    pub id: String,
    pub container: String,
    pub offset: i64,
    pub bytes: i64,
    pub codec: String,
    pub fingerprint: Option<String>,
    pub rules: Vec<String>,
    /// How many names the catalog recorded for this group.
    pub names: usize,
    pub folder: String,
    pub path: String,
}

#[derive(Serialize, Clone, Debug)]
#[serde(rename_all = "camelCase")]
pub struct Detail {
    pub card: Card,
    pub refs: Vec<RefItem>,
    pub gaps: Vec<String>,
    pub name_source: String,
    /// Whether the body itself was read back and expanded. Drives the wording of the
    /// evidence chain, never a guess.
    pub hub_decoded: bool,
    pub members: Vec<MemberItem>,
    pub tech: Tech,
}

#[derive(Serialize, Clone, Debug)]
#[serde(rename_all = "camelCase")]
pub struct Image {
    /// `data:image/png;base64,...` — the shell has no web server to fetch from.
    pub url: String,
    pub width: u32,
    pub height: u32,
    pub format: String,
}

#[derive(Serialize, Clone, Debug)]
#[serde(rename_all = "camelCase")]
pub struct Option2 {
    pub value: String,
    pub label: String,
    pub count: usize,
}

#[derive(Serialize, Clone, Debug)]
#[serde(rename_all = "camelCase")]
pub struct Stats {
    pub total_groups: usize,
    pub scanned: usize,
    pub ready: bool,
    pub scenarios: Vec<Option2>,
    pub kinds: Vec<Option2>,
    pub grades: Vec<Option2>,
    /// Groups that name at least one texture we could try to render — not a promise
    /// that pixels came out, which the card itself decides on demand.
    pub image_candidates: usize,
    /// 至少有一张贴图能对上真实文件的组数——两条边取并：清单登记了贴图成员，
    /// 或材质里写的名字能按客户端 `convert/*` 转换路径对上文件。
    /// 页脚报的是这个数；`image_candidates` 只是第一条边（全库 25 组），单独摆出来会被读成
    /// 「工具只有 25 组能看图」。
    pub paintable_groups: usize,
    /// How many bodies were actually read back and expanded so far.
    pub decoded: usize,
    pub located_refs: usize,
    pub total_refs: usize,
    /// 既没名字又没路径的组数——界面上「未命名资源」那个入口的数字。
    pub unnamed: usize,
    pub containers: usize,
    pub catalog_file: String,
    pub root: String,
}

#[derive(Serialize, Deserialize, Clone, Debug, Default)]
#[serde(rename_all = "camelCase", default)]
pub struct Filter {
    pub query: Option<String>,
    pub scenario: Option<String>,
    pub kind: Option<String>,
    pub grade: Option<String>,
    /// 只列「至少有一张贴图能对上真实文件」的组（判据见 `Stats::paintable_groups`）。
    /// 这里原来有 `only_with_image`：界面标签写的是「只看有缺失的资源」，筛的却是
    /// 「清单登记了贴图成员」那 25 组——方向相反，且按标签真做会命中全库 86%。
    pub only_paintable: Option<bool>,
    /// Some(true) 只列有名字的，Some(false) 只列没名字的，None 不管。
    pub named: Option<bool>,
    pub limit: Option<usize>,
    pub offset: Option<usize>,
}

#[derive(Serialize, Default, Clone, Debug)]
#[serde(rename_all = "camelCase")]
pub struct Page {
    pub items: Vec<Card>,
    pub total: usize,
    pub scanned: usize,
    pub ready: bool,
    pub query_words: Vec<String>,
}

/// One extension's share of the citation graph, worded for a reader.
#[derive(Serialize, Clone, Debug)]
#[serde(rename_all = "camelCase")]
pub struct RefExtView {
    pub ext: String,
    /// 材质 / 网格 / 动作 ... — the extension is code, this is what it means.
    pub kind: String,
    pub total: usize,
    pub resolved: usize,
    /// Distinct names carrying this extension that never landed. Counted separately from
    /// `total`, which counts edges — the two are different units on purpose.
    pub dangling_names: usize,
    /// `dangling_names` 里有多少个**能按客户端 `convert/*` 转换路径对上真实文件**。
    /// 与 `resolved` 不重叠：那条是清单登记了名字/路径的，这条是清单没路径、按客户端
    /// 换算找得到文件的。合起来才是「真能用上的」——只看上一条会把 30,585 个贴图名
    /// 报成「只有 25 个对得上」（实测 90.7% 的贴图名其实对得上文件）。
    pub solvable_names: usize,
    /// `solvable_names / dangling_names`，0-100，同样在后端算一次——前端不许再舍入一遍。
    pub solvable_pct: u32,
    /// `resolved / total`, 0-100, so the frontend never rounds it a second way.
    pub resolved_pct: u32,
}

/// A cited name that lands on nothing we hold.
#[derive(Serialize, Clone, Debug)]
#[serde(rename_all = "camelCase")]
pub struct DanglingView {
    pub name: String,
    pub kind: String,
    pub citations: usize,
    pub sources: usize,
    /// 对上实体时的 16 位编号；悬空名字没有编号，反查只能按名字。
    pub hash: Option<String>,
}

/// The citation graph's health: what we can prove versus what we merely read a name for.
/// This is the panel's whole payload — every number comes from `Catalog::ref_health`.
#[derive(Serialize, Clone, Debug)]
#[serde(rename_all = "camelCase")]
pub struct RefView {
    pub refs_total: usize,
    pub refs_resolved: usize,
    /// `refs_resolved / refs_total`, as a 0-100 integer so the frontend never rounds
    /// two different ways.
    pub resolved_pct: u32,
    pub dangling_names: usize,
    /// 全库对不上的名字里，可按 `convert/*` 转换路径对上文件的总数（贴图之外一律 0）。
    pub dangling_solvable: usize,
    pub by_ext: Vec<RefExtView>,
    pub top_dangling: Vec<DanglingView>,
    /// Distinct assets with any citation at all — the denominator for the ratio below.
    pub assets_citing: usize,
    /// How many assets cite at least one name we resolved — the usable graph's size.
    pub assets_citing_resolved: usize,
    /// The most-mentioned resources that *did* resolve. The mirror of `top_dangling`,
    /// so the panel can show both halves and not only the failures.
    pub top_cited: Vec<DanglingView>,
}

/// Who cites a given resource, by name. The answer is "these files contain this string",
/// which is a fact; it is deliberately not worded as sharing or ownership.
#[derive(Serialize, Clone, Debug)]
#[serde(rename_all = "camelCase")]
pub struct CitationView {
    pub from_path: String,
    pub kind: String,
    /// Whether the citing asset is one the catalog grouped.
    pub grouped: bool,
}

#[derive(Serialize, Clone, Debug)]
#[serde(rename_all = "camelCase")]
pub struct CitedByView {
    pub hash: String,
    pub citations: Vec<CitationView>,
    /// True when the list was cut off at the query's cap.
    pub truncated: bool,
}
