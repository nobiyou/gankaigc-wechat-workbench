import type { WechatMpHtmlStyleItem } from "./api/workbench";

export const ALL_WECHAT_MP_HTML_STYLE_GROUP = "全部";

export function listWechatMpHtmlStyleGroups(styles: WechatMpHtmlStyleItem[]): string[] {
  return [
    ALL_WECHAT_MP_HTML_STYLE_GROUP,
    ...Array.from(new Set(styles.map((style) => style.group).filter(Boolean))),
  ];
}

export function filterWechatMpHtmlStyles(
  styles: WechatMpHtmlStyleItem[],
  query: string,
  group: string,
): WechatMpHtmlStyleItem[] {
  const normalizedQuery = query.trim().toLowerCase();
  return styles.filter((style) => {
    const matchesGroup = group === ALL_WECHAT_MP_HTML_STYLE_GROUP || style.group === group;
    if (!matchesGroup || !normalizedQuery) {
      return matchesGroup;
    }

    const searchableText = [style.key, style.name, style.group, ...style.aliases, ...style.suitable_for]
      .join(" ")
      .toLowerCase();
    return searchableText.includes(normalizedQuery);
  });
}

export function resolveWechatMpHtmlStyleSelection(
  styles: WechatMpHtmlStyleItem[],
  preferredKey: string | null,
): string | null {
  return (
    styles.find((style) => style.key === preferredKey)?.key ??
    styles.find((style) => style.is_default)?.key ??
    styles[0]?.key ??
    null
  );
}
