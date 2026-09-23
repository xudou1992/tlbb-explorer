//! Evidence grading: how much of an asset we actually hold versus how much we only
//! know the name of.
//!
//! The shipped client resolves almost no texture references (measured: 0 of 429 on a
//! 100-card sample), so a card that leads with a picture would be lying about its own
//! confidence. Grade first, image if available.

use serde::Serialize;

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize)]
pub enum Grade {
    /// Body plus its parts are all present and every reference lands on a real resource.
    A,
    /// Body decodes and the composition is multi-part, but some reference dangles.
    B,
    /// Only the body and name-level clues; the referenced parts are not held.
    C,
    /// Nothing decoded; the entry exists only as a name or a guess.
    D,
}

impl Grade {
    pub fn label(self) -> &'static str {
        match self {
            Grade::A => "A 完整定位",
            Grade::B => "B 主体定位",
            Grade::C => "C 名称证据",
            Grade::D => "D 推测",
        }
    }

    pub fn note(self) -> &'static str {
        match self {
            Grade::A => "主体与全部依赖均已定位",
            Grade::B => "主体可解码，部分依赖只有名称",
            Grade::C => "仅持有主体，依赖关系来自名称",
            Grade::D => "未能解码任何内容，条目仅为线索",
        }
    }
}

/// What the card builder knows about one group when it decides the grade.
#[derive(Debug, Default, Clone, Copy)]
pub struct Signals {
    /// The hub file decoded successfully.
    pub hub_decoded: bool,
    /// Distinct member roles present (model / mesh / material / animation / ...).
    pub role_kinds: usize,
    pub members: usize,
    /// Texture references named by the asset.
    pub refs_total: usize,
    /// Of those, how many resolve to a resource we hold.
    pub refs_located: usize,
}

/// Raw per-group facts, before they are reduced to `Signals`.
///
/// This exists because the same reduction used to be written twice — once in the
/// workbench, once in the baseline — and the two drifted:
///
/// * `role_kinds` counted distinct raw role names on one side and distinct display
///   labels on the other.
/// * `hub_decoded` meant "the body file decoded" in the workbench but "a texture exists
///   in this directory" in the baseline. Those are different questions, and answering
///   the second while calling it the first made the baseline report 12,134 D where the
///   workbench reported 0.
///
/// Both callers now hand over the same catalog-derivable facts and get the same
/// `Signals` back, so a card and a baseline cannot disagree about one asset's grade.
#[derive(Debug, Default, Clone)]
pub struct EvidenceFacts {
    /// The body/hub file was actually decoded by the read-back pass.
    ///
    /// This is the one signal the catalog cannot answer — see `Decode::Unmeasured`. A
    /// caller that cannot open containers must say so rather than substitute a proxy.
    pub hub_decoded: Decode,
    /// Member count.
    pub members: usize,
    /// Member roles, exactly as stored in `amembers.role`. Duplicates are fine.
    ///
    /// Pass raw role names, **not** display labels: several raw roles map onto one
    /// Chinese label, so counting labels under-reports a composition that is really
    /// multi-part.
    pub roles: Vec<String>,
    /// Texture-typed references the asset names, and how many resolve.
    ///
    /// Count by `labels::is_texture_name`, which is the single definition of "a texture
    /// reference" — the workbench and the baseline must not each pick their own.
    pub refs_total: usize,
    pub refs_located: usize,
}

/// Whether the body file decoded, or whether the caller is in a position to know.
///
/// A catalog-only tool cannot open a pak, so it cannot answer this. Modelling that as
/// `Unmeasured` rather than `false` is the whole point: `false` means "we looked and it
/// failed", which is a claim a catalog-only tool is not entitled to make.
#[derive(Debug, Default, Clone, Copy, PartialEq, Eq)]
pub enum Decode {
    /// Read back and decoded.
    Decoded,
    /// Read back and failed to decode.
    Failed,
    /// The caller never opened the container, so this axis is not measured.
    #[default]
    Unmeasured,
}

impl EvidenceFacts {
    /// Reduce raw facts to signals. The only place this reduction happens.
    pub fn signals(&self) -> Signals {
        let mut seen: Vec<&str> = Vec::with_capacity(self.roles.len());
        for r in &self.roles {
            if !seen.contains(&r.as_str()) {
                seen.push(r.as_str());
            }
        }
        Signals {
            hub_decoded: self.hub_decoded == Decode::Decoded,
            role_kinds: seen.len(),
            members: self.members,
            refs_total: self.refs_total,
            refs_located: self.refs_located,
        }
    }

    /// Grade straight from raw facts.
    ///
    /// When the decode axis is unmeasured, the D rule cannot fire: it would be asserting
    /// "nothing decoded" on the strength of never having looked. The grade is then the
    /// best the composition and references justify, and `unmeasured_decode()` on the
    /// caller's side is what tells a reader the body axis was skipped.
    pub fn grade(&self) -> Grade {
        if self.hub_decoded == Decode::Unmeasured {
            return self.grade_without_decode();
        }
        grade(&self.signals())
    }

    /// The composition/reference half of the rule, with the decode gate left out.
    fn grade_without_decode(&self) -> Grade {
        let s = self.signals();
        if s.members == 0 {
            return Grade::D;
        }
        let all_refs_land = s.refs_total > 0 && s.refs_located == s.refs_total;
        if s.role_kinds >= 2 && all_refs_land {
            Grade::A
        } else if s.role_kinds >= 2 {
            Grade::B
        } else {
            Grade::C
        }
    }

    /// True when the grade was reached without measuring the body file.
    pub fn unmeasured_decode(&self) -> bool {
        self.hub_decoded == Decode::Unmeasured
    }
}

/// Grade from the signals above. Kept total and side-effect free so the rules can be
/// unit-tested and reused by the browser and any later report.
pub fn grade(s: &Signals) -> Grade {
    if !s.hub_decoded || s.members == 0 {
        return Grade::D;
    }
    let all_refs_land = s.refs_total > 0 && s.refs_located == s.refs_total;
    let composition = s.role_kinds >= 2;
    if composition && all_refs_land {
        Grade::A
    } else if composition {
        Grade::B
    } else {
        Grade::C
    }
}

/// Human-readable gaps: what a B/C card is missing, stated as fact rather than as a
/// failure.
pub fn gaps(s: &Signals) -> Vec<&'static str> {
    let mut out = Vec::new();
    if s.refs_total > 0 && s.refs_located == 0 {
        out.push("贴图引用只有名称，未指向具体资源");
    } else if s.refs_located < s.refs_total {
        out.push("部分贴图引用未定位");
    }
    if s.role_kinds < 2 {
        out.push("组成单一，未见模型/材质/动作的完整搭配");
    }
    if !s.hub_decoded {
        out.push("主体文件未能解码");
    }
    out
}
