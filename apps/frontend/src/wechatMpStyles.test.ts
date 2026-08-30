import assert from "node:assert/strict";

import type { WechatMpHtmlStyleItem } from "./api/workbench.ts";
import {
  ALL_WECHAT_MP_HTML_STYLE_GROUP,
  filterWechatMpHtmlStyles,
  listWechatMpHtmlStyleGroups,
  resolveWechatMpHtmlStyleSelection,
} from "./wechatMpStyles.ts";

function test(name: string, fn: () => void) {
  try {
    fn();
    console.log(`PASS ${name}`);
  } catch (error) {
    console.error(`FAIL ${name}`);
    throw error;
  }
}

const styles: WechatMpHtmlStyleItem[] = [
  {
    key: "minimal",
    name: "极简黑白",
    group: "推荐默认",
    aliases: ["默认", "黑白"],
    suitable_for: ["深度文章"],
    is_builtin: true,
    is_active: true,
    is_default: true,
    sort_order: 1,
  },
  {
    key: "event",
    name: "活动公告",
    group: "中文公众号",
    aliases: ["活动", "招募"],
    suitable_for: ["活动通知"],
    is_builtin: true,
    is_active: false,
    is_default: false,
    sort_order: 15,
  },
];

test("style groups keep all as the first filter", () => {
  assert.deepEqual(listWechatMpHtmlStyleGroups(styles), [ALL_WECHAT_MP_HTML_STYLE_GROUP, "推荐默认", "中文公众号"]);
});

test("style filtering searches aliases and suitable scenes", () => {
  assert.deepEqual(filterWechatMpHtmlStyles(styles, "招募", ALL_WECHAT_MP_HTML_STYLE_GROUP).map((style) => style.key), ["event"]);
  assert.deepEqual(filterWechatMpHtmlStyles(styles, "", "推荐默认").map((style) => style.key), ["minimal"]);
});

test("style selection prefers the requested key, then default", () => {
  assert.equal(resolveWechatMpHtmlStyleSelection(styles, "event"), "event");
  assert.equal(resolveWechatMpHtmlStyleSelection(styles, "missing"), "minimal");
  assert.equal(resolveWechatMpHtmlStyleSelection([], null), null);
});
