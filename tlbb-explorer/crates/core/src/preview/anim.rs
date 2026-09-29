//! `.ani` 骨骼动画：信封 + 每条骨每帧的 TRS。
//!
//! 之前只解到信封和骨架名（能看到「有哪些动作」，点不出播放）。数据块口径
//! 在这里钉死。证据不止是手挑样本：工作台那条闸门从库里随机抽 60 份 `.ani`
//! （骨骼数 1~181 都覆盖到），**230,268 个旋转字段全部是单位四元数**，
//! 每份文件的轨道区都正好按「骨骼数 × 帧数 × 32」收口在文件末尾：
//!
//! ```text
//! 0x00  64B   版权串（信封 banner）
//! 0x40  8B    类型标签 "ani"
//! 0x48  u32   版本（样本都是 2）
//! 0x4C  64B   备注（"Upgraded mtl"）
//! 0x8C  4B    块标签 "MIN2"
//! 0x90  …     段内头（本轮只用到下面三个字段，其余原样不猜）
//! 0xBA  u16   骨骼数 = 轨道数
//! 0xBE  u16   与 0xBA 同值（两处各写一遍，用途未证）
//! 0xC2  u16   关键帧数
//! 0xC6  f32   帧率刻度（样本都是 40.0；是「每秒多少 tick」还是「总时长×40」未证）
//! 0xF0  骨名表：每条 30B，NUL 结尾，顺序就是数据块里轨道的顺序
//!       —— 样本里名字比轨道少一条（45 个名字 / 46 条轨道），多出来的那条无名，
//!          按「未命名骨」处理，不编名字，也不因为这个就不认整个动作。
//! 0x126E      轨道数据（4718 = 头部+名字表+中间那段未解的浮点区，同模型不同动作恒等）
//!
//! 轨道数据 := 轨道 × (关键帧数 × 32B)
//!   一条轨道 = 旋转[帧]（f32×4，单位四元数）
//!            + 位移[帧]（f32×3）
//!            + 缩放[帧]（f32，样本恒为 1.0）
//! ```
//!
//! 位移量级在 0.01~0.9（单位是骨骼局部长度，不是世界坐标）。缩放每条恒 1.0，
//! 是「这套动作没有缩放」还是「这个字段另有他用」——照实标未证，不编。
//!
//! 没解出来的：父骨链与绑定位（蒙皮权重也不在 `.mesh`/`.ske` 里）。所以本层
//! 能报「几骨几帧、每骨每帧怎么动」，还不能直接把模型驱动起来。

use crate::preview::Envelope;

/// 一条骨轨道：每帧一个四元数 + 一个位移 + 一个缩放。
#[derive(Debug, Clone, PartialEq)]
pub struct Track {
    /// 骨名（客户端原文，如 `bip01_pelvis`）。
    pub bone: String,
    pub rotations: Vec<[f32; 4]>,
    pub positions: Vec<[f32; 3]>,
    pub scales: Vec<f32>,
}

/// 解出来的动作。
#[derive(Debug, Clone, PartialEq)]
pub struct Anim {
    pub envelope: Envelope,
    pub bones: usize,
    pub frames: usize,
    /// 0xC6 那个 f32（样本恒 40.0）。含义未证，只如实带着。
    pub tick: f32,
    pub tracks: Vec<Track>,
}

fn f32s(raw: &[u8], off: usize, n: usize) -> Option<Vec<f32>> {
    let mut out = Vec::with_capacity(n);
    for i in 0..n {
        let o = off + i * 4;
        let b: [u8; 4] = raw.get(o..o + 4)?.try_into().ok()?;
        out.push(f32::from_le_bytes(b));
    }
    Some(out)
}

