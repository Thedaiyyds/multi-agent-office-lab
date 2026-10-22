import { periodText } from "./format";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
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
  Settings2,
  ShieldCheck,
  Upload,
  X,
} from "lucide-react";
import { api, type Report, type SystemInfo, type Workspace } from "./api";
import { useConfirmation } from "./confirm";
import Materials from "./Materials";
import Tasks from "./Tasks";
import { Archive as ReportArchive, ReportDelivery } from "./Archive";
import { RunComposer, RunDetail, RunHistory } from "./Cooperation";

const nav = [
  { path: "/", label: "工作台", icon: LayoutDashboard },
  { path: "/reports", label: "报告任务", icon: FileText },
  { path: "/materials", label: "材料库", icon: FolderOpen },
  { path: "/archive", label: "报告归档", icon: Archive },
];
const reportStatus: Record<Report["status"], string> = {
  draft: "待生成",
  pending_review: "待审核",
  needs_changes: "需要修改",
  approved: "审核合格",
};
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
          <span className="status-badge">{reportStatus[report.status]}</span>
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
  const pending = reports.filter((report) => report.status !== "approved");
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
          模型连接尚未配置。可以先整理材料，或主动选择离线模拟验证协作流程。
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
                description="用一段话描述需求，选择材料，交给五角色团队协作。"
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
                <p>查看协作结果、审核状态，或继续完善工作汇报。</p>
              </div>
              <button
                className="button secondary"
                onClick={() => navigate(`/reports/${reports[0].id}`)}
              >
                打开最近报告
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
                {pending.length > 0 && (
                  <span className="count-badge">{pending.length}</span>
                )}
              </div>
              {pending.length === 0 ? (
                <EmptyState
                  compact
                  icon={Check}
                  title="暂无待处理事项"
                  description="需要继续处理的报告会出现在这里。"
                />
              ) : (
                <>
                  <div className="card-subtitle">需要继续处理的报告</div>
                  <ReportRows
                    reports={pending.slice(0, 3)}
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
        本地工作空间<span>协作记录与报告结果自动保留</span>
      </div>
    </>
  );
}

function ReportWorkspace({
  id,
  workspace,
  navigate,
  changed,
  onDirty,
  onSaving,
  system,
}: {
  id: string;
  workspace: Workspace;
  navigate: (path: string, skipGuard?: boolean) => void;
  changed: () => void;
  onDirty: (dirty: boolean) => void;
  onSaving: (saving: boolean) => void;
  system: SystemInfo | null;
}) {
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setReport(null);
    setError("");
    api<Report>(`/reports/${encodeURIComponent(id)}`, workspace, {
      signal: controller.signal,
    })
      .then((result) => {
        if (!controller.signal.aborted) setReport(result);
      })
      .catch((reason) => {
        if (!controller.signal.aborted) setError(message(reason));
      });
    return () => controller.abort();
  }, [id, workspace, reload]);
  const composer = report && (
    <RunComposer
      workspace={workspace}
      system={system}
      report={report}
      onDirty={onDirty}
      onSaving={onSaving}
      onStarted={(run) => {
        changed();
        navigate(`/runs/${run.id}`, true);
      }}
    />
  );
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
              ? `${report.department} · ${periodText(report.start_date!, report.end_date!)}`
              : "查看报告需求、生成记录与交付结果。"}
          </p>
        </div>
        {report && (
          <div className="report-heading-actions">
            <span className="status-badge">{reportStatus[report.status]}</span>
            {report.status !== "draft" && (
              <button
                className="button primary"
                onClick={() => navigate(`/reports/${report.id}/delivery`)}
              >
                <FileText size={17} />
                查看报告
                <ArrowRight size={15} />
              </button>
            )}
          </div>
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
          {report.status === "draft" ? (
            composer
          ) : (
            <details className="report-regenerate">
              <summary>重新生成报告</summary>
              {composer}
            </details>
          )}
          <RunHistory
            workspace={workspace}
            reportId={report.id}
            navigate={navigate}
          />
        </>
      )}
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
                    : "尚未检测到模型配置，可先管理材料或选择离线模拟。"}
                </p>
              </div>
              <span
                className={`status-badge ${system.model_configured ? "configured" : ""}`}
              >
                {system.model_configured ? "已配置" : "未配置"}
              </span>
            </div>
            <Notice>
              模型密钥由服务端配置管理。查看设置、整理材料和下载已有报告不会调用模型。
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
          当前支持任务与报告持久化、TXT / CSV / DOCX
          材料导入、本地模拟接口、来源可追溯的统计、五角色协作、审核返工、经理验收，以及报告修订和
          Markdown / PDF 文件交付。
        </p>
      </section>
    </>
  );
}

