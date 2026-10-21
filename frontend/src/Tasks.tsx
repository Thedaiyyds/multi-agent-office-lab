import { useEffect, useRef, useState } from "react";
import {
  ArrowRight,
  FolderOpen,
  Loader2,
  Plus,
  RefreshCw,
  Search,
} from "lucide-react";
import { api, type Workspace } from "./api";

interface Task {
  id: string;
  title: string;
  department: string;
  start_date: string;
  end_date: string;
  updated_at: string;
  status: string;
  mode: string | null;
  report_id: string | null;
  run_count: number;
  has_report: boolean;
  href: string;
  hidden: boolean;
  attempts: { id: string; status: string; created_at: string }[];
}
const labels: Record<string, string> = {
  draft: "待生成",
  queued: "排队中",
  running: "生成中",
  awaiting_confirmation: "待确认方案",
  completed: "已完成",
  pending_review: "待审核",
  needs_changes: "需修改",
  review_failed: "需修改",
  failed: "执行失败",
  needs_input: "待补充信息",
  cancelled: "已取消",
  interrupted: "已中断",
};
const active = (status: string) =>
  ["queued", "running", "awaiting_confirmation"].includes(status);
const stamp = (time: string) =>
  new Date(time).toLocaleString("zh-CN", { hour12: false });