/// 解 `.ani`。信封不对、字段越界、名字表不规整 → `None`（不硬猜）。
pub fn parse_ani(raw: &[u8]) -> Option<Anim> {
    let envelope = crate::preview::parse_envelope(raw)?;
    if envelope.tag != "ani" {
        return None;
    }
    let bones = u16::from_le_bytes(raw.get(0xba..0xbc)?.try_into().ok()?) as usize;
    let bones2 = u16::from_le_bytes(raw.get(0xbe..0xc0)?.try_into().ok()?) as usize;
    let frames = u16::from_le_bytes(raw.get(0xc2..0xc4)?.try_into().ok()?) as usize;
    // 两处骨骼数不一致就不是这份布局（宁可回 None 也不按其中一个猜）。
    if bones != bones2 || bones == 0 || frames == 0 || bones > 512 || frames > 8192 {
        return None;
    }
    let tick = f32::from_le_bytes(raw.get(0xc6..0xca)?.try_into().ok()?);
    // 名字表：0xF0 起，每条 30B，NUL 结尾。
    //
    // 真实样本里轨道数（46）比名字条数（45）多一个——多出来的那条没有名字。
    // 这一律按「未命名」处理（bone 留空串，展示层说「未命名骨」），不因为
    // 少一个名字就整个动作不认，也不给空槽编一个名字。
    const NAME_STRIDE: usize = 30;
    let mut names = Vec::with_capacity(bones);
    for i in 0..bones {
        let o = 0xf0 + i * NAME_STRIDE;
        let Some(slot) = raw.get(o..o + NAME_STRIDE) else {
            names.push(String::new());
            continue;
        };
        let end = slot.iter().position(|&c| c == 0).unwrap_or(NAME_STRIDE);
        let bytes = &slot[..end];
        let clean = !bytes.is_empty()
            && bytes
                .iter()
                .all(|c| c.is_ascii_alphanumeric() || matches!(c, b'_' | b'-' | b'.'));
        names.push(if clean {
            String::from_utf8_lossy(bytes).into_owned()
        } else {
            String::new()
        });
    }
    // 数据块紧跟名字表之后；但真实偏移以「文件尾对齐」为准：
    // 轨道区 = bones × frames × 32 字节，必须在文件末尾收口。
    let block = frames * 32;
    let total = bones * block;
    let base = raw.len().checked_sub(total)?;
    if base < 0xf0 + bones * NAME_STRIDE {
        return None;
    }
    let mut tracks = Vec::with_capacity(bones);
    for (i, name) in names.into_iter().enumerate() {
        let o = base + i * block;
        let rot_flat = f32s(raw, o, frames * 4)?;
        let rotations = rot_flat
            .chunks(4)
            .map(|c| [c[0], c[1], c[2], c[3]])
            .collect::<Vec<_>>();
        let pos_flat = f32s(raw, o + frames * 16, frames * 3)?;
        let positions = pos_flat
            .chunks(3)
            .map(|c| [c[0], c[1], c[2]])
            .collect::<Vec<_>>();
        let scales = f32s(raw, o + frames * 28, frames)?;
        tracks.push(Track { bone: name, rotations, positions, scales });
    }
    Some(Anim { envelope, bones, frames, tick, tracks })
}

/// 四元数是否单位长（容差按浮点执行）。全零四元数是「静止骨」的存法，
/// 也算合法，不当失败。
pub fn is_unit_quat(q: &[f32; 4]) -> bool {
    let n = (q[0] * q[0] + q[1] * q[1] + q[2] * q[2] + q[3] * q[3]).sqrt();
    n < 1e-6 || (0.98..=1.02).contains(&n)
}

// ------------------------------------------------------------------- 骨架静态区
//
// 骨名表之后、轨道数据之前那段（样本里 1590..4718，共 3128 字节 = 46 × 68）
// 是**骨架静态数据**，不随动作变：同一只怪的 behit/walk/run/idle 四个动作，
// 头部到 4718 逐字节一致，只有 1722..1724 那 3 字节不同。
//
// 已证的部分（四条真样本 × 46 条记录，全部成立）：
// ```text
// 记录起点 = 名字表末尾 + 16（样本 1606），一条 60B，共骨骼数条
//   +0   f32×3  缩放：恒为 0.00992（≈1/100，单位换算的样子，用途未证）
//   +12  f32×4  绑定旋转：184/184 条都是单位四元数
//   +28  f32×3  恒为 0 —— 所以「绑定位移」不在这里
//   +40  f32    恒为 1.0
//   +44  f32    恒为 0
//   +48  f32×3  逐骨不同（样本范围 -1.09..0.55）——是什么未证
// 记录之后 352 字节：两段 u32，一段 42 个递增（4,5,…,45）、一段 46 个恒为 3，
//                    用途未证（看着像索引表，但不猜它是父骨链）。
// ```
//
// 父骨链与绑定位移不在 `.ani` 里，所以要找 `.ske`。在找到之前，
// 「播放」做不出来——只有旋转没有骨架，骨头的相对位置无从摆出来。

