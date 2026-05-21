import assert from "node:assert/strict";

import { prepareWechatMpArticlesForImport } from "./wechatMpImport.ts";

function test(name: string, fn: () => void) {
  try {
    fn();
    console.log(`PASS ${name}`);
  } catch (error) {
    console.error(`FAIL ${name}`);
    throw error;
  }
}

test("prepareWechatMpArticlesForImport keeps original article payload for selected rows", () => {
  const result = prepareWechatMpArticlesForImport(
    [
      {
        article_id: "2247538175_1",
        account_fakeid: "MzI0MzY4NDIyNA==",
        account_nickname: "",
        title: "听到伴侣说话就烦，不是你讨厌他",
        link: "https://mp.weixin.qq.com/s/example-1",
        author: "一凡一尘",
        digest: "从亲密关系里的情绪透支切入。",
        update_time: 1779084000,
      },
      {
        article_id: "2247538175_2",
        account_fakeid: "MzI0MzY4NDIyNA==",
        account_nickname: "今晚有语",
        title: "为什么你总在关系里先道歉",
        link: "https://mp.weixin.qq.com/s/example-2",
        author: "一凡一尘",
        digest: "从讨好模式切入。",
        update_time: 1779085000,
      },
    ],
    ["2247538175_1", "2247538175_2"],
  );

  assert.equal(result[0].account_nickname, "");
  assert.equal(result[1].account_nickname, "今晚有语");
});

test("prepareWechatMpArticlesForImport only returns selected articles", () => {
  const result = prepareWechatMpArticlesForImport(
    [
      {
        article_id: "a-1",
        account_fakeid: "fakeid-1",
        account_nickname: "",
        title: "A",
        link: "https://mp.weixin.qq.com/s/a",
        author: "作者A",
        digest: "A",
        update_time: 1,
      },
      {
        article_id: "b-1",
        account_fakeid: "fakeid-2",
        account_nickname: "",
        title: "B",
        link: "https://mp.weixin.qq.com/s/b",
        author: "作者B",
        digest: "B",
        update_time: 2,
      },
    ],
    ["b-1"],
  );

  assert.equal(result.length, 1);
  assert.equal(result[0].article_id, "b-1");
  assert.equal(result[0].account_nickname, "");
});
