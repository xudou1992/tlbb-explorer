// 迟到回包的丢弃规则。跑法：在 app/ 下 `node --test tests/`。

import test from "node:test";
import assert from "node:assert/strict";
import { makeSeq } from "../web/lib/seq.js";

test("request1 后到：丢弃，界面显示 request2", () => {
  const seq = makeSeq();
  const r1 = seq.next();
  const r2 = seq.next();
  assert.ok(seq.isStale(r1), "1 号已被 2 号作废");
  assert.ok(!seq.isStale(r2), "2 号仍是最新");
});

test("只发一个请求时它自己总是有效", () => {
  const seq = makeSeq();
  const r1 = seq.next();
  assert.equal(seq.isStale(r1), false);
  assert.equal(seq.current(), r1);
});

test("换资产但没发新请求，也要能作废在途回包", () => {
  const seq = makeSeq();
  const inflight = seq.next();
  seq.next(); // 切走了：即使不发新请求也必须让在途的回包作废
  assert.equal(seq.isStale(inflight), true);
});

test("号只增不减，重复调用不会让旧号重新有效", () => {
  const seq = makeSeq();
  const seen = Array.from({ length: 50 }, () => seq.next());
  assert.equal(new Set(seen).size, 50);
  assert.equal(seen.filter((id) => !seq.isStale(id)).length, 1);
});
