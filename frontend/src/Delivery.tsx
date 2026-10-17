import { useCallback, useEffect, useRef, useState } from "react";
import { Download, Loader2, Pencil, RefreshCw, Save, X } from "lucide-react";
import {
  api,
  ApiError,
  downloadReport,
  type AgentRun,
  type Narrative,
  type ReportRevision,
  type RevisionDetail,
  type RevisionList,
  type Workspace,
} from "./api";

const labels: Record<ReportRevision["status"], string> = {
  approved: "审核合格",
  needs_review: "修改后待审核",
  reviewing: "审核进行中",
  needs_changes: "需要修改",
};
const describe = (reason: unknown) =>
  reason instanceof Error ? reason.message : "操作未完成，请重试。";
const display = (value: number | null, unit: string) =>
  value === null
    ? "未定义"
    : unit === "ratio"
      ? `${(value * 100).toFixed(2)}%`
      : String(value);

function ReportPreview({ revision }: { revision: RevisionDetail }) {
  const snapshot = revision.snapshot;
  const expand = (text: string) =>
    text.replace(/\[\[(fact|note):([A-Z]\d{3})\]\]/g, (original, kind, id) => {
      if (kind === "fact") {
        const fact = snapshot.facts.find((item) => item.id === id);
        return fact
          ? `${fact.label}：${display(fact.value, fact.unit)}${fact.unit === "ratio" ? "" : fact.unit}（${id}）`
          : original;
      }
      const note = snapshot.notes.find((item) => item.id === id);
      return note
        ? `【材料原文，非统计指标：${note.text}；来源${id}】`
        : original;
    });
  const limitations = [
    ...new Set(snapshot.facts.flatMap((fact) => fact.limitations)),
  ];
  return (
    <article className="delivery-document" aria-label="当前修订报告阅读视图">
      <header>
        <h2>{snapshot.requirements.title}</h2>
        <p>
          {snapshot.requirements.department} ·{" "}
          {snapshot.requirements.start_date}（含）至{" "}
          {snapshot.requirements.end_date}（不含）
        </p>
      </header>
      {snapshot.mode === "offline_mock" && (
        <p className="notice">
          离线模拟演练：本报告使用本地确定性回复，不代表真实大模型生成。
        </p>
      )}
      {snapshot.narrative.sections.map((section) => (
        <section key={section.title}>
          <h3>{section.title}</h3>
          <p className="delivery-prose">{expand(section.text)}</p>
        </section>
      ))}
      {snapshot.narrative.suggestions.length > 0 && (
        <section>
          <h3>建议（尚未发生）</h3>
          <ul>
            {snapshot.narrative.suggestions.map((item, index) => (
              <li key={index}>{expand(item)}</li>
            ))}
          </ul>
        </section>
      )}
      <section>
        <h3>权威统计与口径</h3>
        <div
          className="delivery-table-scroll"
          tabIndex={0}
          aria-label="权威统计表，可左右滚动"
        >
          <table>
            <thead>
              <tr>
                <th>编号 / 指标</th>
                <th>数值</th>
                <th>定义</th>
              </tr>
            </thead>
            <tbody>
              {snapshot.facts.map((fact) => (
                <tr key={fact.id}>
                  <th scope="row">
                    <small>{fact.id}</small>
                    {fact.label}
                  </th>
                  <td>
                    {display(fact.value, fact.unit)}
                    {fact.unit !== "ratio" && ` ${fact.unit}`}
                  </td>
                  <td>{fact.definition}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <section>
        <h3>数据限制</h3>
        {limitations.length ? (
          <ul>
            {limitations.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        ) : (
          <p>请结合所选材料范围理解报告，文字材料不直接生成权威指标。</p>
        )}
      </section>
      <details className="cooperation-object">
        <summary>查看数据来源与材料哈希</summary>
        {snapshot.facts.map((fact) => (
          <section key={fact.id}>
            <h3>
              {fact.id} · {fact.label}
            </h3>
            <ul className="delivery-sources">
              {fact.source_refs.map((source, index) => (
                <li key={index}>
                  {source.name} · 版本 {source.version} · {source.location}
                  <br />
                  字段：{source.fields.join("、")}
                  <br />
                  <code>SHA256 {source.sha256}</code>
                </li>
              ))}
            </ul>
          </section>
        ))}
        {snapshot.notes.map((note) => (
          <p className="delivery-source-note" key={note.id}>
            {note.id} · {note.name} · 版本 {note.version} · {note.location}
            <br />
            <code>SHA256 {note.sha256}</code>
          </p>
        ))}
      </details>
      <details className="cooperation-object">
        <summary>查看同一快照的 Markdown 原文</summary>
        <pre>{snapshot.markdown}</pre>
      </details>
    </article>
  );
}

export function Delivery({
  reportId,
  workspace,
  onDirty,
  onSaving,
  navigate,
  onChanged,
}: {
  reportId: string;
  workspace: Workspace;
  onDirty: (value: boolean) => void;
  onSaving: (value: boolean) => void;
  navigate: (path: string) => void;
  onChanged: () => void;
}) {
  const [list, setList] = useState<RevisionList | null>(null);
  const [selected, setSelected] = useState("");
  const [revision, setRevision] = useState<RevisionDetail | null>(null);
  const [editing, setEditing] = useState(false);
  const [narrative, setNarrative] = useState<Narrative | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [reviewRun, setReviewRun] = useState<AgentRun | null>(null);
  const active = useRef(false);
  const locked = useRef(false);
  const reviewAttempt = useRef<{ revision: string; key: string } | null>(null);
  const base = `/reports/${encodeURIComponent(reportId)}/revisions`;
  const lastReportState = useRef("");
  const reportState = list?.items.length
    ? `${list.report_version}:${list.current_revision_id}:${list.items[0].id}:${list.items[0].status}`
    : "";
  useEffect(() => {
    if (reportState && reportState !== lastReportState.current) {
      lastReportState.current = reportState;
      // The run may finish before its local delivery callback. Refresh the parent
      // list only when the persisted revision state actually arrives or changes.
      onChanged();
    }
  }, [reportState, onChanged]);
  const dirty =
    editing &&
    narrative !== null &&
    JSON.stringify(narrative) !== JSON.stringify(revision?.snapshot.narrative);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
      onSaving(false);
    };
  }, [onSaving]);
  useEffect(() => {
    onDirty(dirty);
    return () => onDirty(false);
  }, [dirty, onDirty]);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    let timer: number | undefined;
    let reads = 0;
    const load = async () => {
      try {
        const result = await api<RevisionList>(base, workspace, {
          signal: controller.signal,
        });
        if (controller.signal.aborted) return;
        setList(result);
        setSelected((value) =>
          result.items.some((item) => item.id === value)
            ? value
            : result.current_revision_id || result.items[0]?.id || "",
        );
        setRevision((value) => {
          const summary = result.items.find((item) => item.id === value?.id);
          return value && summary ? { ...value, ...summary } : value;
        });
        reads += 1;
        const pending =
          !result.items.length ||
          result.items.some(
            (item) =>
              item.status === "reviewing" ||
              (item.current &&
                item.status === "approved" &&
                item.artifacts.some((artifact) =>
                  ["missing", "running"].includes(artifact.state),
                )),
          );
        if (pending && reads < 15) timer = window.setTimeout(load, 2000);
      } catch (reason) {
        if (!controller.signal.aborted) setError(describe(reason));
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    };
    void load();
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [base, workspace, refresh]);
  useEffect(() => {
    if (!selected) return;
    const controller = new AbortController();
    setRevision(null);
    api<RevisionDetail>(`${base}/${encodeURIComponent(selected)}`, workspace, {
      signal: controller.signal,
    })
      .then((result) => {
        if (controller.signal.aborted) return;
        setRevision(result);
        setNarrative(structuredClone(result.snapshot.narrative));
        setError("");
      })
      .catch((reason) => {
        if (!controller.signal.aborted) setError(describe(reason));
      });
    return () => controller.abort();
  }, [base, workspace, selected, refresh]);
  // A refresh only reads a persisted review run. It never resubmits a model request.
  const runningId =
    reviewRun && ["queued", "running"].includes(reviewRun.status)
      ? reviewRun.id
      : revision?.status === "reviewing"
        ? revision.review_run_id
        : null;
  useEffect(() => {
    if (!runningId) return;
    let stopped = false;
    let timer: number | undefined;
    const controller = new AbortController();
    const poll = async () => {
      try {
        const result = await api<AgentRun>(
          `/runs/${encodeURIComponent(runningId)}`,
          workspace,
          { signal: controller.signal },
        );
        if (stopped) return;
        setReviewRun(result);
        if (!["queued", "running"].includes(result.status)) {
          reviewAttempt.current = null;
          setRefresh((value) => value + 1);
          return;
        }
      } catch (reason) {
        if (stopped) return;
        setError(describe(reason));
        if (reason instanceof ApiError && [403, 404].includes(reason.status))
          return;
      }
      if (!stopped) timer = window.setTimeout(poll, 2000);
    };
    void poll();
    return () => {
      stopped = true;
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [runningId, workspace]);
  const operation = useCallback(
    async (name: string, action: () => Promise<void>) => {
      if (locked.current) return;
      locked.current = true;
      setBusy(name);
      setError("");
      onSaving(true);
      try {
        await action();
      } catch (reason) {
        if (active.current) setError(describe(reason));
      } finally {
        locked.current = false;
        onSaving(false);
        if (active.current) setBusy("");
      }
    },
    [onSaving],
  );
  const save = () =>
    operation("save", async () => {
      if (!revision || !list || !narrative) return;
      const next = await api<RevisionDetail>(base, workspace, {
        method: "POST",
        body: JSON.stringify({
          expected_report_version: list.report_version,
          expected_revision_id: revision.id,
          narrative,
        }),
      });
      if (!active.current) return;
      setEditing(false);
      onDirty(false);
      setSelected(next.id);
      setRevision(next);
      setRefresh((value) => value + 1);
    });
  const review = () =>
    operation("review", async () => {
      if (!revision) return;
      if (reviewAttempt.current?.revision !== revision.id)
        reviewAttempt.current = {
          revision: revision.id,
          key: crypto.randomUUID(),
        };
      const result = await api<AgentRun>(
        `${base}/${revision.id}/review`,
        workspace,
        {
          method: "POST",
          headers: { "Idempotency-Key": reviewAttempt.current.key },
          body: "{}",
        },
      );
      if (!active.current) return;
      setReviewRun(result);
      if (!["queued", "running"].includes(result.status))
        reviewAttempt.current = null;
      setRefresh((value) => value + 1);
    });
  const exportFiles = () =>
    operation("export", async () => {
      if (!revision) return;
      const result = await api<RevisionDetail>(
        `${base}/${revision.id}/exports`,
        workspace,
        { method: "POST" },
      );
      if (active.current) {
        setRevision(result);
        setRefresh((value) => value + 1);
      }
    });
  const staleScope =
    !!revision && !!list && revision.report_version !== list.report_version;
  const cancelEdit = () => {
    setEditing(false);
    setNarrative(
      revision ? structuredClone(revision.snapshot.narrative) : null,
    );
    onDirty(false);
  };
  return (
    <section className="delivery" aria-label="报告修订与文件交付">
      <div className="delivery-heading">
        <div>
          <h2>报告与文件</h2>
          <p className="field-hint">
            每份文件绑定不可变修订；查看、下载和重试导出不会调用模型。
          </p>
        </div>
        <button
          type="button"
          className="text-button"
          disabled={!!busy || editing}
          onClick={() => setRefresh((value) => value + 1)}
        >
          <RefreshCw size={14} />
          刷新
        </button>
      </div>
      {error && (
        <div className="notice error" role="alert">
          {error}
        </div>
      )}
      {loading && !list ? (
        <p role="status">正在读取报告修订…</p>
      ) : !list?.items.length ? (
        <p className="field-hint">
          还没有可交付修订。仅完整协作通过 Checker 和 Manager 验收后生成。
        </p>
      ) : (
        <>
          <label className="field delivery-revision-selector">
            报告修订
            <select
              value={selected}
              disabled={editing || !!busy || !!runningId}
              onChange={(event) => {
                setSelected(event.target.value);
                setReviewRun(null);
              }}
            >
              {list.items.map((item) => (
                <option value={item.id} key={item.id}>
                  修订 {item.number} · {labels[item.status]}
                  {item.current ? " · 当前" : " · 历史"}
                </option>
              ))}
            </select>
          </label>
          {!revision ? (
            <p role="status">正在读取修订内容…</p>
          ) : (
            <>
              <div className="delivery-meta">
                <span className="status-badge">{labels[revision.status]}</span>
                <span>
                  {revision.current ? "当前修订" : "历史修订"} ·{" "}
                  {revision.mode === "live" ? "真实模型" : "离线模拟"}
                </span>
                <code title={revision.content_hash}>
                  内容 SHA256 {revision.content_hash.slice(0, 12)}…
                </code>
              </div>
              {staleScope && (
                <p className="notice">
                  报告范围已更新，此修订仍绑定旧范围，不能修改或重新审核。已合格的冻结文件仍可下载或重试生成。
                </p>
              )}
              {!revision.current && (
                <p className="notice">
                  你正在查看历史修订。已合格的历史文件可以下载；以标记“当前”的修订作为最新结果。
                </p>
              )}
              {revision.status !== "approved" && (
                <p className="notice">
                  本修订尚未合格，不能导出。保存修改后须由 Checker
                  重新审核、Manager 验收；审核不会自动改写你的文字。
                </p>
              )}
              {revision.review_error && (
                <p className="notice error" role="alert">
                  {revision.review_error.message}（{revision.review_error.code}
                  ）
                </p>
              )}
              <div className="delivery-actions">
                {revision.status === "approved" &&
                  revision.artifacts.map((artifact) => (
                    <button
                      type="button"
                      className="button secondary"
                      key={artifact.format}
                      disabled={!!busy || editing || artifact.state !== "ready"}
                      onClick={() =>
                        void operation(
                          `download-${artifact.format}`,
                          async () => {
                            await downloadReport(
                              reportId,
                              revision.id,
                              artifact.format,
                              `${revision.snapshot.requirements.title}-修订${revision.number}.${artifact.format}`,
                              workspace,
                            );
                          },
                        )
                      }
                    >
                      {busy === `download-${artifact.format}` ? (
                        <Loader2 size={15} className="spin" />
                      ) : (
                        <Download size={15} />
                      )}
                      {artifact.format === "md" ? "Markdown" : "PDF"} 下载
                    </button>
                  ))}
                {revision.status === "approved" &&
                  revision.artifacts.some((item) => item.state !== "ready") && (
                    <button
                      type="button"
                      className="button secondary"
                      disabled={!!busy || editing}
                      onClick={() => void exportFiles()}
                    >
                      {busy === "export" ? (
                        <Loader2 size={15} className="spin" />
                      ) : (
                        <RefreshCw size={15} />
                      )}
                      生成 / 重试文件
                    </button>
                  )}
                {revision.current &&
                  !staleScope &&
                  !editing &&
                  revision.status !== "reviewing" && (
                    <button
                      type="button"
                      className="button secondary"
                      disabled={!!busy || !!runningId}
                      onClick={() => {
                        setNarrative(
                          structuredClone(revision.snapshot.narrative),
                        );
                        setEditing(true);
                      }}
                    >
                      <Pencil size={15} />
                      修改文字
                    </button>
                  )}
                {revision.current &&
                  !staleScope &&
                  ["needs_review", "needs_changes"].includes(revision.status) &&
                  !editing && (
                    <button
                      type="button"
                      className="button primary"
                      disabled={!!busy || !!runningId}
                      onClick={() => void review()}
                    >
                      {busy === "review" || runningId ? (
                        <Loader2 size={15} className="spin" />
                      ) : (
                        <RefreshCw size={15} />
                      )}
                      重新审核与验收
                    </button>
                  )}
                {runningId && (
                  <button
                    type="button"
                    className="text-button"
                    disabled={editing || !!busy}
                    onClick={() => navigate(`/runs/${runningId}`)}
                  >
                    查看审核进度
                  </button>
                )}
              </div>
              {revision.artifacts
                .filter((item) => item.state === "failed")
                .map((artifact) => (
                  <p className="notice error" key={artifact.format}>
                    {artifact.format.toUpperCase()} 文件生成失败：
                    {artifact.error || "请重试文件导出"}。报告内容已保留。
                  </p>
                ))}
              {editing && narrative ? (
                <form
                  className="delivery-editor"
                  onSubmit={(event) => {
                    event.preventDefault();
                    void save();
                  }}
                >
                  <h3>修改报告文字</h3>
                  <p className="field-hint">
                    章节标题和统计数据固定。保留已有引用标记，例如
                    [[fact:F001]]；引用对应事实会自动展开。新增事实须先补充材料并重新生成。
                  </p>
                  <fieldset disabled={!!busy}>
                    {narrative.sections.map((section, index) => (
                      <label className="field" key={section.title}>
                        {section.title}
                        <textarea
                          rows={5}
                          required
                          minLength={1}
                          maxLength={1200}
                          value={section.text}
                          onChange={(event) =>
                            setNarrative({
                              ...narrative,
                              sections: narrative.sections.map(
                                (item, position) =>
                                  position === index
                                    ? { ...item, text: event.target.value }
                                    : item,
                              ),
                            })
                          }
                        />
                      </label>
                    ))}
                    <h3>建议（尚未发生）</h3>
                    {narrative.suggestions.map((item, index) => (
                      <div className="delivery-suggestion" key={index}>
                        <label className="field">
                          建议 {index + 1}
                          <textarea
                            rows={2}
                            required
                            maxLength={1200}
                            value={item}
                            onChange={(event) =>
                              setNarrative({
                                ...narrative,
                                suggestions: narrative.suggestions.map(
                                  (text, position) =>
                                    position === index
                                      ? event.target.value
                                      : text,
                                ),
                              })
                            }
                          />
                        </label>
                        <button
                          className="text-button"
                          type="button"
                          onClick={() =>
                            setNarrative({
                              ...narrative,
                              suggestions: narrative.suggestions.filter(
                                (_, position) => position !== index,
                              ),
                            })
                          }
                          aria-label={`删除建议 ${index + 1}`}
                        >
                          <X size={16} />
                        </button>
                      </div>
                    ))}
                    {narrative.suggestions.length < 8 && (
                      <button
                        type="button"
                        className="text-button"
                        onClick={() =>
                          setNarrative({
                            ...narrative,
                            suggestions: [...narrative.suggestions, ""],
                          })
                        }
                      >
                        添加建议
                      </button>
                    )}
                    <div className="delivery-actions">
                      <button
                        className="button primary"
                        disabled={!dirty}
                        type="submit"
                      >
                        {busy === "save" ? (
                          <Loader2 size={15} className="spin" />
                        ) : (
                          <Save size={15} />
                        )}
                        保存新修订
                      </button>
                      <button
                        className="button secondary"
                        type="button"
                        onClick={cancelEdit}
                      >
                        取消修改
                      </button>
                    </div>
                  </fieldset>
                </form>
              ) : (
                <ReportPreview revision={revision} />
              )}
              <details className="cooperation-object">
                <summary>本修订审核记录</summary>
                <pre>
                  {JSON.stringify(
                    {
                      review: revision.review,
                      acceptance: revision.acceptance,
                      attempts: revision.review_attempts,
                    },
                    null,
                    2,
                  )}
                </pre>
              </details>
            </>
          )}
        </>
      )}
    </section>
  );
}