function Help({ navigate }: { navigate: (path: string) => void }) {
  return (
    <>
      <div className="page-heading">
        <div>
          <div className="eyebrow">WORKSPACE GUIDE</div>
          <h1>使用帮助</h1>
          <p>在当前工作台提交需求，查看五角色团队的协作过程。</p>
        </div>
      </div>
      <div className="help-grid">
        <section className="card help-card">
          <div className="empty-icon small">
            <FileText size={24} />
          </div>
          <h2>三步生成工作汇报</h2>
          <ol className="guide-list">
            <li>
              <span>1</span>
              <div>
                <strong>选择材料，输入需求</strong>
                <p>
                  在材料库导入并确认 TXT、CSV 或
                  DOCX。点击“新建报告”，勾选所需材料，用一段话说明部门、期间、主题和重点。
                </p>
              </div>
            </li>
            <li>
              <span>2</span>
              <div>
                <strong>开始协作</strong>
                <p>
                  点击“开始协作”。需求经理理解并拆解任务，内容规划生成大纲，数据整理核对依据，报告撰写生成内容，审核校验检查并反馈修改。
                </p>
              </div>
            </li>
            <li>
              <span>3</span>
              <div>
                <strong>查看结果与验收</strong>
                <p>
                  在运行详情查看报告预览、审核与返工、节点输入输出和协作时间线，确认
                  Manager 最终验收。也可从报告任务里的运行记录返回本次结果。
                </p>
              </div>
            </li>
          </ol>
          <button
            className="button primary"
            onClick={() => navigate("/reports/new")}
          >
            新建报告
            <ArrowRight size={16} />
          </button>
        </section>
        <section className="card help-card">
          <div className="empty-icon small">
            <ShieldCheck size={24} />
          </div>
          <h2>数据与执行方式</h2>
          <p>
            真实模型模式使用本地配置的模型连接，会消耗 API
            token。离线模拟须由你主动选择，用于验证流程，不会调用外部模型。
          </p>
          <p>
            系统不会默认为报告填充样例。只有明确勾选“使用系统本地样例数据（虚构）”时，才接入样例数据；材料不足时会提示补充。
          </p>
          <Notice>
            完整协作通过 Checker 与 Manager 验收后，系统自动保存报告修订并生成
            Markdown /
            PDF。修改文字会创建待审核的新修订；查看、下载和重试文件导出不会调用模型。
          </Notice>
          <button
            className="button secondary"
            onClick={() => navigate("/materials")}
          >
            管理材料
            <ArrowRight size={16} />
          </button>
        </section>
      </div>
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
            "当前有尚未提交的需求、报告修改或尚未确认的材料导入。离开将放弃这些输入，确定继续吗？",
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
            "当前有尚未提交的需求、报告修改或尚未确认的材料导入。离开将放弃这些输入，确定继续吗？",
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
  const deliveryPath = /^\/reports\/[^/]+\/delivery$/.test(path);
  const navActive = deliveryPath
    ? "/archive"
    : path.startsWith("/reports") || path.startsWith("/runs/")
      ? "/reports"
      : path;
  const title = deliveryPath
    ? "报告交付"
    : path.startsWith("/runs/")
      ? "五角色协作"
      : path.startsWith("/reports/")
        ? path === "/reports/new"
          ? "新建报告"
          : "报告工作区"
        : [
            ...nav,
            { path: "/settings", label: "系统设置" },
            { path: "/help", label: "使用帮助" },
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
              使用帮助
            </a>
            <div className="sidebar-footer">
              <span className="caption-dot" />
              本地运行<span>v2.5.0</span>
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
              <Tasks
                key={workspace}
                workspace={workspace}
                navigate={navigate}
                onSaving={onSaving}
              />
            ) : path === "/reports/new" ||
              path.split("?")[0] === "/reports/plan" ? (
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
                    <h1>
                      {path.split("?")[0] === "/reports/plan"
                        ? "基于材料规划汇报"
                        : "新建工作汇报"}
                    </h1>
                    <p>
                      {path.split("?")[0] === "/reports/plan"
                        ? "先看方案，再决定是否生成。文件内容从工作目录按需读取。"
                        : "输入工作需求，让五角色团队自动完成规划、整理、撰写与审核。"}
                    </p>
                  </div>
                </div>
                <RunComposer
                  key={`${workspace}:${path}`}
                  planning={path.split("?")[0] === "/reports/plan"}
                  initialMaterialIds={new URLSearchParams(path.split("?")[1])
                    .getAll("material")
                    .slice(0, 50)}
                  workspace={workspace}
                  system={system}
                  onDirty={onDirty}
                  onSaving={onSaving}
                  onStarted={(run) => {
                    changed();
                    navigate(`/runs/${run.id}`, true);
                  }}
                />
              </>
            ) : /^\/runs\/[^/]+$/.test(path) ? (
              <RunDetail
                key={path}
                id={path.split("/")[2]}
                workspace={workspace}
                navigate={navigate}
                changed={changed}
                onDirty={onDirty}
                onSaving={onSaving}
              />
            ) : deliveryPath ? (
              <ReportDelivery
                key={path}
                reportId={path.split("/")[2]}
                workspace={workspace}
                navigate={navigate}
                onDirty={onDirty}
                onSaving={onSaving}
                onChanged={changed}
              />
            ) : /^\/reports\/[^/]+$/.test(path) ? (
              <ReportWorkspace
                key={path}
                id={path.split("/")[2]}
                workspace={workspace}
                navigate={navigate}
                changed={changed}
                onDirty={onDirty}
                onSaving={onSaving}
                system={system}
              />
            ) : path === "/materials" ? (
              <Materials
                navigate={navigate}
                workspace={workspace}
                onDirty={onDirty}
                onSaving={onSaving}
                confirm={confirm}
              />
            ) : path === "/archive" ? (
              <ReportArchive workspace={workspace} navigate={navigate} />
            ) : path === "/settings" ? (
              <Settings system={system} error={systemError} retry={changed} />
            ) : path === "/help" ? (
              <Help navigate={navigate} />
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
            汇报协作<span>v2.5.0</span>
          </footer>
        </div>
      </div>
      {dialog}
    </>
  );
}
