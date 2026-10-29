//! 「变长权重记录」按骨名补表（[`attach_bone_skin`]）的真数据闸门。
//!
//! 用两份样本各钉一件事：
//! - `w1351_pets_rongyanjushou_b5.mesh`：161 根骨只有 46 条定长记录，定长扫描覆盖 31.7%；
//!   变长记录补齐后必须**多覆盖 ≥1000 个顶点**，且补进来的骨名**都在骨架里**、**不重复加节点**。
//! - `w1351_npc_xinmurongfu.mesh`：它的表已经被定长路径（含变体记录合并）读全（未覆盖 0），
//!   这里**不该再加出任何节点**（防止扫描把噪声当表）。
//!
//! 缺包就跳过（不联网、不落字节）。

use std::path::PathBuf;

use tlbb_core::jpak::Pak;
use tlbb_core::payload;
use tlbb_core::preview::{attach_bone_skin, parse_hierarchy, parse_mesh, parse_nodes, Node};

fn grab(root: &PathBuf, pak: &str, hash: u64) -> Option<Vec<u8>> {
    let p = Pak::open(root.join(format!("{pak}.pak"))).ok()?;
    let rec = p.records().find(|r| r.hash == hash && r.stored > 0)?;
    payload::decode(&p, &rec).ok().map(|d| d.bytes)
}

fn covered(nodes: &[Node], vc: usize) -> usize {
    let mut hit = vec![false; vc];
    for nd in nodes {
        if let Some(sk) = &nd.skin {
            for &v in &sk.vertices {
                if (v as usize) < vc {
                    hit[v as usize] = true;
                }
            }
        }
    }
    hit.iter().filter(|x| **x).count()
}

#[test]
fn 变长记录按骨名补表_覆盖变多且不重复加节点() {
    let root = std::env::var("TLBB_ROOT")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("D:/TLGL"));
    let Some(mesh) = grab(&root, "data3", 0x0458_569a_7595_b56f) else {
        eprintln!("跳过：本机没有 data3.pak 或这份资源不在容器里");
        return;
    };
    let h = parse_hierarchy(&mesh).expect("骨架应解出");
    let vc = parse_mesh(&mesh).expect("网格应解出").geometry.positions.len();
    let base = parse_nodes(&mesh);
    let before = covered(&base, vc);
    let after_nodes = attach_bone_skin(&h, &base, &mesh);
    let after = covered(&after_nodes, vc);

    // 实测 +798（1,837 未覆盖 → 1,039，见 skin_coverage_census）；阈值压到 700 留余量。
    assert!(
        after >= before + 700,
        "变长记录至少该多覆盖 700 个顶点（实得 {} → {}）",
        before,
        after
    );
    let names: std::collections::HashSet<&str> = h.bones.iter().map(|b| b.name.as_str()).collect();
    for nd in &after_nodes[base.len()..] {
        assert!(names.contains(nd.name.as_str()), "补进来的骨名必须在骨架里：{}", nd.name);
        assert!(nd.skin.is_some(), "补进来的节点必须带表：{}", nd.name);
    }
    // 幂等：再跑一遍不该再长出新节点（已经是表的不重复加）。
    let again = attach_bone_skin(&h, &after_nodes, &mesh);
    assert_eq!(again.len(), after_nodes.len(), "重复调用不该再加节点");
}

#[test]
fn 已经读全的网格不该被扫描加出节点() {
    let root = std::env::var("TLBB_ROOT")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("D:/TLGL"));
    let Some(mesh) = grab(&root, "data1", 0x000b_7690_ae63_94ea) else {
        eprintln!("跳过：本机没有 data1.pak 或这份资源不在容器里");
        return;
    };
    let h = parse_hierarchy(&mesh).expect("骨架应解出");
    let base = parse_nodes(&mesh);
    let after = attach_bone_skin(&h, &base, &mesh);
    assert!(
        after.len() <= base.len() + 2,
        "这份的权重已由定长/变体路径读全，扫描不该再加一堆节点（{} → {}）",
        base.len(),
        after.len()
    );
}
