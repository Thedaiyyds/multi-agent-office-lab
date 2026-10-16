import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import {
  Archive,
  ArrowLeft,
  ArrowRight,
  Check,
  ChevronRight,
  CircleHelp,
  Clock3,
  FileCheck2,
  FilePlus2,
  FileText,
  FolderOpen,
  LayoutDashboard,
  Loader2,
  Menu,
  Plus,
  RefreshCw,
  Save,
  Search,
  Settings2,
  ShieldCheck,
  Upload,
  X,
} from "lucide-react";
import {
  api,
  ApiError,
  type Draft,
  type Report,
  type SystemInfo,
  type Workspace,
} from "./api";
import { useConfirmation, type Confirm } from "./confirm";
import Materials, { DemoMaterials } from "./Materials";
import Statistics from "./Statistics";

const nav = [
  { path: "/", label: "工作台", icon: LayoutDashboard },
  { path: "/reports", label: "报告任务", icon: FileText },
  { path: "/materials", label: "材料库", icon: FolderOpen },
  { path: "/archive", label: "报告归档", icon: Archive },
];
const initialDraft = (): Draft => ({
  title: "",
  department: "",
  start_date: "",
  end_date: "",
  focus: "",
  sections: ["工作概述", "重点工作", "问题与计划"],
});
const route = () => window.location.hash.slice(1) || "/";
const dateTime = (date: string) => {
  const parsed = new Date(date);
  return Number.isNaN(parsed.getTime())
    ? "时间未知"
    : new Intl.DateTimeFormat("zh-CN", {
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      }).format(parsed);
};
const message = (error: unknown) =>
  error instanceof Error ? error.message : "操作暂未成功，请重试。";

function Notice({
  children,
  kind = "info",
  action,
}: {
  children: ReactNode;
  kind?: "info" | "error" | "success";
  action?: ReactNode;
}) {
  return (
    <div
      className={`notice ${kind}`}
      role={kind === "error" ? "alert" : "status"}
    >
      <span>{children}</span>
      {action}
    </div>
  );
}

function EmptyState({
  icon: Icon = FileText,
  title,
  description,
  children,
  compact = false,
}: {
  icon?: typeof FileText;
  title: string;
  description: string;
  children?: ReactNode;
  compact?: boolean;
}) {
  return (
    <div className={`empty-state ${compact ? "compact" : ""}`}>
      <div className="empty-icon">
        <Icon size={compact ? 23 : 30} strokeWidth={1.5} />
      </div>
      <h3>{title}</h3>
      <p>{description}</p>
      {children && <div className="empty-actions">{children}</div>}
    </div>
  );
}

function ReportRows({
  reports,
  open,
}: {
  reports: Report[];
  open: (id: string) => void;
}) {
  return (
    <div className="report-rows">
      {reports.map((report) => (
        <button
          className="report-row"
          key={report.id}
          onClick={() => open(report.id)}
        >
          <span className="document-icon">
            <FileText size={21} strokeWidth={1.7} />
          </span>
          <span className="report-row-content">
            <strong>{report.title}</strong>
            <span>
              {report.department}
              <span className="dot">·</span>
              {dateTime(report.updated_at)}
            </span>
          </span>
          <span className="status-badge">草稿</span>
          <ChevronRight size={17} className="muted" />
        </button>
      ))}
    </div>
  );
}

