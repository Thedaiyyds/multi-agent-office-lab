import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  Circle,
  Loader2,
  RefreshCw,
  Sparkles,
  Square,
  TriangleAlert,
} from "lucide-react";
import {
  api,
  ApiError,
  type AgentRun,
  type MaterialVersion,
  type Report,
  type RunMode,
  type SystemInfo,
  type Workspace,
} from "./api";

import { Delivery } from "./Delivery";
import { MaterialPlanReview } from "./MaterialPlan";

const roleLabels: Record<string, string> = {
  manager: "需求经理",
  planner: "内容规划",
  data: "数据整理",
  writer: "报告撰写",
  checker: "审核校验",
};
const statusLabels: Record<AgentRun["status"], string> = {
  queued: "排队中",
  running: "协作进行中",
  needs_input: "需要补充信息",
  completed: "已验收完成",
  review_failed: "审核未通过",
  failed: "执行失败",
  cancelled: "已取消",
  interrupted: "运行已中断",
  awaiting_confirmation: "待确认方案",
};
const terminal = (status: AgentRun["status"]) =>
  !["queued", "running"].includes(status);
const message = (reason: unknown) =>
  reason instanceof Error ? reason.message : "请求未完成，请重试。";
const time = (value: string) =>
  new Date(value).toLocaleString("zh-CN", { hour12: false });
const text = (value: unknown) =>
  typeof value === "string"
    ? value
    : JSON.stringify(value, null, 2) || "暂无结果";
const reportRequest = (report?: Report) =>
  report
    ? `请生成${report.title}。所属部门：${report.department}；报告期间：${report.start_date}（含）至${report.end_date}（不含）。章节：${report.sections.join("、")}。${report.focus ? `重点要求：${report.focus}` : ""}`
    : "";

