/// 拼音素材名的中文注（读音）。
///
/// 客户端里没有「模型名 → 中文名」这张表（按名字、按内容回查
/// `w1351_npc_attack_gaoshanbaiyuan02` 与「高山白猿」都是 0 条），所以：
/// - `ok: true`  = **用户确认过**的写法（2026-10-28：怪物名 = 高山白猿）；
/// - `ok: false` = **按拼音推断的读音**，界面写成 `≈中文`，不冒充客户端文案。
const TABLE = [
  ["gaoshanbaiyuan", "高山白猿", true],
  ["changbiyuan", "长臂猿", false],
  ["shengubaiyuan", "深谷白猿", false],
  ["dahuangfeng", "大黄蜂", false],
  ["xiyuqiezei", "西域窃贼", false],
  ["shirenyanshi", "食人岩石", false],
  ["shanzhu", "山蛛", false],
  ["renzheshengua", "忍者神龟", false],
  ["tangguotianxin", "糖果甜心", false],
  ["jianyinghu", "剑影虎", false],
  ["yuexiaxun", "月下寻", false],
  ["daishu", "袋鼠", false],
  ["ciwei", "刺猬", false],
  ["baozi", "包子", false],
  ["machao", "马超", false],
  ["murongfu", "慕容复", false],
  ["duanyu", "段誉", false],
  ["xiaoyao", "逍遥", false],
  ["guajian", "挂件", false],
  ["yifu", "衣服", false],
  ["toufa", "头发", false],
  ["toukui", "头盔", false],
  ["shenqie", "神锲", false],
  ["zuoqi", "坐骑", false],
  ["wuqi_t_shan", "武器·扇", false],
  ["wuqi_t_huan", "武器·环", false],
  ["wuqi_t_daofu", "武器·刀斧", false],
  ["wuqi_t_qiangbang", "武器·枪棒", false],
  ["wuqi_t_shuangduan", "武器·双段", false],
  ["wuqi_t_danduan", "武器·单段", false],
  ["tuxiaoyao", "兔小妖", false],
  ["xianglong", "翔龙", false],
  ["xiaohualing", "小花铃", false],
  ["xiguaguai", "西瓜怪", false],
  ["jinyubaobao", "金玉宝宝", false],
  ["yuansukonglong", "元素恐龙", false],
  ["zuoqi_menghuan", "坐骑·梦幻", false],
  ["shenghuo_yaocai", "生活·药材", false],
  ["zhiwu_lvguanmucong", "植物·绿灌木丛", false],
  ["zhiwu_lvcaodui", "植物·绿草丛", false],
  ["cj_caodui", "场景·草堆", false],
  ["dl_dizhuan", "地砖", false],
  ["ui_baoxiang", "界面·宝箱", false],
  ["bmy_shanshi", "山石", false],
  ["mofamifeng", "魔法蜜蜂", false],
  ["xuanhuangtengshe", "玄黄腾蛇", false],
  ["dandanji", "蛋蛋鸡", false],
  ["rongyanjushou", "熔岩巨兽", false],
  ["huyaojianjun", "虎妖将军", false],
  ["xuanhaima", "玄海马", false],
  ["huanyizhiling", "幻翼之灵", false],
  ["lingtushuangjie", "灵兔双杰", false],
  ["danghu", "当扈", false],
  ["shenyuan", "深渊", false],
  ["jiuxiaozhanlong", "九霄战龙", false],
  ["yanhun", "炎魂", false],
  ["mengyinhualing", "梦隐花铃", false],
  ["leilin", "雷灵", false],
  ["xiaomifeng", "小蜜蜂", false],
  ["yuanyang", "鸳鸯", false],
  ["xiaomuling", "小木灵", false],
  ["maomi", "猫咪", false],
  ["xixiajiangjunfu", "西夏将军府", false],
  ["liqinglu", "离情鹿", false],
  ["azhu", "阿朱", false],
  ["azi", "阿紫", false],
  ["duanyanqing", "段延庆", false],
  ["zhongling", "钟灵", false],
  ["qiaofeng", "乔峰", false],
  ["xuzhu", "虚竹", false],
  ["muwanqing", "木婉清", false],
  ["zhaotianshi", "赵天师", false],
  ["wangyuyan", "王语嫣", false],
  ["husiluohan", "呼斯罗汉", false],
  ["jiumozhi", "鸠摩智", false],
  ["diancang", "点苍", false],
  ["zhenshoufuti", "珍兽附体", false],
  ["wuqi", "武器", false],
  ["caiji", "采集", false],
  ["shenghuo", "生活", false],
  ["kuangshi", "矿石", false],
  ["jingji", "竞技", false],
  ["biaoche", "镖车", false],
  ["qianzhuang", "钱庄", false],
  ["jiaochang", "校场", false],
  ["shufang", "书房", false],
  ["huandie", "幻蝶", false],
  ["bingcan", "冰蚕", false],
  ["youlong", "游龙", false],
];

const byKey = new Map(TABLE.map(([k, zh, ok]) => [k, { zh, ok }]));

/// 从素材名里找最长命中的拼音段（去数字尾、支持多段拼接）。
export function glossOf(stem) {
  const s = String(stem || "").toLowerCase();
  if (!s) return null;
  const toks = s.split(/[_\-.]/).filter(Boolean);
  for (let n = toks.length; n >= 1; n--) {
    for (let i = 0; i + n <= toks.length; i++) {
      const key = toks
        .slice(i, i + n)
        .map((t) => t.replace(/\d+$/, ""))
        .join("_");
      if (byKey.has(key)) return byKey.get(key);
    }
  }
  return null;
}

/// 界面文案：确认过的直写，推断的带 ≈。
export function glossText(stem) {
  const g = glossOf(stem);
  if (!g) return "";
  return g.ok ? g.zh : `≈${g.zh}`;
}

/// 中文 → 拼音键：搜索框里输中文时先翻成拼音再搜。
/// 只认词表里的中文（最长匹配优先），翻不出来就原样返回空串，交给原来的搜索。
export function pinyinForChinese(q) {
  const s = String(q || "").trim();
  if (!s) return "";
  let best = "";
  let bestZh = "";
  for (const [k, g] of byKey) {
    if (s.includes(g.zh) && g.zh.length > bestZh.length) {
      best = k;
      bestZh = g.zh;
    }
  }
  return best;
}
