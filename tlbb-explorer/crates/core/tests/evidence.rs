//! The grade must state what is held, never what is merely named.

use tlbb_core::catalog::evidence::{grade, Decode, EvidenceFacts, Grade, Signals};

fn s(hub: bool, roles: usize, members: usize, refs: usize, loc: usize) -> Signals {
    Signals { hub_decoded: hub, role_kinds: roles, members, refs_total: refs, refs_located: loc }
}

#[test]
fn undecodable_body_is_always_d() {
    assert_eq!(grade(&s(false, 5, 40, 3, 3)), Grade::D);
    assert_eq!(grade(&s(true, 5, 0, 3, 3)), Grade::D);
}

#[test]
fn a_needs_every_reference_to_land() {
    assert_eq!(grade(&s(true, 3, 12, 4, 4)), Grade::A);
    assert_eq!(grade(&s(true, 3, 12, 4, 3)), Grade::B);
    // A body with no references at all cannot claim A on the strength of composition.
    assert_eq!(grade(&s(true, 3, 12, 0, 0)), Grade::B);
}

#[test]
fn single_role_bodies_are_name_evidence_only() {
    assert_eq!(grade(&s(true, 1, 1, 0, 0)), Grade::C);
    assert_eq!(grade(&s(true, 1, 6, 5, 0)), Grade::C);
}

#[test]
fn labels_are_chinese_and_ordered() {
    assert_eq!(Grade::A.label(), "A 完整定位");
    assert_eq!(Grade::D.label(), "D 推测");
    assert!(Grade::A < Grade::B && Grade::C < Grade::D);
    assert!(Grade::A.note().contains("定位"));
}

/* --------------------------------------------------- one constructor, one answer */

/// The workbench and the baseline used to grade the same asset differently, because each
/// reduced the raw facts its own way. They now both go through `EvidenceFacts`. These tests
/// pin the reduction itself, so a third caller cannot quietly reintroduce a fourth rule.

fn facts(decode: Decode, roles: &[&str], members: usize, refs: usize, loc: usize) -> EvidenceFacts {
    EvidenceFacts {
        hub_decoded: decode,
        roles: roles.iter().map(|r| r.to_string()).collect(),
        members,
        refs_total: refs,
        refs_located: loc,
    }
}

#[test]
fn role_kinds_counts_raw_roles_not_display_labels() {
    // Four members, three distinct raw roles. Counting *labels* instead would collapse
    // `model`/`mesh` onto one Chinese label and under-report a genuinely multi-part body,
    // which is what made the workbench grade 2 groups higher than the baseline.
    let f = facts(Decode::Decoded, &["model", "mesh", "mesh", "material"], 4, 1, 1);
    assert_eq!(f.signals().role_kinds, 3);
    assert_eq!(f.grade(), Grade::A);

    // A single role repeated is still a single kind: composition is not multitplied by
    // member count.
    let g = facts(Decode::Decoded, &["texture", "texture", "texture"], 3, 1, 1);
    assert_eq!(g.signals().role_kinds, 1);
    assert_eq!(g.grade(), Grade::C);
}

#[test]
fn members_zero_is_d_regardless_of_decode() {
    // An entry with no members holds nothing, so it cannot be evidence of anything. This
    // must hold on both the measured and the unmeasured decode axis: a catalog-only caller
    // is still allowed to conclude "empty".
    assert_eq!(facts(Decode::Decoded, &[], 0, 0, 0).grade(), Grade::D);
    assert_eq!(facts(Decode::Failed, &[], 0, 0, 0).grade(), Grade::D);
    assert_eq!(facts(Decode::Unmeasured, &["model"], 0, 0, 0).grade(), Grade::D);
}

#[test]
fn unmeasured_decode_never_asserts_d() {
    // The load-bearing rule behind the 12,134-vs-0 disagreement. A tool that never opened
    // a container must not report "nothing decoded" — it must grade on what it can see and
    // say the decode axis was skipped.
    let f = facts(Decode::Unmeasured, &["model", "material"], 2, 1, 0);
    assert!(f.unmeasured_decode());
    assert_ne!(f.grade(), Grade::D);
    assert_eq!(f.grade(), Grade::B);

    // The same facts with a measured, failed decode *do* earn D. The two axes are
    // genuinely different questions, and this is where that shows.
    let g = facts(Decode::Failed, &["model", "material"], 2, 1, 0);
    assert!(!g.unmeasured_decode());
    assert_eq!(g.grade(), Grade::D);
}

#[test]
fn unmeasured_grade_agrees_with_the_measured_rule_above_d() {
    // Whenever the decode axis is unmeasured, the result must equal the composition-only
    // rule — i.e. the same call the workbench would make had the body decoded. If these
    // ever diverge, the two tools are back to two rules.
    for roles in [vec![], vec!["model"], vec!["model", "mesh"]] {
        for (refs, loc) in [(0usize, 0usize), (1, 0), (1, 1), (4, 3), (4, 4)] {
            // members follows the role list, so the empty case exercises the members==0
            // gate that both the measured and the unmeasured path must agree on.
            let facts = facts(Decode::Unmeasured, &roles, roles.len(), refs, loc);
            let measured = facts.clone();
            let measured = EvidenceFacts { hub_decoded: Decode::Decoded, ..measured };
            let expect = match (roles.len(), refs > 0 && loc == refs) {
                (0, _) => Grade::D,
                (1, _) => Grade::C,
                (_, true) => Grade::A,
                (_, false) => Grade::B,
            };
            assert_eq!(facts.grade(), expect, "unmeasured roles={roles:?} refs={refs}/{loc}");
            assert_eq!(measured.grade(), expect, "decoded roles={roles:?} refs={refs}/{loc}");
        }
    }
}

#[test]
fn signals_are_a_pure_function_of_the_facts() {
    // Two callers handing over the same facts must get byte-identical signals; this is the
    // property that makes a card and a baseline physically unable to disagree.
    let a = facts(Decode::Decoded, &["model", "material"], 2, 3, 3);
    let b = facts(Decode::Decoded, &["model", "material", "material"], 3, 3, 3);
    let (sa, sb) = (a.signals(), b.signals());
    assert_eq!(sa.hub_decoded, sb.hub_decoded);
    assert_eq!(sa.role_kinds, sb.role_kinds);
    assert_eq!(sa.refs_total, sb.refs_total);
    assert_eq!(sa.refs_located, sb.refs_located);
    // Member count is the one field that legitimately differs, and it does not move the grade.
    assert_eq!(a.grade(), b.grade());
}
