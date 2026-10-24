//! Turning decoded payloads into something a person can look at.
//!
//! 两层：
//! - [`image`] —— 像素层：RGBA → PNG。
//! - [`summary`] —— 语义层：字节 → **类型化的内容摘要**（贴图/材质/模型/动作…）。
//!
//! 语义层服务**浏览器**目标：回答「这是什么、里面有什么」。它不回答
//! 「它属于谁、为什么没名字」——那是分析模式的事。

pub mod anim;
pub mod effect;
pub mod geometry;
pub mod image;
pub mod pose;
pub mod rest;
pub mod scene;
pub mod summary;
pub mod uvfit;
pub mod uvfit_batch;

pub use anim::{parse_ani, rest_poses, Anim, Rest, Track};
pub use effect::{parse_pu, Effect, EffectNames, PuRecord};

pub use geometry::{
    bone_count, hierarchy_forest, hierarchy_with_virtual_root, hierarchy_stuck, hierarchy_try, node_names, parse_forest,
    parse_nodes_variant, root_count, tail_entries, tail_inf_audit, tail_stuck_detail,
    tail_stuck_why, tail_walk_steps, tail_first_entry_head, tail_is_u92, parse_geometry, parse_hierarchy, parse_mesh,
    parse_nodes, BoneNode, MeshGeometry, MeshLayout, Node, SkeletonHierarchy, SocketEntry,
    SkinInfluence, StuckPoint,
};
pub use image::{png_bytes, scale_rgba, write_png};
pub use rest::{rebuild_bind_positions, RestRebuild, RestSource, RestStats};
pub use scene::{is_empty_grid, known_version, parse_scene, SceneError, SceneGrid, SceneInstance};
pub use summary::{
    anim_summary, dedup_names, material_slots, mdl_summary, mesh_summary, parse_envelope,
    printable_strings, texture_summary, AnimSummary, Envelope, FileKind, MdlSummary,
    MeshSummary, ResourceView, SlotSummary, TexSummary, ViewBody,
};
pub use uvfit::{
    build_mask, covered, decode_pool, island_variance, mask_png, mdl_mesh_names, mesh_hash,
    open_paks, query_pool, rasterize, score_pool, Cand, PakSet, PoolRow, PoolTex, GRID,
};
