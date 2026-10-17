import { useEffect, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  Archive as ArchiveIcon,
  FileCheck2,
  Loader2,
  RefreshCw,
  Search,
} from "lucide-react";
import { api, type Report, type Workspace } from "./api";
import { Delivery } from "./Delivery";

export function Archive({
  workspace,
  navigate,
}: {
  workspace: Workspace;
  navigate: (path: string) => void;
}) {
  const [reports, setReports] = useState<Report[]>([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    api<{ items: Report[] }>("/reports?status=approved", workspace, {
      signal: controller.signal,
    })
      .then(({ items }) => {
        if (!controller.signal.aborted) setReports(items);
      })
      .catch((reason) => {
        if (!controller.signal.aborted)
          setError(
            reason instanceof Error
              ? reason.message
              : "归档读取未完成，请重试。",
          );
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [workspace, refresh]);
  const filtered = reports.filter((report) =>
    `${report.title} ${report.department}`
      .toLocaleLowerCase()
      .includes(search.trim().toLocaleLowerCase()),
  );
  return (
    <>
      <div className="page-heading">
        <div>
          <div className="eyebrow">REPORT ARCHIVE</div>
          <h1>报告归档</h1>
          <p>查看当前审核合格的报告、历史修订和交付文件。</p>
        </div>
      </div>
      <section className="card">
        <div className="list-toolbar">
          <label className="search-field">
            <Search size={18} />
            <span className="sr-only">搜索已归档报告标题或部门</span>
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="搜索报告标题或部门"
            />
          </label>
          <span className="list-count">{filtered.length} 份合格报告</span>
          <button
            className="icon-button"
            type="button"
            disabled={loading}
            aria-label="刷新报告归档"
            onClick={() => setRefresh((value) => value + 1)}
          >
            <RefreshCw size={17} className={loading ? "spin" : ""} />
          </button>
        </div>
        {error ? (
          <div className="notice error" role="alert">
            <span>{error}</span>
            <button
              className="text-button"
              type="button"
              onClick={() => setRefresh((value) => value + 1)}
            >
              重试
            </button>
          </div>
        ) : loading ? (
          <div className="loading-panel" role="status">
            <Loader2 className="spin" size={22} />
            正在读取已归档报告…
          </div>
        ) : filtered.length ? (
          <div className="report-rows">
            {filtered.map((report) => (
              <button
                className="report-row"
                type="button"
                key={report.id}
                onClick={() =>
                  navigate(`/reports/${encodeURIComponent(report.id)}/delivery`)
                }
              >
                <span className="document-icon">
                  <FileCheck2 size={21} strokeWidth={1.7} />
                </span>
                <span className="report-row-content">
                  <strong>{report.title}</strong>
                  <span>
                    {report.department}
                    <span className="dot">·</span>
                    {report.start_date} 至 {report.end_date}（不含）
                  </span>
                </span>
                <span className="status-badge">审核合格</span>
                <ArrowRight size={17} className="muted" />
              </button>
            ))}
          </div>
        ) : (
          <div className="empty-state">
            <div className="empty-icon">
              <ArchiveIcon size={30} strokeWidth={1.5} />
            </div>
            <h3>{search.trim() ? "没有匹配的合格报告" : "暂无已合格报告"}</h3>
            <p>
              {search.trim()
                ? "尝试其他标题或部门，或清空搜索。"
                : "五角色协作通过审核和经理验收后，当前合格修订会显示在这里。"}
            </p>
            {!search.trim() && (
              <div className="empty-actions">
                <button
                  className="button secondary"
                  type="button"
                  onClick={() => navigate("/reports")}
                >
                  查看报告任务
                  <ArrowRight size={16} />
                </button>
              </div>
            )}
          </div>
        )}
      </section>
      <p className="field-hint archive-note">
        列表仅显示当前合格修订。修改后待审核的报告会暂时离开此列表；既有合格历史文件仍可从报告任务的协作记录查看。离线模拟报告会在交付页明确标注。
      </p>
    </>
  );
}

export function ReportDelivery({
  reportId,
  workspace,
  navigate,
  onDirty,
  onSaving,
  onChanged,
}: {
  reportId: string;
  workspace: Workspace;
  navigate: (path: string) => void;
  onDirty: (value: boolean) => void;
  onSaving: (value: boolean) => void;
  onChanged: () => void;
}) {
  return (
    <>
      <button
        className="back-link"
        type="button"
        onClick={() => navigate("/archive")}
      >
        <ArrowLeft size={15} />
        报告归档
      </button>
      <div className="page-heading">
        <div>
          <div className="eyebrow">REPORT DELIVERY</div>
          <h1>报告交付</h1>
          <p>查看修订、审核结果，下载与同一快照绑定的 Markdown 和 PDF。</p>
        </div>
      </div>
      <section className="card">
        <Delivery
          reportId={reportId}
          workspace={workspace}
          onDirty={onDirty}
          onSaving={onSaving}
          navigate={navigate}
          onChanged={onChanged}
        />
      </section>
    </>
  );
}
