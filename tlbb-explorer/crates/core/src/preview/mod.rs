//! Turning decoded payloads into something a person can look at.
//!
//! 两层：
//! - [`image`] —— 像素层：RGBA → PNG。
//! - [`summary`] —— 语义层：字节 → **类型化的内容摘要**（贴图/材质/模型/动作…）。
//!
//! 语义层服务**浏览器**目标：回答「这是什么、里面有什么」。它不回答
//! 「它属于谁、为什么没名字」——那是分析模式的事。

pub mod anim;
pub mod geometry;
pub mod image;
pub mod scene;
pub mod summary;
pub mod uvfit;
pub mod uvfit_batch;

pub use anim::{parse_ani, rest_poses, Anim, Rest, Track};

pub use geometry::{node_names, parse_geometry, parse_mesh, MeshGeometry, MeshLayout};
pub use image::{png_bytes, scale_rgba, write_png};
pub use scene::{is_empty_grid, known_version, parse_scene, SceneError, SceneGrid, SceneInstance};
pub use summary::{
    anim_summary, dedup_names, material_slots, mdl_summary, mesh_summary, parse_envelope,
    printable_strings, texture_summary, AnimSummary, Envelope, FileKind, MdlSummary,
    MeshSummary, ResourceView, SlotSummary, TexSummary, ViewBody,
};
pub use uvfit::{
    build_mask, covered, decode_pool, island_variance, mdl_mesh_names, mesh_hash, open_paks,
    query_pool, rasterize, score_pool, Cand, PakSet, PoolRow, PoolTex, GRID,
};
