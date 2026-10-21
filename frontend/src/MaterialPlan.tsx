import { useEffect, useRef, useState, type FormEvent } from "react";
import { ArrowDown, ArrowUp, Check, Loader2, Plus, X } from "lucide-react";
import {
  api,
  type AgentRun,
  type Draft,
  type ReportOutline,
  type StatisticsGroup,
  type Workspace,
} from "./api";

const groups: Record<StatisticsGroup, string> = {
  projects: "项目进度",
  attendance: "人员考勤",
  achievements: "成果统计",
  satisfaction: "服务满意度",
};

export function MaterialPlanReview({
  run,
  workspace,
  onConfirmed,
  onDeclined,
  declining,
  onDirty,
  onSaving,
}: {
  run: AgentRun;
  workspace: Workspace;
  onConfirmed: (run: AgentRun) => void;
  onDeclined: () => Promise<void>;
  declining: boolean;
  onDirty: (value: boolean) => void;
  onSaving: (value: boolean) => void;
}) {
  const [draft, setDraft] = useState<Draft>(run.requirements!);
  const [sections, setSections] = useState(
    (run.outline as ReportOutline).sections,
  );
  const [busy, setBusy] = useState(false);
  const [optionId, setOptionId] = useState(run.default_plan_option || "");
  const [error, setError] = useState("");
  const alive = useRef(true);
  const lock = useRef(false);
  const attempt = useRef<{ body: string; key: string } | null>(null);
  const dirty =
    optionId !== (run.default_plan_option || "") ||
    JSON.stringify(draft) !== JSON.stringify(run.requirements) ||
    JSON.stringify(sections) !==
      JSON.stringify((run.outline as ReportOutline).sections);
  useEffect(() => {
    onDirty(dirty);
    return () => onDirty(false);
  }, [dirty, onDirty]);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      onSaving(false);
    };
  }, [onSaving]);
  const files = run.material_profile!.files;
  const option = run.plan_options?.find((item) => item.id === optionId);
  const selectedScopes = (
    option?.scopes || [
      {
        department: draft.department,
        start_date: draft.start_date,
        end_date: draft.end_date,
      },
    ]
  )
    .filter(
      (scope) =>
        scope.start_date < draft.end_date && draft.start_date < scope.end_date,
    )
    .map((scope) => ({
      ...scope,
      start_date:
        scope.start_date > draft.start_date
          ? scope.start_date
          : draft.start_date,
      end_date:
        scope.end_date < draft.end_date ? scope.end_date : draft.end_date,
    }));
  const applicable = files.filter((file) =>
    file.scopes.some((source) =>
      selectedScopes.some(
        (scope) =>
          source.department === scope.department &&
          source.start_date < scope.end_date &&
          scope.start_date < source.end_date,
      ),
    ),
  );
  const requested = [...new Set(sections.flatMap((section) => section.groups))];
  const available = new Set(applicable.map((file) => file.kind));
  const missing = requested.filter((group) => !available.has(group));
  const notesAvailable = available.has("notes");
  const unsupported = sections.some(
    (section) =>
      !applicable.some(
        (file) =>
          file.kind === "notes" ||
          section.groups.includes(file.kind as StatisticsGroup),
      ),
  );
  const scopes = run.material_profile!.scopes;
  const validScope = option
    ? option.department === draft.department &&
      option.start_date <= draft.start_date &&
      draft.start_date < draft.end_date &&
      draft.end_date <= option.end_date &&
      selectedScopes.length > 0
    : scopes.some(
        (scope) =>
          scope.department === draft.department &&
          scope.start_date <= draft.start_date &&
          draft.start_date < draft.end_date &&
          draft.end_date <= scope.end_date,
      );
  const chooseOption = (id: string) => {
    const choice = run.plan_options!.find((item) => item.id === id)!;
    setOptionId(id);
    setDraft((previous) => ({
      ...previous,
      title: choice.title,
      department: choice.department,
      start_date: choice.start_date,
      end_date: choice.end_date,
    }));
    const kinds = [
      ...new Set(
        files
          .filter((file) =>
            file.scopes.some((source) =>
              choice.scopes.some(
                (scope) =>
                  source.department === scope.department &&
                  source.start_date < scope.end_date &&
                  scope.start_date < source.end_date,
              ),
            ),
          )
          .map((file) => file.kind),
      ),
    ].filter((kind) => kind !== "notes") as StatisticsGroup[];
    setSections(
      id === run.default_plan_option
        ? (run.outline as ReportOutline).sections
        : ["工作概况", "主要成果", "问题与风险", "后续计划"].map((title) => ({
            title,
            purpose: "依据所选范围的材料整理",
            groups: kinds,
          })),
    );
  };
  const patchSection = (
    index: number,
    changes: Partial<ReportOutline["sections"][number]>,
  ) =>
    setSections((previous) =>
      previous.map((section, i) =>
        i === index ? { ...section, ...changes } : section,
      ),
    );
  const move = (index: number, step: number) =>
    setSections((previous) => {
      const result = [...previous];
      [result[index], result[index + step]] = [
        result[index + step],
        result[index],
      ];
      return result;
    });
  const confirm = async (event: FormEvent) => {
    event.preventDefault();
    if (lock.current) return;
    if (
      missing.length ||
      unsupported ||
      !validScope ||
      (!requested.length && !notesAvailable)
    ) {
      setError("请先修正部门、期间和章节材料依据，或返回材料库补充文件。");
      return;
    }
    const body = JSON.stringify({
      plan_hash: run.plan_hash,
      ...(option ? { option_id: optionId } : {}),
      requirements: {
        ...draft,
        sections: sections.map((section) => section.title.trim()),
      },
      outline: {
        groups: requested,
        sections: sections.map((section) => ({
          ...section,
          title: section.title.trim(),
          purpose: section.purpose.trim(),
        })),
      },
    });
    if (attempt.current?.body !== body)
      attempt.current = { body, key: crypto.randomUUID() };
    lock.current = true;
    setBusy(true);
    onSaving(true);
    setError("");
    try {
      const result = await api<AgentRun>(
        `/runs/${encodeURIComponent(run.id)}/confirm-plan`,
        workspace,
        {
          method: "POST",
          headers: { "Idempotency-Key": attempt.current.key },
          body,
        },
      );
      if (alive.current) {
        onDirty(false);
        onConfirmed(result);
      }
    } catch (reason) {
      if (alive.current)
        setError(
          reason instanceof Error ? reason.message : "确认失败，请重试。",
        );
    } finally {
      lock.current = false;
      onSaving(false);
      if (alive.current) setBusy(false);
    }
  };
  return (
    <section
      className="material-plan-review"
      aria-labelledby="plan-review-title"
    >
      <div className="material-section-heading">
        <div>
          <h2 id="plan-review-title">确认汇报方案</h2>
          <p>
            这是拟定方案，尚未生成报告。可以调整标题、范围、重点和章节，再决定是否生成。
          </p>
        </div>
        <span className="status-badge">等待你的确认</span>
      </div>
      {error && (
        <div className="notice error" role="alert">
          {error}
        </div>
      )}
      <form onSubmit={confirm}>
        <fieldset disabled={busy || declining} className="plan-fields">
          <legend className="sr-only">修改并确认汇报方案</legend>
          {run.plan_options && run.plan_options.length > 1 && (
            <label className="field">
              汇报方向
              <select
                value={optionId}
                onChange={(event) => chooseOption(event.target.value)}
              >
                {run.plan_options.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.title}
                  </option>
                ))}
              </select>
              <small className="field-hint">
                默认综合使用所选材料，也可以选择其中一个方向；切换后可继续调整大纲。
              </small>
            </label>
          )}
          <label className="field">
            报告标题
            <input
              required
              maxLength={160}
              value={draft.title}
              onChange={(event) =>
                setDraft((value) => ({ ...value, title: event.target.value }))
              }
            />
          </label>
          <div className="plan-scope-fields">
            <label className="field">
              覆盖部门
              <input
                readOnly
                value={
                  option
                    ? [
                        ...new Set(
                          selectedScopes.map((scope) => scope.department),
                        ),
                      ].join("、")
                    : draft.department
                }
              />
            </label>
            <label className="field">
              开始日期（含）
              <input
                required
                type="date"
                value={draft.start_date}
                onChange={(event) =>
                  setDraft((value) => ({
                    ...value,
                    start_date: event.target.value,
                  }))
                }
              />
            </label>
            <label className="field">
              结束日期（不含）
              <input
                required
                type="date"
                value={draft.end_date}
                onChange={(event) =>
                  setDraft((value) => ({
                    ...value,
                    end_date: event.target.value,
                  }))
                }
              />
            </label>
          </div>
          {!validScope && (
            <p className="notice error">
              所选文件不支持这个部门或期间，请调整范围。
            </p>
          )}
          {selectedScopes.length > 1 && (
            <div className="plan-source-list">
              <h3>各组汇报范围</h3>
              {selectedScopes.map((scope) => (
                <div key={`${scope.department}:${scope.start_date}`}>
                  <strong>{scope.department}</strong>
                  <span>
                    {scope.start_date} 至 {scope.end_date}（不含）
                  </span>
                </div>
              ))}
              <p className="field-hint">
                各组独立整理，跨部门、期间不混算指标或推断增长率。
              </p>
            </div>
          )}
          <label className="field">
            汇报重点
            <textarea
              maxLength={2000}
              rows={3}
              value={draft.focus}
              onChange={(event) =>
                setDraft((value) => ({ ...value, focus: event.target.value }))
              }
            />
          </label>
          <div className="plan-source-list">
            <h3>本次使用的文件</h3>
            {files.map((file) => (
              <div key={file.id}>
                <strong>{file.name}</strong>
                <span>
                  {file.row_count} 条
                  {!applicable.includes(file) ? " · 不在当前范围内" : ""}
                </span>
              </div>
            ))}
          </div>
          <h3>报告大纲与材料依据</h3>
          <div className="plan-sections">
            {sections.map((section, index) => {
              const sources = applicable.filter(
                (file) =>
                  file.kind === "notes" ||
                  section.groups.includes(file.kind as StatisticsGroup),
              );
              return (
                <section className="plan-section" key={index}>
                  <div className="plan-section-heading">
                    <strong>章节 {index + 1}</strong>
                    <div>
                      <button
                        type="button"
                        className="icon-button"
                        aria-label={`上移章节 ${index + 1}`}
                        disabled={index === 0}
                        onClick={() => move(index, -1)}
                      >
                        <ArrowUp size={16} />
                      </button>
                      <button
                        type="button"
                        className="icon-button"
                        aria-label={`下移章节 ${index + 1}`}
                        disabled={index === sections.length - 1}
                        onClick={() => move(index, 1)}
                      >
                        <ArrowDown size={16} />
                      </button>
                      <button
                        type="button"
                        className="icon-button"
                        aria-label={`删除章节 ${index + 1}`}
                        disabled={sections.length <= 1}
                        onClick={() =>
                          setSections((previous) =>
                            previous.filter((_, i) => i !== index),
                          )
                        }
                      >
                        <X size={16} />
                      </button>
                    </div>
                  </div>
                  <label className="field">
                    章节标题
                    <input
                      required
                      maxLength={80}
                      value={section.title}
                      onChange={(event) =>
                        patchSection(index, { title: event.target.value })
                      }
                    />
                  </label>
                  <label className="field">
                    内容要点
                    <input
                      required
                      maxLength={300}
                      value={section.purpose}
                      onChange={(event) =>
                        patchSection(index, { purpose: event.target.value })
                      }
                    />
                  </label>
                  <div className="plan-groups">
                    {Object.entries(groups)
                      .filter(([group]) =>
                        files.some((file) => file.kind === group),
                      )
                      .map(([group, label]) => (
                        <label key={group}>
                          <input
                            type="checkbox"
                            checked={section.groups.includes(
                              group as StatisticsGroup,
                            )}
                            onChange={(event) =>
                              patchSection(index, {
                                groups: event.target.checked
                                  ? [
                                      ...section.groups,
                                      group as StatisticsGroup,
                                    ]
                                  : section.groups.filter(
                                      (value) => value !== group,
                                    ),
                              })
                            }
                          />
                          {label}
                        </label>
                      ))}
                  </div>
                  <p className={sources.length ? "field-hint" : "notice error"}>
                    材料依据：
                    {sources.map((file) => file.name).join("、") ||
                      "当前没有材料可支持此章节"}
                  </p>
                </section>
              );
            })}
          </div>
          <button
            type="button"
            className="button secondary"
            disabled={sections.length >= 12}
            onClick={() =>
              setSections((previous) => [
                ...previous,
                { title: "", purpose: "", groups: requested },
              ])
            }
          >
            <Plus size={16} />
            增加章节
          </button>
          <div className="plan-limitations">
            <h3>材料缺口与使用限制</h3>
            <ul>
              {missing.map((group) => (
                <li key={group}>
                  缺少当前范围内的{groups[group]}
                  材料，请补充或取消对应统计要求。
                </li>
              ))}
              {!notesAvailable && (
                <li>
                  缺少文字说明，问题原因和后续安排只能写为建议，不能当作既有事实。
                </li>
              )}
              {requested.includes("attendance") && (
                <li>考勤仅代表已提供样本，不能据此认定部门整体出勤率。</li>
              )}
              {!requested.length && (
                <li>
                  本方案为文字汇报，不输出量化统计，也不从文字说明推算指标。
                </li>
              )}
              <li>
                文件日期不代表整期数据完整；预算等没有提供的数据不作事实结论。
              </li>
            </ul>
          </div>
          <p className="field-hint">
            确认后沿用以上文件、范围和大纲，接续数据整理、撰写与审核；
            {run.mode === "live"
              ? "继续消耗本任务剩余模型预算。"
              : "当前为离线模拟，不调用外部模型。"}
          </p>
          <div className="plan-actions">
            <button
              type="button"
              className="button secondary"
              onClick={onDeclined}
            >
              暂不生成
            </button>
            <button
              className="button primary"
              type="submit"
              disabled={Boolean(
                missing.length ||
                unsupported ||
                !validScope ||
                (!requested.length && !notesAvailable),
              )}
            >
              {busy ? (
                <Loader2 className="spin" size={16} />
              ) : (
                <Check size={16} />
              )}
              确认方案并生成
            </button>
          </div>
        </fieldset>
      </form>
    </section>
  );
}