function Home({
  reports,
  loading,
  error,
  retry,
  navigate,
  system,
}: {
  reports: Report[];
  loading: boolean;
  error: string;
  retry: () => void;
  navigate: (path: string) => void;
  system: SystemInfo | null;
}) {
  return (
    <>
      <div className="page-heading">
        <div>
          <div className="eyebrow">YOUR WORKSPACE</div>
          <h1>让每一份汇报，有据可依。</h1>
          <p>从整理需求开始，逐步形成清晰、可信的工作汇报。</p>
        </div>
        <button
          className="button primary"
          onClick={() => navigate("/reports/new")}
        >
          <Plus size={18} />
          新建报告
        </button>
      </div>
      {system && !system.model_configured && (
        <Notice
          action={
            <button
              className="text-button"
              onClick={() => navigate("/settings")}
            >
              查看设置
              <ArrowRight size={14} />
            </button>
          }
        >
          模型连接尚未配置。你可以先创建并保存报告草稿。
        </Notice>
      )}
      {error ? (
        <Notice
          kind="error"
          action={
            <button className="text-button" onClick={retry}>
              重新连接
            </button>
          }
        >
          {error}
        </Notice>
      ) : loading ? (
        <div className="loading-panel" role="status">
          <Loader2 className="spin" size={22} />
          正在读取工作空间…
        </div>
      ) : (
        <>
          {reports.length === 0 ? (
            <section className="card welcome-card">
              <div className="welcome-lines" aria-hidden="true" />
              <EmptyState
                icon={FilePlus2}
                title="创建第一份工作汇报"
                description="先明确汇报主题与时间范围，保存草稿后随时回来继续。"
              >
                <button
                  className="button primary"
                  onClick={() => navigate("/reports/new")}
                >
                  <Plus size={17} />
                  新建报告
                </button>
                <button
                  className="button secondary"
                  onClick={() => navigate("/materials")}
                >
                  <Upload size={17} />
                  上传材料
                </button>
              </EmptyState>
              <div className="welcome-note">
                <ShieldCheck size={15} />
                报告保存在本地工作空间
              </div>
            </section>
          ) : (
            <section className="card continue-card">
              <div className="continue-icon">
                <FileCheck2 size={28} strokeWidth={1.5} />
              </div>
              <div>
                <h2>继续你的工作汇报</h2>
                <p>已保存的草稿可继续修改需求和章节安排。</p>
              </div>
              <button
                className="button secondary"
                onClick={() => navigate(`/reports/${reports[0].id}`)}
              >
                打开最近草稿
                <ArrowRight size={16} />
              </button>
            </section>
          )}
          <div className="dashboard-grid">
            <section className="card">
              <div className="card-heading">
                <div className="heading-with-icon">
                  <Clock3 size={18} />
                  <h2>待处理</h2>
                </div>
                {reports.length > 0 && (
                  <span className="count-badge">{reports.length}</span>
                )}
              </div>
              {reports.length === 0 ? (
                <EmptyState
                  compact
                  icon={Check}
                  title="暂无待处理事项"
                  description="新的报告草稿会出现在这里。"
                />
              ) : (
                <>
                  <div className="card-subtitle">可继续完善的草稿</div>
                  <ReportRows
                    reports={reports.slice(0, 3)}
                    open={(id) => navigate(`/reports/${id}`)}
                  />
                </>
              )}
            </section>
            <section className="card">
              <div className="card-heading">
                <div className="heading-with-icon">
                  <FileText size={18} />
                  <h2>最近报告</h2>
                </div>
                <button
                  className="text-button"
                  onClick={() => navigate("/reports")}
                >
                  查看全部
                  <ArrowRight size={14} />
                </button>
              </div>
              {reports.length === 0 ? (
                <EmptyState
                  compact
                  title="尚未创建报告"
                  description="你的报告和最近修改会保留在这里。"
                />
              ) : (
                <ReportRows
                  reports={reports.slice(0, 4)}
                  open={(id) => navigate(`/reports/${id}`)}
                />
              )}
            </section>
          </div>
        </>
      )}
      <div className="workspace-caption">
        <span className="caption-dot" />
        本地工作空间<span>草稿随时保存，回来继续处理</span>
      </div>
    </>
  );
}

function ReportList({
  reports,
  loading,
  error,
  retry,
  navigate,
}: {
  reports: Report[];
  loading: boolean;
  error: string;
  retry: () => void;
  navigate: (path: string) => void;
}) {
  const [search, setSearch] = useState("");
  const filtered = reports.filter((report) =>
    `${report.title} ${report.department}`
      .toLocaleLowerCase()
      .includes(search.toLocaleLowerCase()),
  );
  return (
    <>
      <div className="page-heading">
        <div>
          <div className="eyebrow">REPORTS</div>
          <h1>报告任务</h1>
          <p>查找并继续处理已保存的工作汇报。</p>
        </div>
        <button
          className="button primary"
          onClick={() => navigate("/reports/new")}
        >
          <Plus size={18} />
          新建报告
        </button>
      </div>
      <section className="card">
        <div className="list-toolbar">
          <label className="search-field">
            <Search size={18} />
            <span className="sr-only">搜索报告标题或部门</span>
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="搜索报告标题或部门"
            />
          </label>
          <span className="list-count">{filtered.length} 份草稿</span>
          <button
            className="icon-button"
            onClick={retry}
            disabled={loading}
            aria-label="刷新报告列表"
          >
            <RefreshCw size={17} className={loading ? "spin" : ""} />
          </button>
        </div>
        {error ? (
          <div className="panel-padding">
            <Notice
              kind="error"
              action={
                <button className="text-button" onClick={retry}>
                  重试
                </button>
              }
            >
              {error}
            </Notice>
          </div>
        ) : loading ? (
          <div className="loading-panel" role="status">
            <Loader2 className="spin" size={22} />
            正在读取报告…
          </div>
        ) : filtered.length ? (
          <ReportRows
            reports={filtered}
            open={(id) => navigate(`/reports/${id}`)}
          />
        ) : (
          <EmptyState
            title={search ? "没有匹配的报告" : "从一份新报告开始"}
            description={
              search
                ? "尝试其他标题或部门名称。"
                : "填写主题和期间，将想法保存为可继续完善的草稿。"
            }
          >
            {!search && (
              <button
                className="button primary"
                onClick={() => navigate("/reports/new")}
              >
                <Plus size={17} />
                新建报告
              </button>
            )}
          </EmptyState>
        )}
      </section>
    </>
  );
}