export function RunComposer({
  workspace,
  system,
  report,
  onDirty,
  onSaving,
  onStarted,
  planning = false,
  initialMaterialIds = [],
}: {
  workspace: Workspace;
  system: SystemInfo | null;
  report?: Report;
  onDirty: (value: boolean) => void;
  onSaving: (value: boolean) => void;
  onStarted: (run: AgentRun) => void;
  planning?: boolean;
  initialMaterialIds?: string[];
}) {
  const [userText, setUserText] = useState(() => reportRequest(report));
  const [materials, setMaterials] = useState<MaterialVersion[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [mode, setMode] = useState<RunMode>("live");
  const [useLocal, setUseLocal] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [baseline, setBaseline] = useState(() =>
    JSON.stringify({ selected: [], mode: "live", useLocal: false }),
  );
  const initialized = useRef(false);
  const mounted = useRef(false);
  const lock = useRef(false);
  const attempt = useRef<{ payload: string; key: string } | null>(null);
  const dirty =
    userText.trim() !== reportRequest(report).trim() ||
    JSON.stringify({ selected, mode, useLocal }) !== baseline;
  const priorRequest = useRef(reportRequest(report));
  useEffect(() => {
    const next = reportRequest(report);
    const previous = priorRequest.current;
    setUserText((value) => (value === previous ? next : value));
    priorRequest.current = next;
  }, [report?.version, report?.id]);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
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
    setError("");
    api<{ items: MaterialVersion[] }>("/materials", workspace, {
      signal: controller.signal,
    })
      .then(({ items }) => {
        if (controller.signal.aborted) return;
        setMaterials(items);
        if (!initialized.current) {
          const latest = new Map<string, MaterialVersion>();
          for (const item of items) {
            const key = `${item.kind}:${item.name}`;
            if (!latest.has(key) || latest.get(key)!.version < item.version)
              latest.set(key, item);
          }
          const ids = planning
            ? items
                .filter((item) => initialMaterialIds.includes(item.id))
                .slice(0, 50)
                .map((item) => item.id)
            : [...latest.values()].slice(0, 50).map((item) => item.id);
          setSelected(ids);
          setBaseline(
            JSON.stringify({ selected: ids, mode: "live", useLocal: false }),
          );
          initialized.current = true;
        }
      })
      .catch((reason) => {
        if (!controller.signal.aborted) setError(message(reason));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [workspace, refresh]);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (lock.current) return;
    if (planning && !selected.length) {
      setError("请先选择需要规划汇报的材料文件。");
      return;
    }
    if (!planning && !userText.trim()) {
      setError("请先用一段话说明希望生成什么工作汇报。");
      return;
    }
    if (mode === "live" && !system?.model_configured) {
      setError(
        "尚未配置模型连接。请在本地配置后刷新系统设置，或主动选择离线模拟；系统不会自动降级。",
      );
      return;
    }
    const payload = JSON.stringify({
      user_text: userText.trim() || "根据所选材料提出一份工作汇报方案",
      material_ids: selected,
      mode,
      use_local_api: useLocal,
      ...(planning ? { planning_only: true } : {}),
      ...(report
        ? { report_id: report.id, expected_version: report.version }
        : {}),
    });
    if (attempt.current?.payload !== payload)
      attempt.current = { payload, key: crypto.randomUUID() };
    lock.current = true;
    setBusy(true);
    onSaving(true);
    setError("");
    try {
      const run = await api<AgentRun>("/runs", workspace, {
        method: "POST",
        headers: { "Idempotency-Key": attempt.current.key },
        body: payload,
      });
      if (!mounted.current) return;
      onDirty(false);
      onStarted(run);
    } catch (reason) {
      if (mounted.current) setError(message(reason));
    } finally {
      lock.current = false;
      onSaving(false);
      if (mounted.current) setBusy(false);
    }
  };
  return (
    <section className="card cooperation-composer">
      <div className="heading-with-icon">
        <Sparkles size={20} />
        <h2>
          {planning
            ? "选择材料，让团队先提出汇报方案"
            : "告诉协作团队，你需要什么报告"}
        </h2>
      </div>
      <p className="field-hint">
        {planning
          ? "先由需求经理和规划专员提出主题、大纲、材料依据及缺口；你确认后才开始整理数据和撰写。跨部门、跨期间也可以规划，系统会列出综合汇编及各组方向。"
          : "需求经理会先理解这段话，确认主题、部门与期间，再交给其余角色。缺少信息时会明确提示，不会替你编造。"}
      </p>
      {error && (
        <div className="notice error" role="alert">
          {error}
        </div>
      )}
      <form onSubmit={submit}>
        <fieldset disabled={busy} className="cooperation-fields">
          <legend className="sr-only">提交五角色协作任务</legend>
          <label className="field">
            {planning ? "汇报要求（可选）" : "汇报需求"}
            <textarea
              required={!planning}
              maxLength={8000}
              rows={6}
              value={userText}
              onChange={(event) => setUserText(event.target.value)}
              placeholder={
                planning
                  ? "例如：整理近期交付情况，或按月对比工作进展。留空时，由模型根据材料提出主题、期间和大纲。"
                  : "例如：请根据所选材料生成技术部2026年第二季度工作汇报，包含项目进度、成果、考勤样本、问题和下季度计划。"
              }
            />
          </label>
          <div className="cooperation-material-header">
            <h3>使用哪些材料</h3>
            <button
              className="text-button"
              type="button"
              disabled={loading || !selected.length}
              onClick={() => setSelected([])}
            >
              取消全部选择
            </button>
            <button
              className="text-button"
              type="button"
              disabled={loading}
              onClick={() => setRefresh((value) => value + 1)}
            >
              <RefreshCw size={14} />
              刷新材料
            </button>
          </div>
          {loading ? (
            <p className="field-hint" role="status">
              正在读取已确认材料…
            </p>
          ) : materials.length ? (
            <>
              <p className="field-hint">
                {planning
                  ? "请选择需要分析的文件，最多50份；文字说明可单独生成文字汇报。相同名称和分类只选一份。"
                  : "已预选每个同名、同类材料的最新文件，可取消或调整；最多50份。文字说明也可作为业务依据。"}
              </p>
              <div className="cooperation-materials">
                {materials.map((item) => (
                  <label key={item.id}>
                    <input
                      type="checkbox"
                      checked={selected.includes(item.id)}
                      disabled={
                        selected.length >= 50 && !selected.includes(item.id)
                      }
                      onChange={() =>
                        setSelected((previous) =>
                          previous.includes(item.id)
                            ? previous.filter((id) => id !== item.id)
                            : [...previous, item.id],
                        )
                      }
                    />
                    <span>
                      {item.name}
                      <small>
                        {item.department ? `${item.department} · ` : ""}
                        {item.row_count} 条记录 ·{" "}
                        {new Date(item.created_at).toLocaleDateString("zh-CN")}
                      </small>
                    </span>
                  </label>
                ))}
              </div>
            </>
          ) : (
            <p className="field-hint">
              尚无已确认材料。可以先提交需求；缺少依据时，团队会提示补充。也可以先到材料库导入文件。
            </p>
          )}
          {!planning && (
            <label className="cooperation-local">
              <input
                type="checkbox"
                checked={useLocal}
                onChange={(event) => setUseLocal(event.target.checked)}
              />
              <span>
                使用系统本地样例数据（虚构）
                <small>
                  季度办公案例：12个项目、1560条考勤、42项成果；行政案例216条反馈。请取消无关旧材料。
                </small>
              </span>
            </label>
          )}
          <div className="cooperation-submit">
            <label className="field">
              执行模式
              <select
                value={mode}
                onChange={(event) => setMode(event.target.value as RunMode)}
              >
                <option value="live">真实模型协作</option>
                <option value="offline_mock">离线模拟（不调用模型）</option>
              </select>
            </label>
            <button
              className="button primary"
              type="submit"
              disabled={
                busy ||
                loading ||
                (planning ? !selected.length : !userText.trim()) ||
                (mode === "live" && !system?.model_configured)
              }
            >
              {busy ? (
                <Loader2 className="spin" size={17} />
              ) : (
                <Sparkles size={17} />
              )}{" "}
              {busy
                ? "正在创建协作任务…"
                : planning
                  ? "生成汇报方案"
                  : "开始协作"}
            </button>
          </div>
          {mode === "offline_mock" ? (
            <p className="field-hint">
              离线模拟用于验证五角色调度与审核流程，输出不代表真实模型生成。
            </p>
          ) : (
            <p className="field-hint">
              {system?.model_configured
                ? "真实模式会使用服务端配置的模型并消耗 API token；每次运行受服务端预算限制。"
                : "模型连接尚未就绪。请到系统设置查看配置状态；也可手动选择离线模拟。"}
            </p>
          )}
        </fieldset>
      </form>
    </section>
  );
}

export function RunHistory({
  workspace,
  reportId,
  navigate,
}: {
  workspace: Workspace;
  reportId?: string;
  navigate: (path: string) => void;
}) {
  const [items, setItems] = useState<AgentRun[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [refresh, setRefresh] = useState(0);
  const [page, setPage] = useState(1);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    api<{ items: AgentRun[] }>(
      `/runs?summary=true${reportId ? `&report_id=${encodeURIComponent(reportId)}` : ""}`,
      workspace,
      { signal: controller.signal },
    )
      .then(({ items }) => {
        if (!controller.signal.aborted) setItems(items);
      })
      .catch((reason) => {
        if (!controller.signal.aborted) setError(message(reason));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [workspace, reportId, refresh]);
  return (
    <details className="card cooperation-history">
      <summary>执行历史 · {items.length} 次</summary>
      <div className="cooperation-material-header">
        <h3>本报告的执行过程</h3>
        <button
          className="text-button"
          type="button"
          disabled={loading}
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
      {loading ? (
        <p className="field-hint" role="status">
          正在读取运行记录…
        </p>
      ) : !items.length ? (
        <p className="field-hint">
          尚无协作运行。提交需求后可在这里找回过程与结果。
        </p>
      ) : (
        <div className="cooperation-history-list">
          {items
            .slice(
              (Math.min(page, Math.max(1, Math.ceil(items.length / 5))) - 1) *
                5,
              Math.min(page, Math.max(1, Math.ceil(items.length / 5))) * 5,
            )
            .map((item) => (
              <button
                key={item.id}
                onClick={() => navigate(`/runs/${item.id}`)}
              >
                <span>
                  <strong>
                    {item.request?.planning_only
                      ? `${item.requirements?.title || item.user_text}（材料方案）`
                      : item.user_text}
                  </strong>
                  <small>
                    {item.mode === "offline_mock" ? "离线模拟" : "真实模型"} ·{" "}
                    {item.created_at
                      ? time(item.created_at)
                      : item.id.slice(0, 8)}
                  </small>
                </span>
                <span className="status-badge">
                  {statusLabels[item.status]}
                </span>
                <ArrowRight size={16} />
              </button>
            ))}
        </div>
      )}
      {items.length > 5 && (
        <div className="task-pagination">
          <button
            className="button secondary"
            disabled={page <= 1}
            onClick={() => setPage((value) => value - 1)}
          >
            上一页
          </button>
          <span>
            第 {Math.min(page, Math.ceil(items.length / 5))} /{" "}
            {Math.ceil(items.length / 5)} 页
          </span>
          <button
            className="button secondary"
            disabled={page >= Math.ceil(items.length / 5)}
            onClick={() => setPage((value) => value + 1)}
          >
            下一页
          </button>
        </div>
      )}
    </details>
  );
}

export function RunDetail({
  id,
  workspace,
  navigate,
  changed,
  onDirty,
  onSaving,
}: {
  id: string;
  workspace: Workspace;
  navigate: (path: string) => void;
  changed: () => void;
  onDirty: (value: boolean) => void;
  onSaving: (value: boolean) => void;
}) {
  const [run, setRun] = useState<AgentRun | null>(null);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [cancelling, setCancelling] = useState(false);
  const [tab, setTab] = useState("report");
  const active = useRef(false);
  const cancelLock = useRef(false);
  useEffect(() => {
    active.current = true;
    let stopped = false;
    let timer: number | undefined;
    let terminalNotified = false;
    const controller = new AbortController();
    const poll = async () => {
      try {
        const result = await api<AgentRun>(
          `/runs/${encodeURIComponent(id)}`,
          workspace,
          { signal: controller.signal },
        );
        if (stopped) return;
        setRun(result);
        setError("");
        if (terminal(result.status)) {
          if (!terminalNotified) {
            terminalNotified = true;
            changed();
          }
          return;
        }
      } catch (reason) {
        if (stopped) return;
        setError(message(reason));
        if (reason instanceof ApiError && [403, 404].includes(reason.status))
          return;
      }
      if (!stopped) timer = window.setTimeout(poll, 2000);
    };
    void poll();
    return () => {
      stopped = true;
      active.current = false;
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [id, workspace, refresh, changed]);
  const cancel = async () => {
    if (cancelLock.current) return;
    cancelLock.current = true;
    setCancelling(true);
    setError("");
    try {
      const result = await api<AgentRun>(
        `/runs/${encodeURIComponent(id)}/cancel`,
        workspace,
        { method: "POST" },
      );
      if (active.current) setRun(result);
    } catch (reason) {
      if (active.current) setError(message(reason));
    } finally {
      cancelLock.current = false;
      if (active.current) setCancelling(false);
    }
  };
  const completedRoles = new Set(
    run?.nodes
      .filter((node) => node.status === "completed")
      .map((node) => node.role.toLowerCase()),
  );
  return (
    <>
      <button className="back-link" onClick={() => navigate("/reports")}>
        <ArrowLeft size={15} />
        报告任务
      </button>
      <div className="page-heading">
        <div>
          <div className="eyebrow">AGENT COOPERATION</div>
          <h1>
            {run?.request?.planning_only && !run.plan_confirmation
              ? "汇报方案"
              : "五角色协作"}
          </h1>
          <p>需求分析 → 内容规划 → 数据整理 → 报告撰写 → 审核校验 → 经理验收</p>
        </div>
        {run && (
          <span className="status-badge">{statusLabels[run.status]}</span>
        )}
      </div>
      {error && (
        <div className="notice error" role="alert">
          <span>{error}</span>
          <button
            className="text-button"
            onClick={() => setRefresh((value) => value + 1)}
          >
            重新连接
          </button>
        </div>
      )}
      {!run ? (
        !error && (
          <div className="loading-panel" role="status">
            <Loader2 size={20} className="spin" />
            正在读取协作任务…
          </div>
        )
      ) : (
        <>
          <section className="card cooperation-summary">
            <div className="cooperation-run-meta">
              <span
                className={`status-badge ${run.mode === "offline_mock" ? "cooperation-mock" : ""}`}
              >
                {run.mode === "offline_mock"
                  ? "离线模拟 · 无外部模型调用"
                  : "真实模型协作"}
              </span>
              <span className="field-hint">任务 {run.id.slice(0, 8)}</span>
            </div>
            <p className="cooperation-request">{run.user_text}</p>
            <ol className="cooperation-stages">
              {Object.entries(roleLabels).map(([role, label]) => {
                const current =
                  run.stage?.toLowerCase().includes(role) &&
                  !terminal(run.status);
                const done = completedRoles.has(role);
                return (
                  <li
                    key={role}
                    className={current ? "current" : done ? "done" : ""}
                  >
                    {current ? (
                      <Loader2 size={19} className="spin" />
                    ) : done ? (
                      <Check size={19} />
                    ) : (
                      <Circle size={19} />
                    )}
                    <span>
                      {label}
                      <small>
                        {current
                          ? "正在处理"
                          : done
                            ? "已有节点结果"
                            : run.status === "awaiting_confirmation"
                              ? "待确认方案后执行"
                              : "等待结果"}
                      </small>
                    </span>
                  </li>
                );
              })}
            </ol>
            {run.error && (
              <div className="notice error" role="alert">
                <TriangleAlert size={17} />
                <span>
                  {run.error.message}（{run.error.code}）
                </span>
              </div>
            )}
            {run.status === "needs_input" && (
              <div className="notice">
                <div>
                  <strong>请补充信息后重新提交</strong>
                  {run.missing_fields?.length > 0 && (
                    <p>缺少：{run.missing_fields.join("、")}</p>
                  )}
                  {run.questions?.map((question, index) => (
                    <p key={index}>{question}</p>
                  ))}
                  <button
                    className="text-button"
                    onClick={() =>
                      navigate(
                        run.request?.planning_only
                          ? `/reports/plan?${new URLSearchParams((run.material_ids || []).map((id) => ["material", id]))}`
                          : "/reports/new",
                      )
                    }
                  >
                    {run.request?.planning_only
                      ? "返回调整材料"
                      : "返回提交需求"}
                    <ArrowRight size={14} />
                  </button>
                </div>
              </div>
            )}
            {run.status === "awaiting_confirmation" && (
              <MaterialPlanReview
                key={run.plan_hash}
                run={run}
                workspace={workspace}
                onDirty={onDirty}
                onSaving={onSaving}
                onConfirmed={(result) => {
                  setRun(result);
                  setRefresh((value) => value + 1);
                  changed();
                }}
                onDeclined={cancel}
                declining={cancelling}
              />
            )}
            <div className="cooperation-run-actions">
              {run.report_id && (
                <button
                  className="button secondary"
                  onClick={() => navigate(`/reports/${run.report_id}`)}
                >
                  打开关联报告
                  <ArrowRight size={15} />
                </button>
              )}
              {!terminal(run.status) && (
                <>
                  <button
                    className="button secondary"
                    onClick={cancel}
                    disabled={cancelling || run.cancel_requested}
                  >
                    {cancelling ? (
                      <Loader2 size={15} className="spin" />
                    ) : (
                      <Square size={14} />
                    )}{" "}
                    {run.cancel_requested ? "已请求取消" : "取消运行"}
                  </button>
                  <span className="field-hint">
                    取消将在安全节点生效；已发出的模型请求仍可能计费。
                  </span>
                </>
              )}
            </div>
            {run.usage && (
              <details className="cooperation-usage">
                <summary>调用与预算</summary>
                <dl>
                  <div>
                    <dt>模型调用</dt>
                    <dd>
                      {run.usage.request_count} / {run.usage.request_budget}
                    </dd>
                  </div>
                  <div>
                    <dt>离线模拟调用</dt>
                    <dd>{run.usage.mock_calls}</dd>
                  </div>
                  <div>
                    <dt>总 token</dt>
                    <dd>{run.usage.total_tokens ?? "服务商未提供"}</dd>
                  </div>
                  <div>
                    <dt>输出预算预留（非实际用量）</dt>
                    <dd>
                      {run.usage.reserved_output_tokens} /{" "}
                      {run.usage.output_budget}
                    </dd>
                  </div>
                </dl>
              </details>
            )}
          </section>
          <section className="card cooperation-work">
            <div className="cooperation-tabs" aria-label="运行结果视图">
              {[
                ["report", "报告预览"],
                ["review", "审核与返工"],
                ["nodes", "节点输入输出"],
                ["events", "协作时间线"],
              ].map(([key, label]) => (
                <button
                  type="button"
                  key={key}
                  aria-pressed={tab === key}
                  className={tab === key ? "active" : ""}
                  onClick={() => setTab(key)}
                >
                  {label}
                </button>
              ))}
            </div>
            <div hidden={tab !== "report"} className="cooperation-panel">
              <h2>报告内容</h2>
              {run.status === "completed" && run.report_id ? (
                <Delivery
                  reportId={run.report_id}
                  workspace={workspace}
                  onDirty={onDirty}
                  onSaving={onSaving}
                  navigate={navigate}
                  onChanged={changed}
                />
              ) : run.draft_markdown ? (
                <>
                  <p className="field-hint">
                    {run.status === "completed"
                      ? "已通过本次协作验收。"
                      : "当前为中间稿，请结合审核结果查看。"}
                    仅通过 Checker 与 Manager 验收的报告可作为合格文件交付。
                  </p>
                  <pre className="cooperation-markdown">
                    {run.draft_markdown}
                  </pre>
                </>
              ) : (
                <p className="field-hint">
                  报告尚未生成。可以先查看协作时间线和节点结果。
                </p>
              )}
              {run.outline != null && (
                <details className="cooperation-object">
                  <summary>规划大纲</summary>
                  <pre>{text(run.outline)}</pre>
                </details>
              )}
            </div>
            <div hidden={tab !== "review"} className="cooperation-panel">
              <h2>审核与返工</h2>
              {run.acceptance != null && (
                <section className="cooperation-acceptance">
                  <h3>Manager 最终验收</h3>
                  <pre>{text(run.acceptance)}</pre>
                </section>
              )}
              {run.review != null && (
                <details open className="cooperation-object">
                  <summary>最新审核</summary>
                  <pre>{text(run.review)}</pre>
                </details>
              )}
              {run.revision_history?.length ? (
                run.revision_history.map((revision, index) => (
                  <details className="cooperation-object" key={index}>
                    <summary>审核 / 修改记录 {index + 1}</summary>
                    <pre>{text(revision)}</pre>
                  </details>
                ))
              ) : (
                <p className="field-hint">
                  暂无返工记录。审核未通过时，会在预算内退回 Writer 修改，再由
                  Checker 复审。
                </p>
              )}
            </div>
            <div hidden={tab !== "nodes"} className="cooperation-panel">
              <h2>节点输入与输出</h2>
              {run.nodes.length ? (
                run.nodes.map((node, index) => (
                  <details
                    className="cooperation-object"
                    key={`${node.role}-${node.revision}-${index}`}
                  >
                    <summary>
                      {roleLabels[node.role.toLowerCase()] || node.role} ·{" "}
                      {node.status}
                      {node.revision != null ? ` · 第 ${node.revision} 轮` : ""}
                    </summary>
                    <h3>输入</h3>
                    <pre>{text(node.inputs)}</pre>
                    <h3>输出</h3>
                    {node.status === "failed" &&
                      node.candidate_output != null && (
                        <p className="field-hint">
                          候选输出未通过业务校验，未作为有效结果使用。
                        </p>
                      )}
                    <pre>{text(node.output ?? node.candidate_output)}</pre>
                  </details>
                ))
              ) : (
                <p className="field-hint">尚无节点结果。</p>
              )}
            </div>
            <div hidden={tab !== "events"} className="cooperation-panel">
              <h2>协作时间线</h2>
              {run.events.length ? (
                <ol className="cooperation-events">
                  {run.events.map((event) => (
                    <li key={event.seq}>
                      <div>
                        <strong>
                          {roleLabels[event.role.toLowerCase()] || event.role}
                        </strong>
                        <span>{time(event.created_at)}</span>
                      </div>
                      <p>{event.message}</p>
                      <small>{event.event_type}</small>
                    </li>
                  ))}
                </ol>
              ) : (
                <p className="field-hint">任务已提交，等待开始执行。</p>
              )}
            </div>
          </section>
        </>
      )}
    </>
  );
}