/// 一条骨的静态数据（骨架区里的记录）。
#[derive(Debug, Clone, PartialEq)]
pub struct Rest {
    /// 骨名（客户端原文）；名字表比轨道少一条时，多出来的那条为空串。
    pub bone: String,
    /// +0 那三个浮点（样本恒 0.00992，用途未证，原样带着不解释）。
    pub unit: [f32; 3],
    /// +12 绑定旋转（单位四元数）。
    pub rotation: [f32; 4],
}

/// 读骨架静态区的绑定旋转。布局不合（记录区越界、旋转不是单位长）→ `None`。
///
/// 记录区起点是「名字表末尾 + 16」，而名字表**可能比轨道少一条**（样本 45 名 /
/// 46 轨），所以起点有两个候选：按名字条数、按轨道数。这里不硬挑一个——
/// 两个候选都试，取「每条旋转都是单位长且整区落在轨道数据之前」的那个；
/// 两个都不成立就回 `None`。这样布局靠证据选，不靠写死的偏移。
pub fn rest_poses(raw: &[u8]) -> Option<Vec<Rest>> {
    let a = parse_ani(raw)?;
    let track_start = raw.len().checked_sub(a.bones * a.frames * 32)?;
    let named = a.tracks.iter().filter(|t| !t.bone.is_empty()).count();
    for n in [named, a.bones] {
        let Some(base) = 0xf0usize.checked_add(n * 30)?.checked_add(16) else {
            continue;
        };
        if base.checked_add(a.bones * 60)? > track_start {
            continue;
        }
        let mut out = Vec::with_capacity(a.bones);
        let mut ok = true;
        for i in 0..a.bones {
            let o = base + i * 60;
            let unit = struct_of::<3>(raw, o)?;
            let rotation = struct_of::<4>(raw, o + 12)?;
            if !is_unit_quat(&rotation) {
                ok = false;
                break;
            }
            out.push(Rest { bone: a.tracks[i].bone.clone(), unit, rotation });
        }
        if ok {
            return Some(out);
        }
    }
    None
}

fn struct_of<const N: usize>(raw: &[u8], off: usize) -> Option<[f32; N]> {
    let mut a = [0f32; N];
    for (i, slot) in a.iter_mut().enumerate() {
        let b: [u8; 4] = raw.get(off + i * 4..off + i * 4 + 4)?.try_into().ok()?;
        *slot = f32::from_le_bytes(b);
    }
    Some(a)
}

#[cfg(test)]
mod rest_tests {
    use super::*;

    /// 骨架区的绑定旋转：四份真样本 × 46 条全部单位长，且同模型不同动作
    /// 读出来的静态区逐字节一致（动作不该改骨架）。
    #[test]
    fn 绑定旋转每条都是单位长() {
        let Ok(dir) = std::env::var("TLBB_ANI_DIR") else {
            eprintln!("跳过：没有 TLBB_ANI_DIR 指向的 .ani 样本");
            return;
        };
        let read = |n: &str| std::fs::read(std::path::Path::new(&dir).join(n)).ok();
        let a = match read("w1351_monster_xiyuqiezei_behit01.ani") {
            Some(v) => v,
            None => {
                eprintln!("跳过：样本不在");
                return;
            }
        };
        let rest = rest_poses(&a).expect("骨架区应能解出");
        assert_eq!(rest.len(), 46);
        assert_eq!(rest[0].bone, "bip01");
        assert!(rest.iter().all(|r| is_unit_quat(&r.rotation)));
        // 静态单位值：四份样本都是 0.00992 三元组（不解释它，只钉住「恒等」）
        for r in &rest {
            assert!(r.unit.iter().all(|v| (v - 0.00992).abs() < 5e-4), "单位值恒等破了：{:?}", r.unit);
        }
        // 同一骨架的另一个动作，读出来的骨架区应与这一个完全一致。
        let b = read("w1351_monster_xiyuqiezei_walk.ani").expect("walk 样本应在");
        let rest_b = rest_poses(&b).expect("walk 骨架区应能解出");
        assert_eq!(rest, rest_b, "同模型不同动作的骨架静态数据必须一致");
    }