function DraftForm({
  report,
  workspace,
  onSaved,
  onDirty,
  onSaving,
  refresh,
}: {
  report?: Report;
  workspace: Workspace;
  onSaved: (report: Report) => void;
  onDirty: (dirty: boolean) => void;
  onSaving: (saving: boolean) => void;
  refresh?: () => void;
}) {
  const [draft, setDraft] = useState<Draft>(() =>
    report
      ? {
          title: report.title,
          department: report.department,
          start_date: report.start_date,
          end_date: report.end_date,
          focus: report.focus,
          sections: [...report.sections],
        }
      : initialDraft(),
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [conflict, setConflict] = useState(false);
  const [saved, setSaved] = useState(false);
  const [baseline, setBaseline] = useState(() => JSON.stringify(draft));
  const dirty = JSON.stringify(draft) !== baseline;
  const lock = useRef(false);
  const createAttempt = useRef<{ payload: string; key: string } | null>(null);
  const mounted = useRef(true);
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
  const update = <K extends keyof Draft>(field: K, value: Draft[K]) => {
    setDraft((previous) => ({ ...previous, [field]: value }));
    setSaved(false);
    if (!conflict) setError("");
  };
  const save = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (lock.current || conflict) return;
    if (!draft.title.trim() || !draft.department.trim()) {
      setError("请填写报告标题和所属部门，内容不能只有空格。");
      return;
    }
    if (
      new Set(draft.sections.map((section) => section.trim())).size !==
      draft.sections.length
    ) {
      setError("章节名称不能重复，请为每个章节填写不同的名称。");
      return;
    }
    if (draft.end_date <= draft.start_date) {
      setError("结束日期须晚于开始日期。结束日不计入本次报告期间。");
      return;
    }
    if (
      !draft.sections.length ||
      draft.sections.some((section) => !section.trim())
    ) {
      setError("请至少保留一个章节，并填写所有章节名称。");
      return;
    }
    lock.current = true;
    onSaving(true);
    setSaving(true);
    setError("");
    setSaved(false);
    try {
      const payload = {
        ...draft,
        title: draft.title.trim(),
        department: draft.department.trim(),
        focus: draft.focus.trim(),
        sections: draft.sections.map((section) => section.trim()),
      };
      const canonicalPayload = JSON.stringify(payload);
      if (!report && createAttempt.current?.payload !== canonicalPayload)
        createAttempt.current = {
          payload: canonicalPayload,
          key: crypto.randomUUID(),
        };
      const result = await api<Report>(
        report ? `/reports/${report.id}/draft` : "/reports",
        workspace,
        {
          method: report ? "PATCH" : "POST",
          headers: report
            ? undefined
            : { "Idempotency-Key": createAttempt.current!.key },
          body: JSON.stringify(
            report ? { ...payload, expected_version: report.version } : payload,
          ),
        },
      );
      createAttempt.current = null;
      if (!mounted.current) return;
      setDraft({
        title: result.title,
        department: result.department,
        start_date: result.start_date,
        end_date: result.end_date,
        focus: result.focus,
        sections: result.sections,
      });
      setBaseline(
        JSON.stringify({
          title: result.title,
          department: result.department,
          start_date: result.start_date,
          end_date: result.end_date,
          focus: result.focus,
          sections: result.sections,
        }),
      );
      onDirty(false);
      setSaved(true);
      onSaved(result);
    } catch (reason) {
      if (mounted.current) {
        setError(message(reason));
        setConflict(reason instanceof ApiError && reason.status === 409);
      }
    } finally {
      lock.current = false;
      onSaving(false);
      if (mounted.current) setSaving(false);
    }
  };
  return (
    <form onSubmit={save}>
      <fieldset disabled={saving} className="draft-layout">
        <div className="draft-main">
          <section className="card form-card">
            <div className="form-section-heading">
              <span className="section-number">01</span>
              <div>
                <h2>主题与范围</h2>
                <p>明确这份报告写给谁、覆盖哪些工作。</p>
              </div>
            </div>
            <div className="form-fields">
              <label className="field">
                报告标题<span className="required-label">必填</span>
                <input
                  required
                  maxLength={160}
                  value={draft.title}
                  onChange={(event) => update("title", event.target.value)}
                  placeholder="填写这份工作汇报的标题"
                  autoFocus={!report}
                />
              </label>
              <label className="field">
                所属部门<span className="required-label">必填</span>
                <input
                  required
                  maxLength={80}
                  value={draft.department}
                  onChange={(event) => update("department", event.target.value)}
                  placeholder="填写部门名称"
                />
              </label>
              <div className="date-fields">
                <label className="field">
                  开始日期<span className="required-label">必填</span>
                  <input
                    type="date"
                    required
                    value={draft.start_date}
                    onChange={(event) =>
                      update("start_date", event.target.value)
                    }
                  />
                </label>
                <label className="field">
                  结束日期<span className="required-label">不含当日</span>
                  <input
                    type="date"
                    required
                    value={draft.end_date}
                    onChange={(event) => update("end_date", event.target.value)}
                  />
                </label>
              </div>
              <p className="field-hint">
                报告期间包含开始日，不包含结束日。例如覆盖 1 月至 3
                月，结束日期请选择 4 月 1 日。
              </p>
              <label className="field">
                汇报重点<span className="optional-label">选填</span>
                <textarea
                  rows={4}
                  maxLength={4000}
                  value={draft.focus}
                  onChange={(event) => update("focus", event.target.value)}
                  placeholder="希望突出哪些工作？有哪些需要说明的问题或读者关心的内容？"
                />
              </label>
            </div>
          </section>
          <section className="card form-card">
            <div className="form-section-heading">
              <span className="section-number">02</span>
              <div>
                <h2>章节安排</h2>
                <p>以下为通用结构建议，可按需要调整；至少保留一章。</p>
              </div>
            </div>
            <div className="chapter-list">
              {draft.sections.map((section, index) => (
                <div className="chapter-row" key={index}>
                  <span className="chapter-number">
                    {String(index + 1).padStart(2, "0")}
                  </span>
                  <label className="chapter-input">
                    <span className="sr-only">第 {index + 1} 章名称</span>
                    <input
                      required
                      maxLength={100}
                      value={section}
                      onChange={(event) =>
                        update(
                          "sections",
                          draft.sections.map((item, position) =>
                            position === index ? event.target.value : item,
                          ),
                        )
                      }
                    />
                  </label>
                  <button
                    type="button"
                    className="icon-button"
                    disabled={draft.sections.length <= 1}
                    aria-label={`删除第 ${index + 1} 章`}
                    onClick={() =>
                      update(
                        "sections",
                        draft.sections.filter(
                          (_, position) => position !== index,
                        ),
                      )
                    }
                  >
                    <X size={17} />
                  </button>
                </div>
              ))}
            </div>
            <button
              type="button"
              className="text-button add-chapter"
              disabled={draft.sections.length >= 20}
              onClick={() => update("sections", [...draft.sections, ""])}
            >
              <Plus size={16} />
              添加章节
            </button>
          </section>
          <div className="save-area">
            {error && (
              <Notice
                kind="error"
                action={
                  conflict && refresh ? (
                    <button
                      type="button"
                      className="text-button"
                      onClick={refresh}
                    >
                      查看最新版本
                    </button>
                  ) : undefined
                }
              >
                {error}
              </Notice>
            )}
            {saved && (
              <Notice kind="success">
                <Check size={16} />
                草稿已保存到本地工作空间。
              </Notice>
            )}
            <div className="save-bar">
              <span>
                {saving
                  ? "正在保存，请稍候…"
                  : dirty
                    ? "有尚未保存的修改"
                    : report
                      ? `已保存 · 草稿版本 ${report.version}`
                      : "保存后可随时返回继续编辑"}
              </span>
              <button
                type="submit"
                className="button primary"
                disabled={saving || conflict || (Boolean(report) && !dirty)}
              >
                {saving ? (
                  <Loader2 size={17} className="spin" />
                ) : (
                  <Save size={17} />
                )}
                {saving ? "正在保存" : "保存草稿"}
              </button>
            </div>
          </div>
        </div>
        <aside className="draft-aside">
          <div className="card guidance-card">
            <div className="heading-with-icon">
              <FileText size={18} />
              <h2>当前阶段</h2>
            </div>
            <span className="status-badge">需求草稿</span>
            <p>
              先把报告的主题、期间和重点记录下来。这些内容将作为后续协作的起点。
            </p>
            <div className="aside-divider" />
            <h3>接下来</h3>
            <p>
              材料库已支持文件导入与预览。保存草稿后，可在下方整理与核对数据；多智能体生成、审核与
              Markdown / PDF 导出将在后续版本开放。
            </p>
            <div className="version-label">v2.0-alpha.3 · 数据核对</div>
          </div>
          <div className="privacy-note">
            <ShieldCheck size={16} />
            <span>当前操作只保存草稿，不会发起模型请求。</span>
          </div>
        </aside>
      </fieldset>
    </form>
  );
}

