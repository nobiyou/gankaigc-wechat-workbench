import { useEffect, useState } from "react";

import {
  activateToneProfile,
  checkAIConfig,
  createToneProfile,
  deleteToneProfile,
  duplicateToneProfile,
  fetchAIConfigSummary,
  fetchDomainPacks,
  fetchPromptTemplates,
  fetchToneProfiles,
  reorderToneProfiles,
  updateToneProfile,
  type AIConfigCheckResult,
  type AIConfigSummary,
  type DomainPackSummary,
  type PromptTemplateSummary,
  type ToneProfileItem,
} from "../api/workbench";
import { formatAiConfigBaseUrl, formatAiConfigReasoning, formatAiConfigSummaryLabel } from "../aiConfig";
import { buildDomainPackSummaryLines } from "../domainPacks";
import { buildPromptTemplateSummaryLines } from "../promptTemplates";
import {
  buildToneProfileFormState,
  buildToneProfileReorderIds,
  buildToneProfileUpdatePayload,
  createToneProfileFormState,
  pickEditableToneProfile,
  pickToneProfileSelectionAfterRemoval,
  sortToneProfiles,
  type ToneProfileFormState,
  type ToneProfileMoveDirection,
} from "../toneProfiles";

type SettingsPageProps = {
  section: "tone-profiles";
};

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; profiles: ToneProfileItem[] };

type AIConfigLoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; summary: AIConfigSummary };

type DomainPacksLoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; packs: DomainPackSummary[] };

type PromptTemplatesLoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; templates: PromptTemplateSummary[] };

type NoticeState = {
  tone: "success" | "error" | "info";
  message: string;
} | null;

const SECTION_COPY: Record<SettingsPageProps["section"], { eyebrow: string; title: string; description: string }> = {
  "tone-profiles": {
    eyebrow: "Settings",
    title: "Tone Profiles",
    description: "风格配置从生产主航道中独立出来，但仍保持真实可编辑，避免设置工作干扰日常写作链路。",
  },
};

