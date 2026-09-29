//! `.ani` 骨骼动画：信封 + 每条骨每帧的 TRS。
//!
//! 之前只解到信封和骨架名（能看到「有哪些动作」，点不出播放）。数据块的
//! 口径在这里钉死（四个真样本 21/26/31/41 帧逐字节对齐，块尾余 0）：
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