function Editor({
  id,
  workspace,
  navigate,
  changed,
  onDirty,
  onSaving,
  confirm,
}: {
  id: string;
  workspace: Workspace;
  navigate: (path: string) => void;
  changed: () => void;
  onDirty: (dirty: boolean) => void;
  onSaving: (saving: boolean) => void;
  confirm: Confirm;
}) {
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const [reload, setReload] = useState(0);
  useEffect(() => {
    let active = true;
    setReport(null);
    setError("");
    api<Report>(`/reports/${encodeURIComponent(id)}`, workspace)
      .then((result) => {
        if (active) setReport(result);
      })
      .catch((reason) => {
        if (active) setError(message(reason));
      });
    return () => {
      active = false;
    };
  }, [id, workspace, reload]);
  const refreshing = useRef(false);
  const refresh = async () => {
    if (refreshing.current) return;
    refreshing.current = true;
    try {
      if (
        await confirm(
          "重新读取会替换页面中尚未保存的输入。建议先复制需要保留的内容。现在读取最新版本吗？",
          "读取最新版本？",
          "读取最新版本",
        )
      ) {
        onDirty(false);
        setRevision((value) => value + 1);
        setReload((value) => value + 1);
      }
    } finally {
      refreshing.current = false;
    }
  };
  return (
    <>
      <button className="back-link" onClick={() => navigate("/reports")}>
        <ArrowLeft size={15} />
        报告任务
      </button>
      <div className="page-heading editor-heading">
        <div>
          <div className="eyebrow">REPORT WORKSPACE</div>
          <h1>{report?.title || "报告工作区"}</h1>
          <p>
            {report
              ? `${report.department} · 更新于 ${dateTime(report.updated_at)}`
              : "查看并继续完善报告需求。"}
          </p>
        </div>
        {report && (
          <span className="status-badge">草稿 · v{report.version}</span>
        )}
      </div>
      {error ? (
        <Notice
          kind="error"
          action={
            <button
              className="text-button"
              onClick={() => setReload((value) => value + 1)}
            >
              重试
            </button>
          }
        >
          {error}
        </Notice>
      ) : !report ? (
        <div className="loading-panel" role="status">
          <Loader2 size={22} className="spin" />
          正在打开报告…
        </div>
      ) : (
        <>
          <DraftForm
            key={revision}
            report={report}
            workspace={workspace}
            onDirty={onDirty}
            onSaving={onSaving}
            refresh={refresh}
            onSaved={(result) => {
              setReport(result);
              changed();
            }}
          />
          <Statistics
            key={`${workspace}:${report.id}`}
            report={report}
            workspace={workspace}
          />
        </>
      )}
    </>
  );
}