export default function Tasks({
  workspace,
  navigate,
  onSaving,
}: {
  workspace: Workspace;
  navigate: (path: string) => void;
  onSaving: (value: boolean) => void;
}) {
  const [data, setData] = useState<{ items: Task[]; attempts: Task[] }>({
    items: [],
    attempts: [],
  });
  const [loading, setLoading] = useState(true),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0),
    [search, setSearch] = useState(""),
    [filter, setFilter] = useState("all"),
    [mode, setMode] = useState("all");
  const [showHidden, setShowHidden] = useState(false),
    [selected, setSelected] = useState<string[]>([]),
    [page, setPage] = useState(1),
    [historyPage, setHistoryPage] = useState(1);
  const alive = useRef(true),
    lock = useRef(false);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      onSaving(false);
    };
  }, [onSaving]);
  useEffect(() => {
    const controller = new AbortController();
    let timer: number | undefined;
    setLoading(true);
    const poll = async () => {
      try {
        const result = await api<typeof data>("/tasks", workspace, {
          signal: controller.signal,
        });
        if (controller.signal.aborted) return;
        setData(result);
        setError("");
        if (result.items.some((item) => active(item.status)))
          timer = window.setTimeout(poll, 2500);
      } catch (reason) {
        if (!controller.signal.aborted)
          setError(
            reason instanceof Error ? reason.message : "任务列表读取失败",
          );
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    };
    void poll();
    return () => {
      controller.abort();
      if (timer) clearTimeout(timer);
    };
  }, [workspace, refresh]);
  useEffect(() => {
    setPage(1);
    setHistoryPage(1);
    setSelected([]);
  }, [search, filter, mode, showHidden]);
  const matches = (task: Task) =>
    (showHidden || !task.hidden) &&
    (mode === "all" || task.mode === mode) &&
    (filter === "all" ||
      (filter === "active" && active(task.status)) ||
      (filter === "done" && task.status === "completed") ||
      (filter === "attention" &&
        !active(task.status) &&
        task.status !== "completed")) &&
    `${task.title} ${task.department}`
      .toLowerCase()
      .includes(search.trim().toLowerCase());
  const items = data.items.filter(matches),
    attempts = data.attempts.filter(matches);
  const currentPage = Math.min(page, Math.max(1, Math.ceil(items.length / 10)));
  const currentHistoryPage = Math.min(
    historyPage,
    Math.max(1, Math.ceil(attempts.length / 5)),
  );
  const allTasks = [...data.items, ...data.attempts];
  const toggle = (id: string) =>
    setSelected((previous) =>
      previous.includes(id)
        ? previous.filter((value) => value !== id)
        : [...previous, id].slice(0, 100),
    );
  const visibility = async (hidden: boolean) => {
    if (lock.current || !selected.length) return;
    lock.current = true;
    setBusy(true);
    onSaving(true);
    setError("");
    try {
      await api("/tasks/visibility", workspace, {
        method: "POST",
        body: JSON.stringify({ ids: selected, hidden }),
      });
      if (alive.current) {
        setSelected([]);
        setRefresh((value) => value + 1);
      }
    } catch (reason) {
      if (alive.current)
        setError(reason instanceof Error ? reason.message : "任务整理失败");
    } finally {
      lock.current = false;
      onSaving(false);
      if (alive.current) setBusy(false);
    }
  };
  const row = (task: Task) => (
    <div className={`task-row ${task.hidden ? "is-hidden" : ""}`} key={task.id}>
      <input
        type="checkbox"
        aria-label={`选择任务 ${task.title}`}
        checked={selected.includes(task.id)}
        disabled={busy || active(task.status)}
        onChange={() => toggle(task.id)}
      />
      <button
        className="task-open"
        onClick={() => navigate(task.href)}
        disabled={busy}
      >
        <FolderOpen size={21} />
        <span>
          <strong>{task.title}</strong>
          <small>
            {task.department}
            {task.start_date
              ? ` · ${task.start_date} 至 ${task.end_date}（不含）`
              : ""}
          </small>
          <small>
            {stamp(task.updated_at)} ·{" "}
            {task.mode === "offline_mock"
              ? "离线测试"
              : task.mode === "live"
                ? "真实模型"
                : "尚未执行"}
            {task.run_count > 1 ? ` · ${task.run_count} 次执行` : ""}
            {task.hidden ? " · 已收起" : ""}
            {task.has_report && task.status !== "completed"
              ? " · 有报告结果可查看"
              : ""}
          </small>
        </span>
        <span
          className={`status-badge ${task.status === "completed" ? "approved" : ""}`}
        >
          {labels[task.status] || task.status}
        </span>
        <ArrowRight size={16} />
      </button>
      {!task.report_id && task.attempts.length > 1 && (
        <details className="task-attempts">
          <summary>查看 {task.attempts.length} 次尝试</summary>
          <div>
            {task.attempts.map((run) => (
              <button
                key={run.id}
                className="text-button"
                onClick={() => navigate(`/runs/${run.id}`)}
              >
                {stamp(run.created_at)} · {labels[run.status] || run.status}
              </button>
            ))}
          </div>
        </details>
      )}
    </div>
  );
  const pager = (
    number: number,
    total: number,
    size: number,
    set: (value: number) => void,
  ) => (
    <div className="task-pagination">
      <button
        className="button secondary"
        disabled={number <= 1}
        onClick={() => set(number - 1)}
      >
        上一页
      </button>
      <span>
        第 {number} / {Math.max(1, Math.ceil(total / size))} 页 · {total} 项
      </span>
      <button
        className="button secondary"
        disabled={number >= Math.ceil(total / size)}
        onClick={() => set(number + 1)}
      >
        下一页
      </button>
    </div>
  );
  return (
    <>
      <div className="page-heading">
        <div>
          <div className="eyebrow">REPORT TASKS</div>
          <h1>报告任务</h1>
          <p>每份报告保留一个入口，执行过程和历史记录在任务内查看。</p>
        </div>
        <div className="report-heading-actions">
          <button
            className="button secondary"
            onClick={() => navigate("/materials")}
          >
            从材料规划
          </button>
          <button
            className="button primary"
            onClick={() => navigate("/reports/new")}
          >
            <Plus size={17} />
            新建报告
          </button>
        </div>
      </div>
      {error && (
        <div className="notice error" role="alert">
          {error}
        </div>
      )}
      <section className="card task-list">
        <div className="list-toolbar">
          <label className="search-field">
            <Search size={17} />
            <span className="sr-only">搜索任务标题或部门</span>
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="搜索任务标题或部门"
            />
          </label>
          <select
            aria-label="按任务状态筛选"
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
          >
            <option value="all">全部状态</option>
            <option value="active">处理中</option>
            <option value="done">已完成</option>
            <option value="attention">需处理</option>
          </select>
          <select
            aria-label="按执行模式筛选"
            value={mode}
            onChange={(event) => setMode(event.target.value)}
          >
            <option value="all">全部模式</option>
            <option value="live">真实模型</option>
            <option value="offline_mock">离线测试</option>
          </select>
          <label className="material-history-toggle">
            <input
              type="checkbox"
              checked={showHidden}
              onChange={(event) => setShowHidden(event.target.checked)}
            />
            显示已收起
          </label>
          <button
            className="icon-button"
            aria-label="刷新任务列表"
            disabled={loading || busy}
            onClick={() => setRefresh((value) => value + 1)}
          >
            <RefreshCw size={17} className={loading ? "spin" : ""} />
          </button>
        </div>
        {selected.length > 0 && (
          <div className="task-bulk">
            <span>已选择 {selected.length} 项</span>
            <button
              className="button secondary"
              disabled={
                busy ||
                selected.some(
                  (id) => allTasks.find((task) => task.id === id)?.hidden,
                )
              }
              onClick={() => visibility(true)}
            >
              收起所选任务
            </button>
            <button
              className="button secondary"
              disabled={
                busy ||
                selected.some(
                  (id) => !allTasks.find((task) => task.id === id)?.hidden,
                )
              }
              onClick={() => visibility(false)}
            >
              恢复所选任务
            </button>
            <button
              className="text-button"
              onClick={() => setSelected([])}
              disabled={busy}
            >
              取消选择
            </button>
          </div>
        )}
        {loading && !data.items.length ? (
          <div className="loading-panel" role="status">
            <Loader2 size={22} className="spin" />
            正在读取任务…
          </div>
        ) : items.length ? (
          items.slice((currentPage - 1) * 10, currentPage * 10).map(row)
        ) : (
          <div className="empty-state compact">
            <h3>没有匹配的报告任务</h3>
            <p>可以调整筛选，或从材料规划一份新报告。</p>
          </div>
        )}
        {items.length > 10 && pager(currentPage, items.length, 10, setPage)}
        <p className="material-history-note">
          收起仅整理当前列表，报告文件和执行证据保留，可随时恢复；任务有新进展时会重新显示。
        </p>
      </section>
      {attempts.length > 0 && (
        <details className="card task-unfinished">
          <summary>
            未成稿尝试 ·{" "}
            {attempts.reduce((count, task) => count + task.run_count, 0)}{" "}
            次，合并为 {attempts.length} 项
          </summary>
          <p className="field-hint">
            未形成报告的补充信息、失败或取消记录统一放在这里，重复提交合并展示。
          </p>
          {attempts
            .slice((currentHistoryPage - 1) * 5, currentHistoryPage * 5)
            .map(row)}
          {attempts.length > 5 &&
            pager(currentHistoryPage, attempts.length, 5, setHistoryPage)}
        </details>
      )}
    </>
  );
}
