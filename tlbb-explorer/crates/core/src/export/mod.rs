//! 把解出来的内部数据写成**别的工具也认识**的格式。
//!
//! - [`gltf`] —— `.mesh` 几何 → glTF 2.0 (`.glb`)，给浏览器和任意 3D 查看器用。
//!
//! 这一层不做解码也不查库：只吃已经证实的解析结果，缺的东西不编。

pub mod gltf;

pub use gltf::{to_glb, SlotStyle};