function FuturePage({ navigate }: { navigate: (path: string) => void }) {
  return (
    <>
      <div className="page-heading">
        <div>
          <div className="eyebrow">REPORT ARCHIVE</div>
          <h1>报告归档</h1>
          <p>保留经审核确认的正式报告与交付文件。</p>
        </div>
      </div>
      <section className="card">
        <EmptyState
          icon={Archive}
          title="正式归档将在审核功能完成后开放"
          description="当前支持需求草稿和材料接入。审核、归档和 Markdown / PDF 导出将在 v2.0-alpha.5 完善。"
        >
          <button
            className="button secondary"
            onClick={() => navigate("/reports")}
          >
            查看报告任务
            <ArrowRight size={16} />
          </button>
        </EmptyState>
      </section>
    </>
  );
}

function Settings({
  system,
  error,
  retry,
}: {
  system: SystemInfo | null;
  error: string;
  retry: () => void;
}) {
  return (
    <>
      <div className="page-heading">
        <div>
          <div className="eyebrow">PREFERENCES</div>
          <h1>系统设置</h1>
          <p>查看本地服务与模型连接状态。</p>
        </div>
        <button className="button secondary" onClick={retry}>
          <RefreshCw size={16} />
          刷新状态
        </button>
      </div>
      <section className="card settings-card">
        <h2>模型连接</h2>
        {error ? (
          <Notice kind="error">{error}</Notice>
        ) : !system ? (
          <p role="status">正在读取配置状态…</p>
        ) : (
          <>
            <div className="setting-row">
              <div>
                <h3>本地模型配置</h3>
                <p>
                  {system.model_configured
                    ? "服务已读取模型配置。此状态不代表已经进行连通测试。"
                    : "尚未检测到模型配置，仍可正常使用草稿保存。"}
                </p>
              </div>
              <span
                className={`status-badge ${system.model_configured ? "configured" : ""}`}
              >
                {system.model_configured ? "已配置" : "未配置"}
              </span>
            </div>
            <Notice>
              模型密钥由本地环境配置管理。当前页面不读取或显示密钥，草稿操作不调用模型。
            </Notice>
          </>
        )}
        <div className="aside-divider" />
        <h2>应用信息</h2>
        <div className="setting-row">
          <div>
            <h3>汇报协作工作台</h3>
            <p>本地单用户工作空间</p>
          </div>
          <span className="muted">{system?.version || "版本读取中"}</span>
        </div>
        <p className="field-hint">
          当前支持持久化草稿、TXT / CSV / DOCX
          材料导入、本地模拟接口、材料版本管理与来源可追溯的统计快照；模型生成和正式导出将按版本逐步开放。
        </p>
      </section>
    </>
  );
}