export function SettingsPage({ section }: SettingsPageProps) {
  const [loadState, setLoadState] = useState<LoadState>({ status: "loading" });
  const [aiConfigLoadState, setAiConfigLoadState] = useState<AIConfigLoadState>({ status: "loading" });
  const [domainPacksLoadState, setDomainPacksLoadState] = useState<DomainPacksLoadState>({ status: "loading" });
  const [promptTemplatesLoadState, setPromptTemplatesLoadState] = useState<PromptTemplatesLoadState>({ status: "loading" });
  const [reloadToken, setReloadToken] = useState(0);
  const [selectedProfileId, setSelectedProfileId] = useState<number | null>(null);
  const [formState, setFormState] = useState<ToneProfileFormState>(createToneProfileFormState());
  const [isCreating, setIsCreating] = useState(false);
  const [isDirty, setIsDirty] = useState(false);
  const [pendingAction, setPendingAction] = useState<string | null>(null);
  const [notice, setNotice] = useState<NoticeState>(null);
  const [aiConfigCheckResult, setAiConfigCheckResult] = useState<AIConfigCheckResult | null>(null);

  useEffect(() => {
    let isCancelled = false;
    setLoadState({ status: "loading" });
    setAiConfigLoadState({ status: "loading" });
    setDomainPacksLoadState({ status: "loading" });
    setPromptTemplatesLoadState({ status: "loading" });

    fetchToneProfiles()
      .then((profiles) => {
        if (!isCancelled) {
          setLoadState({ status: "ready", profiles: sortToneProfiles(profiles) });
        }
      })
      .catch((error: unknown) => {
        if (!isCancelled) {
          setLoadState({
            status: "error",
            message: error instanceof Error ? error.message : "Tone Profiles 加载失败。",
          });
        }
      });

    fetchAIConfigSummary()
      .then((summary) => {
        if (!isCancelled) {
          setAiConfigLoadState({ status: "ready", summary });
        }
      })
      .catch((error: unknown) => {
        if (!isCancelled) {
          setAiConfigLoadState({
            status: "error",
            message: error instanceof Error ? error.message : "AI 配置摘要加载失败。",
          });
        }
      });

    fetchDomainPacks()
      .then((packs) => {
        if (!isCancelled) {
          setDomainPacksLoadState({ status: "ready", packs });
        }
      })
      .catch((error: unknown) => {
        if (!isCancelled) {
          setDomainPacksLoadState({
            status: "error",
            message: error instanceof Error ? error.message : "赛道模板加载失败。",
          });
        }
      });

    fetchPromptTemplates()
      .then((templates) => {
        if (!isCancelled) {
          setPromptTemplatesLoadState({ status: "ready", templates });
        }
      })
      .catch((error: unknown) => {
        if (!isCancelled) {
          setPromptTemplatesLoadState({
            status: "error",
            message: error instanceof Error ? error.message : "阶段模板加载失败。",
          });
        }
      });

    return () => {
      isCancelled = true;
    };
  }, [reloadToken]);

  useEffect(() => {
    if (loadState.status !== "ready") {
      return;
    }

    if (isCreating) {
      return;
    }

    const editable = pickEditableToneProfile(loadState.profiles, selectedProfileId);
    if (!editable) {
      setSelectedProfileId(null);
      setFormState(createToneProfileFormState());
      setIsDirty(false);
      return;
    }

    setSelectedProfileId(editable.id);
    setFormState(buildToneProfileFormState(editable));
    setIsDirty(false);
  }, [isCreating, loadState, selectedProfileId]);

  const sectionCopy = SECTION_COPY[section];

  function handleFieldChange(field: keyof ToneProfileFormState, value: string) {
    setFormState((current) => ({ ...current, [field]: value }));
    setIsDirty(true);
  }

  function handleStartCreate() {
    setIsCreating(true);
    setSelectedProfileId(null);
    setFormState(createToneProfileFormState());
    setIsDirty(false);
    setNotice({ tone: "info", message: "已切换到新建模式，填写后保存即可创建新风格。" });
  }

  function handleSelectProfile(profile: ToneProfileItem) {
    setSelectedProfileId(profile.id);
    setFormState(buildToneProfileFormState(profile));
    setIsCreating(false);
    setIsDirty(false);
    setNotice(null);
  }

  async function runMutation(actionKey: string, task: () => Promise<void>) {
    setPendingAction(actionKey);
    setNotice(null);
    try {
      await task();
    } catch (error: unknown) {
      setNotice({
        tone: "error",
        message: error instanceof Error ? error.message : "操作失败，请稍后重试。",
      });
    } finally {
      setPendingAction(null);
    }
  }

  async function replaceProfiles(
    nextProfiles: ToneProfileItem[],
    options?: {
      selectedProfileId?: number | null;
      message?: string;
      creating?: boolean;
    },
  ) {
    const sortedProfiles = sortToneProfiles(nextProfiles);
    setLoadState({ status: "ready", profiles: sortedProfiles });
    setIsCreating(options?.creating ?? false);

    const nextSelectedProfileId =
      options?.selectedProfileId ?? pickEditableToneProfile(sortedProfiles, selectedProfileId)?.id ?? null;
    setSelectedProfileId(nextSelectedProfileId);

    const editable = pickEditableToneProfile(sortedProfiles, nextSelectedProfileId);
    setFormState(editable ? buildToneProfileFormState(editable) : createToneProfileFormState());
    setIsDirty(false);

    if (options?.message) {
      setNotice({ tone: "success", message: options.message });
    }
  }

  async function handleSave() {
    await runMutation(isCreating ? "create" : "save", async () => {
      const payload = buildToneProfileUpdatePayload(formState);
      if (isCreating) {
        const created = await createToneProfile(payload);
        const existingProfiles = loadState.status === "ready" ? loadState.profiles : [];
        await replaceProfiles([created, ...existingProfiles], {
          selectedProfileId: created.id,
          message: `已创建风格「${created.name}」。`,
          creating: false,
        });
        return;
      }

      if (selectedProfileId === null || loadState.status !== "ready") {
        throw new Error("当前没有可保存的风格。");
      }

      const updated = await updateToneProfile(selectedProfileId, payload);
      await replaceProfiles(
        loadState.profiles.map((profile) => (profile.id === updated.id ? updated : profile)),
        {
          selectedProfileId: updated.id,
          message: `已保存风格「${updated.name}」。`,
        },
      );
    });
  }

  async function handleActivate(profileId: number) {
    await runMutation(`activate-${profileId}`, async () => {
      if (loadState.status !== "ready") {
        throw new Error("Tone Profiles 尚未加载完成。");
      }

      const activated = await activateToneProfile(profileId);
      await replaceProfiles(
        loadState.profiles.map((profile) =>
          profile.id === activated.id ? activated : { ...profile, is_active: false },
        ),
        {
          selectedProfileId: activated.id,
          message: `已激活风格「${activated.name}」。`,
        },
      );
    });
  }

  async function handleDuplicate(profileId: number) {
    await runMutation(`duplicate-${profileId}`, async () => {
      if (loadState.status !== "ready") {
        throw new Error("Tone Profiles 尚未加载完成。");
      }

      const duplicated = await duplicateToneProfile(profileId);
      await replaceProfiles([duplicated, ...loadState.profiles], {
        selectedProfileId: duplicated.id,
        message: `已复制为新风格「${duplicated.name}」。`,
      });
    });
  }

  async function handleDelete(profileId: number) {
    await runMutation(`delete-${profileId}`, async () => {
      if (loadState.status !== "ready") {
        throw new Error("Tone Profiles 尚未加载完成。");
      }

      await deleteToneProfile(profileId);
      const nextSelectedId = pickToneProfileSelectionAfterRemoval(loadState.profiles, profileId);
      await replaceProfiles(
        loadState.profiles.filter((profile) => profile.id !== profileId),
        {
          selectedProfileId: nextSelectedId,
          message: "已删除风格。",
        },
      );
    });
  }

  async function handleMove(profileId: number, direction: ToneProfileMoveDirection) {
    await runMutation(`move-${profileId}-${direction}`, async () => {
      if (loadState.status !== "ready") {
        throw new Error("Tone Profiles 尚未加载完成。");
      }

      const profileIds = buildToneProfileReorderIds(loadState.profiles, profileId, direction);
      const reordered = await reorderToneProfiles({ profile_ids: profileIds });
      await replaceProfiles(reordered, {
        selectedProfileId: profileId,
        message: "排序已更新。",
      });
    });
  }

  async function handleCheckAiConfig() {
    setPendingAction("check-ai-config");
    setAiConfigCheckResult(null);
    try {
      const result = await checkAIConfig();
      setAiConfigCheckResult(result);
    } catch (error: unknown) {
      setAiConfigCheckResult({
        ok: false,
        status: "request_failed",
        message: error instanceof Error ? error.message : "AI 配置检测失败，请稍后重试。",
        checked_at: new Date().toISOString(),
      });
    } finally {
      setPendingAction(null);
    }
  }

  if (loadState.status === "loading") {
    return (
      <section className="workspace-page">
        <div className="dashboard-state dashboard-state--loading">
          <p className="dashboard-state__eyebrow">加载中</p>
          <h3>正在加载 Tone Profiles</h3>
          <p>正在同步风格配置、激活状态与排序信息。</p>
        </div>
      </section>
    );
  }

  if (loadState.status === "error") {
    return (
      <section className="workspace-page">
        <div className="dashboard-state dashboard-state--error">
          <p className="dashboard-state__eyebrow">加载失败</p>
          <h3>Tone Profiles 加载失败</h3>
          <p>{loadState.message}</p>
          <div className="dashboard-state__actions">
            <button className="dashboard-button" type="button" onClick={() => setReloadToken((value) => value + 1)}>
              重新加载
            </button>
          </div>
        </div>
      </section>
    );
  }

  const editableProfile = pickEditableToneProfile(loadState.profiles, selectedProfileId);
  const aiConfigSummary = aiConfigLoadState.status === "ready" ? aiConfigLoadState.summary : null;
  const domainPacks = domainPacksLoadState.status === "ready" ? domainPacksLoadState.packs : [];
  const promptTemplates = promptTemplatesLoadState.status === "ready" ? promptTemplatesLoadState.templates : [];

  return (
    <section className="workspace-page">
      <section className="workspace-section">
        <div className="workspace-section__header">
          <div>
            <p className="workspace-section__eyebrow">{sectionCopy.eyebrow}</p>
            <h3>{sectionCopy.title}</h3>
            <p className="workspace-section__description">{sectionCopy.description}</p>
          </div>
        </div>
        <div className="workspace-summary-grid">
          <article className="workspace-summary-card">
            <span>风格总数</span>
            <strong>{loadState.profiles.length}</strong>
            <p>统一维护全局写作风格，不再和生产流程同屏竞争。</p>
          </article>
          <article className="workspace-summary-card">
            <span>当前激活</span>
            <strong>{loadState.profiles.find((profile) => profile.is_active)?.name ?? "未设置"}</strong>
            <p>新项目默认跟随当前激活风格，除非项目显式绑定专属风格。</p>
          </article>
          <article className="workspace-summary-card">
            <span>AI 配置</span>
            <strong>{aiConfigSummary ? formatAiConfigSummaryLabel(aiConfigSummary) : "加载中"}</strong>
            <p>这里检查当前文本模型链路是否能通，避免等到批量任务失败后才回看日志。</p>
          </article>
        </div>
      </section>

      {notice ? <div className={`workspace-note workspace-note--${notice.tone}`}>{notice.message}</div> : null}

      <section className="workspace-section">
        <div className="workspace-section__header">
          <div>
            <p className="workspace-section__eyebrow">AI Config</p>
            <h3>模型配置检测</h3>
            <p className="workspace-section__description">
              读取当前后端实际生效的模型配置，并发起一次轻量探测请求，优先暴露 key、base URL、模型名或上游服务异常。
            </p>
          </div>
          <button
            className="dashboard-button"
            type="button"
            onClick={() => void handleCheckAiConfig()}
            disabled={pendingAction !== null || aiConfigLoadState.status !== "ready"}
          >
            {pendingAction === "check-ai-config" ? "检测中..." : "检测配置"}
          </button>
        </div>

        {aiConfigLoadState.status === "error" ? (
          <div className="workspace-note workspace-note--error">
            <p>{aiConfigLoadState.message}</p>
          </div>
        ) : null}

        {aiConfigSummary ? (
          <div className="settings-config-grid">
            <article className="settings-config-card">
              <span>接口地址</span>
              <strong>{formatAiConfigBaseUrl(aiConfigSummary.base_url)}</strong>
            </article>
            <article className="settings-config-card">
              <span>文本模型</span>
              <strong>{aiConfigSummary.model}</strong>
            </article>
            <article className="settings-config-card">
              <span>出图模型</span>
              <strong>{aiConfigSummary.image_model}</strong>
            </article>
            <article className="settings-config-card">
              <span>推理强度</span>
              <strong>{formatAiConfigReasoning(aiConfigSummary)}</strong>
            </article>
            <article className="settings-config-card">
              <span>请求超时</span>
              <strong>{`${aiConfigSummary.request_timeout_seconds} 秒`}</strong>
            </article>
            <article className="settings-config-card">
              <span>密钥状态</span>
              <strong>{aiConfigSummary.api_key_configured ? "已配置" : "未配置"}</strong>
            </article>
          </div>
        ) : null}

        {aiConfigCheckResult ? (
          <div className={`workspace-note ${aiConfigCheckResult.ok ? "workspace-note--success" : "workspace-note--error"}`}>
            <p>{aiConfigCheckResult.message}</p>
            <p>{`检测时间：${new Date(aiConfigCheckResult.checked_at).toLocaleString("zh-CN", { hour12: false })}`}</p>
          </div>
        ) : (
          <div className="workspace-note workspace-note--info">
            <p>点击“检测配置”会向当前文本模型发起一次轻量请求，用于提前发现配置错误或上游临时不可用。</p>
          </div>
        )}
      </section>

      <section className="workspace-section">
        <div className="workspace-section__header">
          <div>
            <p className="workspace-section__eyebrow">Domain Packs</p>
            <h3>赛道模板</h3>
            <p className="workspace-section__description">
              这里展示当前可用的赛道 prompt packs。它们决定生成链的受众、语气和业务约束，用来约束大纲、正文、素材和发布包的生成语境。
            </p>
          </div>
        </div>

        {domainPacksLoadState.status === "error" ? (
          <div className="workspace-note workspace-note--error">
            <p>{domainPacksLoadState.message}</p>
          </div>
        ) : null}

        {domainPacks.length > 0 ? (
          <div className="settings-config-grid">
            {domainPacks.map((pack) => (
              <article key={pack.key} className="settings-config-card">
                <span>{pack.is_default ? "默认赛道" : "候选赛道"}</span>
                <strong>{pack.label}</strong>
                <p className="settings-config-card__meta">{pack.key}</p>
                {buildDomainPackSummaryLines(pack).map((line) => (
                  <p key={`${pack.key}-${line}`} className="settings-config-card__detail">
                    {line}
                  </p>
                ))}
              </article>
            ))}
          </div>
        ) : domainPacksLoadState.status === "loading" ? (
          <div className="workspace-note workspace-note--info">
            <p>正在加载赛道模板与生成语境约束。</p>
          </div>
        ) : null}
      </section>

      <section className="workspace-section">
        <div className="workspace-section__header">
          <div>
            <p className="workspace-section__eyebrow">Prompt Templates</p>
            <h3>阶段模板</h3>
            <p className="workspace-section__description">
              这里展示当前生成链各阶段的模板职责、输出字段和可接收输入，方便核对系统到底按什么链路在生成。
            </p>
          </div>
        </div>

        {promptTemplatesLoadState.status === "error" ? (
          <div className="workspace-note workspace-note--error">
            <p>{promptTemplatesLoadState.message}</p>
          </div>
        ) : null}

        {promptTemplates.length > 0 ? (
          <div className="settings-config-grid">
            {promptTemplates.map((template) => (
              <article key={template.key} className="settings-config-card">
                <span>阶段模板</span>
                <strong>{template.label}</strong>
                <p className="settings-config-card__meta">{template.key}</p>
                {buildPromptTemplateSummaryLines(template).map((line) => (
                  <p key={`${template.key}-${line}`} className="settings-config-card__detail">
                    {line}
                  </p>
                ))}
              </article>
            ))}
          </div>
        ) : promptTemplatesLoadState.status === "loading" ? (
          <div className="workspace-note workspace-note--info">
            <p>正在加载生成链阶段模板。</p>
          </div>
        ) : null}
      </section>

      <div className="settings-layout">
        <section className="workspace-section settings-panel">
          <div className="workspace-section__header">
            <div>
              <p className="workspace-section__eyebrow">风格配置</p>
              <h3>风格列表</h3>
              <p className="workspace-section__description">选择现有风格编辑，或先复制再调整，避免直接改坏主用模板。</p>
            </div>
            <button className="dashboard-button" type="button" onClick={handleStartCreate} disabled={pendingAction !== null}>
              新建风格
            </button>
          </div>

          <div className="settings-profile-list">
            {loadState.profiles.map((profile, index) => {
              const isSelected = !isCreating && selectedProfileId === profile.id;
              const isBusy = pendingAction !== null;
              return (
                <article
                  key={profile.id}
                  className={isSelected ? "settings-profile-card settings-profile-card--selected" : "settings-profile-card"}
                >
                  <button
                    className="settings-profile-card__main"
                    type="button"
                    onClick={() => handleSelectProfile(profile)}
                    disabled={isBusy}
                  >
                    <div className="settings-profile-card__header">
                      <h4>{profile.name}</h4>
                      <div className="workspace-actions workspace-actions--row">
                        {profile.preset_key ? <span className="workspace-pill">系统预置</span> : null}
                        {profile.is_active ? <span className="workspace-pill">当前激活</span> : null}
                      </div>
                    </div>
                    <p>{profile.opening_style}</p>
                    <div className="workspace-item__meta">
                      <span>目标字数 {profile.target_word_count}</span>
                      <span>{profile.default_polish_instruction ? "带默认精修策略" : "无默认精修策略"}</span>
                      <span>排序 #{profile.sort_order}</span>
                    </div>
                  </button>

                  <div className="workspace-actions workspace-actions--row">
                    <button
                      className="dashboard-button dashboard-button--ghost"
                      type="button"
                      onClick={() => handleActivate(profile.id)}
                      disabled={isBusy || profile.is_active}
                    >
                      设为激活
                    </button>
                    <button
                      className="dashboard-button dashboard-button--ghost"
                      type="button"
                      onClick={() => handleDuplicate(profile.id)}
                      disabled={isBusy}
                    >
                      复制
                    </button>
                    <button
                      className="dashboard-button dashboard-button--ghost"
                      type="button"
                      onClick={() => handleMove(profile.id, "up")}
                      disabled={isBusy || index === 0}
                    >
                      上移
                    </button>
                    <button
                      className="dashboard-button dashboard-button--ghost"
                      type="button"
                      onClick={() => handleMove(profile.id, "down")}
                      disabled={isBusy || index === loadState.profiles.length - 1}
                    >
                      下移
                    </button>
                    <button
                      className="dashboard-button dashboard-button--ghost"
                      type="button"
                      onClick={() => handleDelete(profile.id)}
                      disabled={isBusy || loadState.profiles.length === 1}
                    >
                      删除
                    </button>
                  </div>
                </article>
              );
            })}
          </div>
        </section>

        <section className="workspace-section settings-panel">
          <div className="workspace-section__header">
            <div>
              <p className="workspace-section__eyebrow">Editor</p>
              <h3>{isCreating ? "新建风格" : editableProfile ? `编辑：${editableProfile.name}` : "暂无可编辑风格"}</h3>
              <p className="workspace-section__description">修改后立即保存到后端，供项目默认风格和后续生成链复用。</p>
            </div>
          </div>

          <div className="settings-form">
            <label className="settings-field">
              <span>风格名称</span>
              <input value={formState.name} onChange={(event) => handleFieldChange("name", event.target.value)} />
            </label>

            <label className="settings-field">
              <span>开头风格</span>
              <textarea
                rows={3}
                value={formState.opening_style}
                onChange={(event) => handleFieldChange("opening_style", event.target.value)}
              />
            </label>

            <label className="settings-field">
              <span>段落节奏</span>
              <textarea
                rows={3}
                value={formState.paragraph_rhythm}
                onChange={(event) => handleFieldChange("paragraph_rhythm", event.target.value)}
              />
            </label>

            <label className="settings-field">
              <span>结尾风格</span>
              <textarea
                rows={3}
                value={formState.closing_style}
                onChange={(event) => handleFieldChange("closing_style", event.target.value)}
              />
            </label>

            <label className="settings-field">
              <span>禁用短语</span>
              <textarea
                rows={3}
                value={formState.forbidden_phrases_text}
                onChange={(event) => handleFieldChange("forbidden_phrases_text", event.target.value)}
                placeholder="使用中文或英文逗号分隔"
              />
            </label>

            <label className="settings-field">
              <span>价值约束</span>
              <textarea
                rows={4}
                value={formState.value_constraints}
                onChange={(event) => handleFieldChange("value_constraints", event.target.value)}
              />
            </label>

            <label className="settings-field">
              <span>目标字数</span>
              <input
                inputMode="numeric"
                value={formState.target_word_count}
                onChange={(event) => handleFieldChange("target_word_count", event.target.value)}
              />
            </label>

            <label className="settings-field">
              <span>默认原创增强精修策略</span>
              <textarea
                rows={4}
                value={formState.default_polish_instruction}
                onChange={(event) => handleFieldChange("default_polish_instruction", event.target.value)}
                placeholder="未手填精修指令时，Workbench 会默认使用这条策略。"
              />
            </label>

            <div className="workspace-actions workspace-actions--row">
              <button className="dashboard-button" type="button" onClick={handleSave} disabled={pendingAction !== null}>
                {pendingAction === "save" || pendingAction === "create" ? "保存中..." : isCreating ? "创建风格" : "保存修改"}
              </button>
              <button
                className="dashboard-button dashboard-button--ghost"
                type="button"
                onClick={() => {
                  if (editableProfile && !isCreating) {
                    handleSelectProfile(editableProfile);
                    return;
                  }
                  setFormState(createToneProfileFormState());
                  setIsDirty(false);
                }}
                disabled={pendingAction !== null || (!isDirty && !isCreating)}
              >
                重置表单
              </button>
            </div>
          </div>
        </section>
      </div>
    </section>
  );
}
