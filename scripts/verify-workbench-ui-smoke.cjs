#!/usr/bin/env node

const { execFileSync } = require("node:child_process");
const { existsSync } = require("node:fs");

function parseArgs(argv) {
  const options = {
    baseUrl: "http://127.0.0.1:3000",
    edgePath: null,
    timeoutMs: 8000,
    projectSlug: "office-burnout-recovery-weekly",
  };

  for (let index = 0; index < argv.length; index += 1) {
    const current = argv[index];
    const next = argv[index + 1];

    if (current === "--base-url" && next) {
      options.baseUrl = next;
      index += 1;
      continue;
    }
    if (current === "--edge-path" && next) {
      options.edgePath = next;
      index += 1;
      continue;
    }
    if (current === "--timeout-ms" && next) {
      options.timeoutMs = Number.parseInt(next, 10);
      index += 1;
      continue;
    }
    if (current === "--project-slug" && next) {
      options.projectSlug = next;
      index += 1;
    }
  }

  return options;
}

function resolveEdgePath(explicitPath) {
  if (explicitPath) {
    if (!existsSync(explicitPath)) {
      throw new Error(`Edge path not found: ${explicitPath}`);
    }
    return explicitPath;
  }

  const candidates = [
    "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
    "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
  ];

  const match = candidates.find((candidate) => existsSync(candidate));
  if (!match) {
    throw new Error("Microsoft Edge not found. Pass --edge-path to specify msedge.exe.");
  }
  return match;
}

function buildChecks(baseUrl, projectSlug) {
  return [
    {
      name: "dashboard",
      url: `${baseUrl}/`,
      markers: ["Dashboard", "待办队列", "概览摘要", "补充热点素材", "查看项目列表", "打开入口"],
    },
    {
      name: "sources-trends",
      url: `${baseUrl}/sources/trends`,
      markers: ["Sources", "热点池与单条转选题", "当前子区", "工作边界", "单条处理", "AI 转选题"],
    },
    {
      name: "sources-wechat-import",
      url: `${baseUrl}/sources/wechat-import`,
      markers: ["Sources", "公众号文章导入", "工作边界", "公众号文章导入", "登录状态", "搜索公众号"],
    },
    {
      name: "pipeline-topics",
      url: `${baseUrl}/pipeline/topics`,
      markers: ["Pipeline", "选题队列过渡管理区", "新建原创选题", "去批量建项目"],
      evaluate(dom) {
        const hasQueueItems = dom.includes("直接建项目");
        const hasExpandedProjectConfig =
          dom.includes("建项目配置") || dom.includes("确认创建项目") || dom.includes("项目赛道");
        const markerHits = {
          Pipeline: dom.includes("Pipeline"),
          "选题队列过渡管理区": dom.includes("选题队列过渡管理区"),
          "新建原创选题": dom.includes("新建原创选题"),
          "去批量建项目": dom.includes("去批量建项目"),
          "直接建项目": hasQueueItems,
          "全部来源": hasQueueItems ? dom.includes("全部来源") : true,
          "参考文章": hasQueueItems ? dom.includes("参考文章") : true,
          "全选当前筛选": hasQueueItems ? dom.includes("全选当前筛选") : true,
          "批量废弃": hasQueueItems ? dom.includes("批量废弃") : true,
          "项目赛道": hasExpandedProjectConfig ? dom.includes("项目赛道") : true,
          "项目风格": hasExpandedProjectConfig ? dom.includes("项目风格") : true,
          "跟随当前全局风格": hasExpandedProjectConfig ? dom.includes("跟随当前全局风格") : true,
        };

        return {
          markerHits,
          passed:
            markerHits.Pipeline &&
            markerHits["选题队列过渡管理区"] &&
            markerHits["新建原创选题"] &&
            markerHits["去批量建项目"] &&
            markerHits["全部来源"] &&
            markerHits["参考文章"] &&
            markerHits["全选当前筛选"] &&
            markerHits["批量废弃"] &&
            (!hasQueueItems || (markerHits["项目赛道"] && markerHits["项目风格"] && markerHits["跟随当前全局风格"])),
        };
      },
    },
    {
      name: "pipeline-tasks",
      url: `${baseUrl}/pipeline/tasks`,
      markers: ["Pipeline", "Task Log", "任务日志与失败归位", "异步任务日志", "回到批量运行", "失败"],
    },
    {
      name: "pipeline-runs",
      url: `${baseUrl}/pipeline/runs`,
      markers: ["Pipeline", "批量运行与推进", "批量推进入口", "最近一次批量提交", "最近批量任务", "打开任务日志"],
    },
    {
      name: "projects",
      url: `${baseUrl}/projects`,
      markers: ["Projects", "项目分组与 Workbench 入口", "搜索项目", "负责人", "下一步", "打开 Workbench"],
    },
    {
      name: "workbench-publish",
      url: `${baseUrl}/projects/${projectSlug}/workbench/publish`,
      markers: ["Workbench", "Publish", "当前阶段", "历史版本", "推荐阶段", "切换赛道/风格"],
    },
    {
      name: "settings-tone-profiles",
      url: `${baseUrl}/settings/tone-profiles`,
      markers: [
        "Settings",
        "Tone Profiles",
        "风格列表",
        "当前激活",
        "新建风格",
        "保存修改",
        "赛道模板",
        "默认赛道",
        "阶段模板",
        "选题生成",
      ],
    },
  ];
}

function dumpDom(edgePath, url, timeoutMs) {
  return execFileSync(
    edgePath,
    [
      "--headless=new",
      "--disable-gpu",
      `--virtual-time-budget=${timeoutMs}`,
      "--dump-dom",
      url,
    ],
    {
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"],
      maxBuffer: 8 * 1024 * 1024,
    },
  );
}

function normalizeDom(rawDom) {
  const htmlStart = rawDom.indexOf("<!DOCTYPE html>");
  if (htmlStart >= 0) {
    return rawDom.slice(htmlStart);
  }

  const fallbackStart = rawDom.indexOf("<html");
  if (fallbackStart >= 0) {
    return rawDom.slice(fallbackStart);
  }

  return rawDom;
}

function runCheck(edgePath, check, timeoutMs) {
  try {
    const rawDom = dumpDom(edgePath, check.url, timeoutMs);
    const dom = normalizeDom(rawDom);
    const evaluation =
      typeof check.evaluate === "function"
        ? check.evaluate(dom)
        : {
            markerHits: Object.fromEntries(check.markers.map((marker) => [marker, dom.includes(marker)])),
            passed: check.markers.every((marker) => dom.includes(marker)),
          };

    return {
      name: check.name,
      url: check.url,
      passed: evaluation.passed,
      markers: evaluation.markerHits,
    };
  } catch (error) {
    return {
      name: check.name,
      url: check.url,
      passed: false,
      markers: Object.fromEntries(check.markers.map((marker) => [marker, false])),
      error: error instanceof Error ? error.message : String(error),
    };
  }
}

function main() {
  const options = parseArgs(process.argv.slice(2));
  const edgePath = resolveEdgePath(options.edgePath);
  const checks = buildChecks(options.baseUrl, options.projectSlug);
  const results = checks.map((check) => runCheck(edgePath, check, options.timeoutMs));
  const passed = results.every((result) => result.passed);

  const output = {
    baseUrl: options.baseUrl,
    edgePath,
    timeoutMs: options.timeoutMs,
    projectSlug: options.projectSlug,
    passed,
    checks: results,
  };

  process.stdout.write(`${JSON.stringify(output, null, 2)}\n`);
  process.exitCode = passed ? 0 : 1;
}

main();