function Help({
  workspace,
  switchWorkspace,
  navigate,
  onSaving,
}: {
  workspace: Workspace;
  switchWorkspace: (next: Workspace) => void;
  navigate: (path: string) => void;
  onSaving: (value: boolean) => void;
}) {
  return (
    <>
      <div className="page-heading">
        <div>
          <div className="eyebrow">GUIDE & DEMO</div>
          <h1>帮助与演示</h1>
          <p>了解当前功能，选择适合的工作空间。</p>
        </div>
      </div>
      <div className="help-grid">
        <section className="card help-card">
          <div className="empty-icon small">
            <FileText size={24} />
          </div>
          <h2>从需求与材料开始</h2>
          <ol className="guide-list">
            <li>
              <span>1</span>
              <div>
                <strong>新建报告</strong>
                <p>填写标题、部门与起止日期。</p>
              </div>
            </li>
            <li>
              <span>2</span>
              <div>
                <strong>整理材料</strong>
                <p>进入材料库，选择分类，上传 TXT、CSV 或 DOCX 并预览。</p>
              </div>
            </li>
            <li>
              <span>3</span>
              <div>
                <strong>确认并保存</strong>
                <p>
                  核对字段映射和校验提示后确认入库。材料与草稿在刷新或重启后仍可读取。
                </p>
              </div>
            </li>
          </ol>
          <Notice>
            材料库已开放 TXT / CSV / DOCX
            导入、预览与校验。智能体生成、审核和导出将在后续版本开放。
          </Notice>
        </section>
        <section className="card help-card">
          <div className="empty-icon small">
            <ShieldCheck size={24} />
          </div>
          <h2>独立演示工作空间</h2>
          <p>
            演示报告与正常工作数据分别保存，不会混入正常首页或归档。切换空间不会自动加载案例，也不会调用模型。
          </p>
          <div className="space-description">
            <span className="caption-dot" />
            <strong>
              当前：{workspace === "demo" ? "演示工作空间" : "正常工作空间"}
            </strong>
          </div>
          <button
            className={`button ${workspace === "demo" ? "secondary" : "primary"}`}
            onClick={() =>
              switchWorkspace(workspace === "demo" ? "normal" : "demo")
            }
          >
            {workspace === "demo" ? "返回正常工作空间" : "进入独立演示空间"}
            <ArrowRight size={16} />
          </button>
        </section>
      </div>
      <DemoMaterials
        workspace={workspace}
        navigate={navigate}
        onSaving={onSaving}
      />
    </>
  );
}

