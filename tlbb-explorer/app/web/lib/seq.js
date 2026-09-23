// 请求序号锁。纯函数，不碰 DOM——「迟到的回包不能盖住新请求」这条规矩
// 是前端最容易出事的地方（切资产、切筛选、反查连点都是同一个形状）。
//
// 用法：发请求前 `const my = seq.next()`，回包后 `if (seq.isStale(my)) return;`。

export function makeSeq() {
  let now = 0;
  return {
    /// 领一个新号；同时作废上一号（换资产/换查询时即使不发新请求也要调用）。
    next() {
      now += 1;
      return now;
    },
    /// 当前有效号。
    current() {
      return now;
    },
    /// 拿到回包时判断：这个号还是最新的吗？
    isStale(id) {
      return id !== now;
    },
  };
}