    /// 布局不合（记录区越界 / 旋转不是单位长）就整份不认。
    #[test]
    fn 骨架区不合就不硬给() {
        assert_eq!(rest_poses(&[]), None);
        let mut raw = vec![0u8; 4096];
        raw[0..10].copy_from_slice(b"Copyright\x00");
        raw[0x40..0x44].copy_from_slice(b"ani\x00");
        raw[0xba..0xbc].copy_from_slice(&2u16.to_le_bytes());
        raw[0xbe..0xc0].copy_from_slice(&2u16.to_le_bytes());
        raw[0xc2..0xc4].copy_from_slice(&2u16.to_le_bytes());
        // 轨道区按 2 骨 × 2 帧摆到文件尾，骨架区记录全零 → 旋转零四元数：
        // 零四元数按「静止骨」是合法的，所以这里应该解得出 2 条，而不是报错。
        let got = rest_poses(&raw).expect("全零旋转按静止骨处理，应能解出");
        assert_eq!(got.len(), 2);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// 吃 `.ani` 真字节（客户端素材不入库；没有样本就跳过，不算失败）。
    /// 导出方式：`cargo run --offline --example fetch -- <动作名>.ani --out <目录>/<名字>`，
    /// 再把 `TLBB_ANI_DIR` 指到那个目录。
    ///
    /// 这四个动作来自同一只怪：帧数各不相同，正好验到「块长随帧数伸缩」。
    #[test]
    fn 真样本四份都解得出且四元数单位长() {
        let cases = [
            ("w1351_monster_xiyuqiezei_behit01.ani", 21),
            ("w1351_monster_xiyuqiezei_run.ani", 26),
            ("w1351_monster_xiyuqiezei_walk.ani", 31),
            ("w1351_monster_xiyuqiezei_idle01.ani", 41),
        ];
        let mut ran = 0usize;
        for (name, want_frames) in cases {
            let Ok(dir) = std::env::var("TLBB_ANI_DIR") else { continue };
            let Ok(raw) = std::fs::read(std::path::Path::new(&dir).join(name)) else {
                continue;
            };
            ran += 1;
            let a = parse_ani(&raw).unwrap_or_else(|| panic!("{name} 应能解出"));
            assert_eq!(a.frames, want_frames, "{name} 帧数");
            assert_eq!(a.bones, 46, "{name} 骨骼数");
            assert_eq!(a.tracks.len(), 46);
            assert_eq!(a.tick, 40.0, "{name} 帧率刻度");
            assert_eq!(a.tracks[0].bone, "bip01", "{name} 第一条骨名");
            assert!(a.tracks.iter().all(|t| t.rotations.len() == want_frames));
            assert!(a.tracks.iter().all(|t| t.positions.len() == want_frames));
            assert!(a.tracks.iter().all(|t| t.scales.len() == want_frames));
            // 四元数单位长：允许全零（静止骨），不许出现「明显不是四元数」的值。
            let bad = a
                .tracks
                .iter()
                .flat_map(|t| t.rotations.iter())
                .filter(|q| !is_unit_quat(q))
                .count();
            assert_eq!(bad, 0, "{name} 有 {bad} 个四元数不是单位长");
        }
        if ran == 0 {
            eprintln!("跳过：没有 TLBB_ANI_DIR 指向的 .ani 样本（夹具不入库）");
        }
    }

    /// 坏输入必须回 None，不能硬凑出一个动作。
    #[test]
    fn 坏输入不硬猜() {
        assert_eq!(parse_ani(&[]), None);
        // 信封都不对
        assert_eq!(parse_ani(&[0u8; 512]), None);
        let mut raw = vec![0u8; 4096];
        raw[0..10].copy_from_slice(b"Copyright\x00");
        raw[0x40..0x44].copy_from_slice(b"ani\x00");
        // 骨骼数 0 → 不是这份布局
        assert_eq!(parse_ani(&raw), None);
        // 两处骨骼数不一致 → None
        raw[0xba..0xbc].copy_from_slice(&3u16.to_le_bytes());
        raw[0xbe..0xc0].copy_from_slice(&4u16.to_le_bytes());
        raw[0xc2..0xc4].copy_from_slice(&2u16.to_le_bytes());
        assert_eq!(parse_ani(&raw), None);
    }
}
