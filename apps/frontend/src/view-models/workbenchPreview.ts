import type { ProjectDetail } from "../api/workbench";
import type { WorkbenchStage } from "../app/navigation";

export type WorkbenchPreviewBlock = {
  key: string;
  label: string;
  content: string;
  kind?: "text" | "markdown" | "image";
  imageUrl?: string;
};

export type WorkbenchPreviewModel = {
  title: string;
  eyebrow: string;
  summary: string;
  tone: "default" | "outline" | "draft" | "assets" | "publish";
  blocks: WorkbenchPreviewBlock[];
};

const API_BASE_URL =
  (typeof import.meta !== "undefined" && (import.meta as ImportMeta & { env?: Record<string, string | undefined> }).env
    ? (import.meta as ImportMeta & { env?: Record<string, string | undefined> }).env?.VITE_API_BASE_URL
    : undefined) ?? "http://localhost:8000/api";

function joinLines(lines: Array<string | null | undefined>): string {
  return lines
    .map((line) => line?.trim())
    .filter((line): line is string => Boolean(line))
    .join("\n");
}

function resolvePreviewAssetUrl(path: string | null | undefined): string {
  const normalizedPath = path?.trim();
  if (!normalizedPath) {
    return "";
  }
  if (/^https?:\/\//i.test(normalizedPath)) {
    return normalizedPath;
  }
  return new URL(normalizedPath, `${new URL(API_BASE_URL).origin}/`).toString();
}

export function buildWorkbenchPreview(stage: WorkbenchStage, detail: ProjectDetail): WorkbenchPreviewModel | null {
  if (stage === "outline") {
    if (!detail.outline) {
      return null;
    }

    return {
      title: detail.outline.hook,
      eyebrow: "Outline Preview",
      summary: `结构预览 · v${detail.outline.version}`,
      tone: "outline",
      blocks: [
        {
          key: "hook",
          label: "开篇钩子",
          content: detail.outline.hook,
        },
        {
          key: "outline-body",
          label: "大纲内容",
          content: detail.outline.outline_body,
          kind: "markdown",
        },
      ],
    };
  }

  if (stage === "draft") {
    if (!detail.draft) {
      return null;
    }

    return {
      title: detail.draft.title,
      eyebrow: "Draft Preview",
      summary: `正文预览 · ${detail.draft.word_count} 字`,
      tone: "draft",
      blocks: [
        {
          key: "body",
          label: "正文预览",
          content: detail.draft.body_markdown,
          kind: "markdown",
        },
      ],
    };
  }

  if (stage === "assets") {
    if (!detail.assets) {
      return null;
    }

    return {
      title: detail.assets.title_options[0] ?? "未生成标题",
      eyebrow: "Assets Preview",
      summary: "标题、封面文案与分发导语预览",
      tone: "assets",
      blocks: [
        {
          key: "cover-image",
          label: "封面图",
          content: detail.assets.cover_image_url || "未生成（图片服务暂时不可用）",
          kind: detail.assets.cover_image_url ? "image" : "text",
          imageUrl: resolvePreviewAssetUrl(detail.assets.cover_image_url),
        },
        {
          key: "titles",
          label: "标题组选项",
          content: detail.assets.title_options.map((item, index) => `${index + 1}. ${item}`).join("\n"),
          kind: "markdown",
        },
        {
          key: "cover-copy",
          label: "封面文案",
          content: detail.assets.cover_copy,
        },
        {
          key: "social-teaser",
          label: "分发导语",
          content: detail.assets.social_teaser,
        },
        {
          key: "cover-prompt",
          label: "配图提示词",
          content: detail.assets.cover_prompt,
        },
      ],
    };
  }

  if (stage === "publish") {
    if (!detail.publish_package) {
      return null;
    }

    return {
      title: detail.draft?.title ?? detail.project.title,
      eyebrow: "Publish Preview",
      summary: "最终发布包与上线前检查预览",
      tone: "publish",
      blocks: [
        {
          key: "article",
          label: "正文成品",
          content: joinLines([detail.draft?.title, "", detail.draft?.body_markdown]),
          kind: "markdown",
        },
        {
          key: "abstract",
          label: "摘要",
          content: detail.publish_package.abstract,
        },
        {
          key: "tags",
          label: "标签",
          content: detail.publish_package.tags.length > 0 ? detail.publish_package.tags.join(" / ") : "暂无标签",
        },
        {
          key: "checklist",
          label: "发布前检查清单",
          content:
            detail.publish_package.publish_checklist.length > 0
              ? detail.publish_package.publish_checklist.map((item, index) => `${index + 1}. ${item}`).join("\n")
              : "暂无检查项",
          kind: "markdown",
        },
        {
          key: "editor-note",
          label: "编辑备注",
          content: detail.publish_package.editor_note,
        },
      ],
    };
  }

  return null;
}