export default function App() {
  const { confirm, confirming, dialog } = useConfirmation();
  const navigationBusy = useRef(false);
  const saveInProgress = useRef(false);
  const onSaving = useCallback((value: boolean) => {
    saveInProgress.current = value;
  }, []);
  const [path, setPath] = useState(route);
  const [workspace, setWorkspace] = useState<Workspace>(() => {
    try {
      return localStorage.getItem("office-workspace") === "demo"
        ? "demo"
        : "normal";
    } catch {
      return "normal";
    }
  });
  const [reports, setReports] = useState<Report[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [system, setSystem] = useState<SystemInfo | null>(null);
  const [systemError, setSystemError] = useState("");
  const [reload, setReload] = useState(0);
  const [mobileOpen, setMobileOpen] = useState(false);
  const dirty = useRef(false);
  const currentPath = useRef(path);
  const sidebarRef = useRef<HTMLElement>(null);
  const menuRef = useRef<HTMLButtonElement>(null);
  const wasMobileOpen = useRef(false);
  useEffect(() => {
    if (mobileOpen)
      sidebarRef.current?.querySelector<HTMLButtonElement>("button")?.focus();
    else if (wasMobileOpen.current) menuRef.current?.focus();
    wasMobileOpen.current = mobileOpen;
    if (!mobileOpen) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setMobileOpen(false);
        return;
      }
      if (event.key !== "Tab") return;
      const elements = sidebarRef.current?.querySelectorAll<HTMLElement>(
        "a[href], button:not([disabled])",
      );
      if (!elements?.length) return;
      const first = elements[0];
      const last = elements[elements.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [mobileOpen]);
  const onDirty = useCallback((value: boolean) => {
    dirty.current = value;
  }, []);
  const changed = useCallback(() => setReload((value) => value + 1), []);
  const commitPath = useCallback((next: string) => {
    dirty.current = false;
    currentPath.current = next;
    window.location.hash = next;
    setPath(next);
    setMobileOpen(false);
    window.scrollTo({ top: 0 });
  }, []);
  const navigate = useCallback(
    async (next: string, skipGuard = false) => {
      if (saveInProgress.current && !skipGuard) return;
      if (next === currentPath.current) {
        setMobileOpen(false);
        return;
      }
      if (navigationBusy.current) return;
      navigationBusy.current = true;
      try {
        if (
          next !== currentPath.current &&
          dirty.current &&
          !skipGuard &&
          !(await confirm(
            "当前有尚未保存的草稿或尚未确认的材料导入。离开将放弃这些输入，确定继续吗？",
            "离开当前页面？",
          ))
        )
          return;
        commitPath(next);
      } finally {
        navigationBusy.current = false;
      }
    },
    [commitPath, confirm],
  );
  useEffect(() => {
    const onHash = async () => {
      const next = route();
      if (next === currentPath.current) return;
      if (saveInProgress.current || navigationBusy.current) {
        window.history.replaceState(null, "", `#${currentPath.current}`);
        return;
      }
      navigationBusy.current = true;
      try {
        if (
          dirty.current &&
          !(await confirm(
            "当前有尚未保存的草稿或尚未确认的材料导入。离开将放弃这些输入，确定继续吗？",
            "离开当前页面？",
          ))
        ) {
          window.history.replaceState(null, "", `#${currentPath.current}`);
          return;
        }
        commitPath(next);
      } finally {
        navigationBusy.current = false;
      }
    };
    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (dirty.current) {
        event.preventDefault();
        event.returnValue = "";
      }
    };
    window.addEventListener("hashchange", onHash);
    window.addEventListener("beforeunload", beforeUnload);
    return () => {
      window.removeEventListener("hashchange", onHash);
      window.removeEventListener("beforeunload", beforeUnload);
    };
  }, [commitPath, confirm]);
  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    setReports([]);
    api<{ items: Report[] }>("/reports", workspace)
      .then((result) => {
        if (active) setReports(result.items);
      })
      .catch((reason) => {
        if (active) setError(message(reason));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [workspace, reload]);
  useEffect(() => {
    let active = true;
    setSystem(null);
    setSystemError("");
    api<SystemInfo>("/system", workspace)
      .then((result) => {
        if (active) setSystem(result);
      })
      .catch((reason) => {
        if (active) setSystemError(message(reason));
      });
    return () => {
      active = false;
    };
  }, [workspace, reload]);
  const switchWorkspace = async (next: Workspace) => {
    if (saveInProgress.current || navigationBusy.current) return;
    navigationBusy.current = true;
    try {
      if (
        dirty.current &&
        !(await confirm(
          "切换工作空间会放弃尚未保存的输入，确定继续吗？",
          "切换工作空间？",
          "切换工作空间",
        ))
      )
        return;
      dirty.current = false;
      setReports([]);
      setError("");
      setLoading(true);
      setWorkspace(next);
      try {
        localStorage.setItem("office-workspace", next);
      } catch {
        /* Saving the workspace preference is optional. */
      }
      commitPath("/");
    } finally {
      navigationBusy.current = false;
    }
  };
  const navActive = path.startsWith("/reports") ? "/reports" : path;
  const title = path.startsWith("/reports/")
    ? path === "/reports/new"
      ? "新建报告"
      : "报告工作区"
    : [
        ...nav,
        { path: "/settings", label: "系统设置" },
        { path: "/help", label: "帮助与演示" },
      ].find((item) => item.path === path)?.label || "页面未找到";
  return (
    <>
      <div className="app-shell" inert={confirming}>
        <a
          className="skip-link"
          href="#main-content"
          onClick={(event) => {
            event.preventDefault();
            document.getElementById("main-content")?.focus();
          }}
        >
          跳到主要内容
        </a>
        {mobileOpen && (
          <button
            className="mobile-overlay"
            aria-label="关闭导航"
            onClick={() => setMobileOpen(false)}
          />
        )}
        <aside
          ref={sidebarRef}
          className={`sidebar ${mobileOpen ? "is-open" : ""}`}
        >
          <div className="brand">
            <div className="brand-icon">
              <FileCheck2 size={23} strokeWidth={1.8} />
            </div>
            <div>
              <strong>汇报协作</strong>
              <span>工作汇报工作台</span>
            </div>
          </div>
          <button
            className="icon-button sidebar-close"
            aria-label="关闭导航"
            onClick={() => setMobileOpen(false)}
          >
            <X size={20} />
          </button>
          <div className="sidebar-group-label">工作空间</div>
          <nav aria-label="主导航">
            {nav.map(({ path: target, label, icon: Icon }) => (
              <a
                href={`#${target}`}
                key={target}
                className={`nav-item ${navActive === target ? "active" : ""}`}
                aria-current={navActive === target ? "page" : undefined}
                onClick={(event) => {
                  event.preventDefault();
                  navigate(target);
                }}
              >
                <Icon size={19} strokeWidth={1.8} />
                {label}
              </a>
            ))}
          </nav>
          <div className="sidebar-bottom">
            <a
              href="#/settings"
              className={`nav-item ${path === "/settings" ? "active" : ""}`}
              onClick={(event) => {
                event.preventDefault();
                navigate("/settings");
              }}
            >
              <Settings2 size={18} />
              系统设置
            </a>
            <a
              href="#/help"
              className={`nav-item ${path === "/help" ? "active" : ""}`}
              onClick={(event) => {
                event.preventDefault();
                navigate("/help");
              }}
            >
              <CircleHelp size={18} />
              帮助与演示
            </a>
            <div className="sidebar-footer">
              <span className="caption-dot" />
              本地运行<span>alpha.3</span>
            </div>
          </div>
        </aside>
        <div className="main-shell">
          <header className="topbar">
            <div className="breadcrumb">
              <button
                ref={menuRef}
                className="icon-button mobile-menu"
                aria-label="打开导航"
                aria-expanded={mobileOpen}
                onClick={() => setMobileOpen(true)}
              >
                <Menu size={21} />
              </button>
              <span>工作空间</span>
              <ChevronRight size={13} />
              <strong>{title}</strong>
            </div>
            <span
              className={`workspace-pill ${workspace === "demo" ? "demo-pill" : ""}`}
            >
              <span className="caption-dot" />
              {workspace === "demo" ? "演示工作空间" : "本地工作空间"}
            </span>
          </header>
          {workspace === "demo" && (
            <div className="demo-banner">
              <span>演示空间 · 报告和材料均与正常工作数据隔离</span>
              <button onClick={() => switchWorkspace("normal")}>
                返回正常空间
                <ArrowRight size={14} />
              </button>
            </div>
          )}
          <main id="main-content" tabIndex={-1} key={workspace}>
            {path === "/" ? (
              <Home
                reports={reports}
                loading={loading}
                error={error}
                retry={changed}
                navigate={navigate}
                system={system}
              />
            ) : path === "/reports" ? (
              <ReportList
                reports={reports}
                loading={loading}
                error={error}
                retry={changed}
                navigate={navigate}
              />
            ) : path === "/reports/new" ? (
              <>
                <button
                  className="back-link"
                  onClick={() => navigate("/reports")}
                >
                  <ArrowLeft size={15} />
                  报告任务
                </button>
                <div className="page-heading">
                  <div>
                    <div className="eyebrow">NEW REPORT</div>
                    <h1>新建工作汇报</h1>
                    <p>给这份报告一个清晰的起点，内容可以随时调整。</p>
                  </div>
                </div>
                <DraftForm
                  workspace={workspace}
                  onDirty={onDirty}
                  onSaving={onSaving}
                  onSaved={(report) => {
                    changed();
                    navigate(`/reports/${report.id}`, true);
                  }}
                />
              </>
            ) : /^\/reports\/[^/]+$/.test(path) ? (
              <Editor
                key={path}
                id={path.split("/")[2]}
                workspace={workspace}
                navigate={navigate}
                changed={changed}
                onDirty={onDirty}
                onSaving={onSaving}
                confirm={confirm}
              />
            ) : path === "/materials" ? (
              <Materials
                workspace={workspace}
                onDirty={onDirty}
                onSaving={onSaving}
                confirm={confirm}
              />
            ) : path === "/archive" ? (
              <FuturePage navigate={navigate} />
            ) : path === "/settings" ? (
              <Settings system={system} error={systemError} retry={changed} />
            ) : path === "/help" ? (
              <Help
                workspace={workspace}
                switchWorkspace={switchWorkspace}
                navigate={navigate}
                onSaving={onSaving}
              />
            ) : (
              <EmptyState
                title="页面未找到"
                description="请从左侧导航进入工作空间。"
              >
                <button
                  className="button primary"
                  onClick={() => navigate("/")}
                >
                  返回工作台
                </button>
              </EmptyState>
            )}
          </main>
          <footer className="app-footer">
            汇报协作<span>v2.0-alpha.3</span>
          </footer>
        </div>
      </div>
      {dialog}
    </>
  );
}
