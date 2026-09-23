//! Chinese-facing labels for the internal classifications.

/// Asset group kind → what a player would call it.
pub fn kind_zh(kind: &str) -> &'static str {
    match kind {
        "npc" => "NPC / 怪物",
        "player" => "玩家角色",
        "map-prop" => "场景物件",
        "effect" => "特效",
        "ui" => "界面资源",
        "shared-material" => "共享材质",
        _ => "其他资源",
    }
}

/// Member role inside a group.
pub fn role_zh(role: &str) -> &'static str {
    match role {
        "model" => "模型",
        "mesh" => "网格",
        "material" => "材质",
        "animation" => "动作",
        "skeleton" => "骨骼",
        "texture" => "贴图",
        "scene" => "场景",
        "config" => "配置",
        "audio" => "音频",
        "map" => "地图",
        "effect" => "特效文件",
        "other" => "附属文件",
        _ => "未归类文件",
    }
}

/// Tag → Chinese. Unknown tags fall through verbatim.
pub fn tag_zh(tag: &str) -> std::borrow::Cow<'static, str> {
    match tag {
        "pet" => return std::borrow::Cow::Borrowed("宠物"),
        "monster" => return std::borrow::Cow::Borrowed("怪物"),
        "boss" => return std::borrow::Cow::Borrowed("首领"),
        "npc" => return std::borrow::Cow::Borrowed("NPC"),
        "building" => return std::borrow::Cow::Borrowed("建筑"),
        "tileset" => return std::borrow::Cow::Borrowed("地表贴图组"),
        "map-props" => return std::borrow::Cow::Borrowed("地图摆件"),
        "effect" => return std::borrow::Cow::Borrowed("特效"),
        "animation-set" => return std::borrow::Cow::Borrowed("动作集"),
        "player-part" => return std::borrow::Cow::Borrowed("角色部件"),
        "player-male" => return std::borrow::Cow::Borrowed("男性角色"),
        "player-female" => return std::borrow::Cow::Borrowed("女性角色"),
        "mask" => return std::borrow::Cow::Borrowed("遮罩"),
        "ui" => return std::borrow::Cow::Borrowed("界面"),
        "weapon" => return std::borrow::Cow::Borrowed("武器"),
        "mount" => return std::borrow::Cow::Borrowed("坐骑"),
        "accessory" => return std::borrow::Cow::Borrowed("配饰"),
        "item-icon" => return std::borrow::Cow::Borrowed("物品图标"),
        "scene-effect" => return std::borrow::Cow::Borrowed("场景特效"),
        "skill-effect" => return std::borrow::Cow::Borrowed("技能特效"),
        "shared-material" => return std::borrow::Cow::Borrowed("共享材质"),
        "unknown" => return std::borrow::Cow::Borrowed("未分类"),
        _ => std::borrow::Cow::Owned(tag.to_string()),
    }
}

/// Whether a name looks like an image the browser can show.
pub fn is_texture_name(name: &str) -> bool {
    let low = name.to_ascii_lowercase();
    [".tga", ".dds", ".png", ".jpg", ".jpeg", ".bmp", ".webp"]
        .iter()
        .any(|e| low.ends_with(e))
}
