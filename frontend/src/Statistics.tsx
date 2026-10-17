import { useEffect, useRef, useState, type FormEvent } from "react";
import { BarChart3, ChevronDown, Loader2, RefreshCw } from "lucide-react";
import {
  api,
  ApiError,
  type MaterialIssue,
  type MaterialKind,
  type MaterialVersion,
  type Report,
  type StatisticsGroup,
  type StatisticsMetric,
  type StatisticsSnapshot,
  type Workspace,
} from "./api";

const groups: Record<StatisticsGroup, string> = {
  projects: "项目进度",
  attendance: "人员考勤",
  achievements: "成果统计",
  satisfaction: "服务满意度",
};
const kindLabel = (kind: MaterialKind) =>
  kind === "notes" ? "文字说明" : groups[kind];
const describe = (reason: unknown) =>
  reason instanceof Error ? reason.message : "数据读取未完成，请重试。";
const time = (value: string) => {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleString("zh-CN", { hour12: false });
};
const displayValue = (metric: StatisticsMetric) => {
  if (metric.value === null) return "未定义";
  const value = metric.unit === "ratio" ? metric.value * 100 : metric.value;
  return `${new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 }).format(value)}${metric.unit === "ratio" ? "%" : ""}`;
};

function Issues({ items }: { items: MaterialIssue[] }) {
  return items.length ? (
    <ul className="statistics-issues">
      {items.map((issue, index) => (
        <li key={index} className={issue.severity}>
          <strong>
            {issue.severity === "error" ? "需修正" : "提示"} · {issue.location}
          </strong>
          <span>{issue.message}</span>
        </li>
      ))}
    </ul>
  ) : null;
}

function Snapshot({
  snapshot,
  version,
}: {
  snapshot: StatisticsSnapshot;
  version: number;
}) {
  const stale = snapshot.report_version !== version;
  return (
    <div className="statistics-result">
      <div className="statistics-result-heading">
        <div>
          <h3>数据核对结果</h3>
          <p>
            草稿 v{snapshot.report_version} · {time(snapshot.created_at)} · 口径{" "}
            {snapshot.policy_version}
          </p>
        </div>
        <span
          className={`status-badge ${snapshot.status === "ready" && !stale ? "statistics-ready" : "statistics-attention"}`}
        >
          {stale
            ? "对应旧草稿"
            : {
                ready: "可供后续撰写",
                needs_input: "需要补充数据",
                invalid_data: "材料存在问题",
              }[snapshot.status]}
        </span>
      </div>
      {stale && (
        <div className="notice" role="status">
          此结果对应旧草稿 v{snapshot.report_version}，当前为 v{version}
          。请重新整理数据，不能将旧结果视为当前报告的数据。
        </div>
      )}
      <p className="field-hint">
        {snapshot.department} · {snapshot.start_date}（含）至{" "}
        {snapshot.end_date}（不含）。数值为“未定义”时，不代表 0。
      </p>
      <Issues items={snapshot.issues} />
      {snapshot.metrics.length ? (
        <div className="statistics-metrics">
          {snapshot.metrics.map((metric) => (
            <details key={metric.id} className="statistics-metric">
              <summary>
                <span>
                  <strong>{metric.label}</strong>
                  <small>
                    {metric.value !== null && metric.unit !== "ratio"
                      ? metric.unit
                      : ""}
                  </small>
                </span>
                <b>{displayValue(metric)}</b>
                <ChevronDown size={16} />
              </summary>
              <div className="statistics-metric-body">
                <h4>计算口径</h4>
                <p>{metric.definition}</p>
                <p className="field-hint">
                  原始值：
                  {metric.value === null ? "null（未定义）" : metric.value} ·
                  单位：{metric.unit}
                </p>
                {metric.limitations.length > 0 && (
                  <>
                    <h4>适用限制</h4>
                    <ul>
                      {metric.limitations.map((item, index) => (
                        <li key={index}>{item}</li>
                      ))}
                    </ul>
                  </>
                )}
                <h4>来源与定位</h4>
                {metric.source_refs.length ? (
                  <div className="statistics-source-scroll">
                    <table className="statistics-source-table">
                      <thead>
                        <tr>
                          <th>材料版本</th>
                          <th>原文位置</th>
                          <th>字段</th>
                        </tr>
                      </thead>
                      <tbody>
                        {metric.source_refs.map((source, index) => (
                          <tr
                            key={`${source.material_id}-${source.location}-${index}`}
                          >
                            <td>
                              {source.name} · v{source.version}
                              <details>
                                <summary>文件指纹</summary>
                                <code>{source.sha256}</code>
                              </details>
                            </td>
                            <td>{source.location}</td>
                            <td>{source.fields.join("、")}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <p>无可用来源；请结合计算口径和提示核对。</p>
                )}
              </div>
            </details>
          ))}
        </div>
      ) : (
        <p className="field-hint">此快照暂无可计算指标，请根据提示补充材料。</p>
      )}
      <details className="statistics-frozen">
        <summary>本次冻结的材料版本（{snapshot.materials.length}）</summary>
        <ul>
          {snapshot.materials.map((material) => (
            <li key={material.id}>
              <strong>
                {material.name} · v{material.version}
              </strong>
              <code>{material.sha256}</code>
            </li>
          ))}
        </ul>
      </details>
    </div>
  );
}

export default function Statistics({
  report,
  workspace,
}: {
  report: Report;
  workspace: Workspace;
}) {
  const [materials, setMaterials] = useState<MaterialVersion[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [selectedGroups, setSelectedGroups] = useState<StatisticsGroup[]>([]);
  const [customGroups, setCustomGroups] = useState(false);
  const [roster, setRoster] = useState("");
  const [dates, setDates] = useState("");
  const [snapshots, setSnapshots] = useState<StatisticsSnapshot[]>([]);
  const [snapshotId, setSnapshotId] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [issues, setIssues] = useState<MaterialIssue[]>([]);
  const [refresh, setRefresh] = useState(0);
  const scope = `${workspace}:${report.id}`;
  const liveScope = useRef(scope);
  liveScope.current = scope;
  const sequence = useRef(0);
  const lock = useRef(false);
  const mounted = useRef(false);
  useEffect(() => {
    mounted.current = true;
    setSelected([]);
    setSelectedGroups([]);
    setCustomGroups(false);
    setRoster("");
    setDates("");
    setSnapshots([]);
    setSnapshotId("");
    setError("");
    setIssues([]);
    setBusy(false);
    lock.current = false;
    return () => {
      mounted.current = false;
      sequence.current += 1;
    };
  }, [scope]);
  useEffect(() => {
    const request = ++sequence.current;
    const controller = new AbortController();
    setLoading(true);
    setError("");
    Promise.all([
      api<{ items: MaterialVersion[] }>("/materials", workspace, {
        signal: controller.signal,
      }),
      api<{ items: StatisticsSnapshot[] }>(
        `/reports/${encodeURIComponent(report.id)}/statistics`,
        workspace,
        { signal: controller.signal },
      ),
    ])
      .then(([library, history]) => {
        if (!mounted.current || request !== sequence.current) return;
        setMaterials(library.items);
        setSnapshots(history.items);
        setSnapshotId((previous) =>
          history.items.some((item) => item.id === previous)
            ? previous
            : history.items[0]?.id || "",
        );
      })
      .catch((reason) => {
        if (
          mounted.current &&
          request === sequence.current &&
          !controller.signal.aborted
        )
          setError(describe(reason));
      })
      .finally(() => {
        if (mounted.current && request === sequence.current) setLoading(false);
      });
    return () => controller.abort();
  }, [scope, report.version, refresh, workspace, report.id]);
  const inferredGroups = [
    ...new Set(
      materials
        .filter(
          (material) =>
            selected.includes(material.id) && material.kind !== "notes",
        )
        .map((material) => material.kind as StatisticsGroup),
    ),
  ];
  const effectiveGroups = customGroups ? selectedGroups : inferredGroups;
  const toggleMaterial = (id: string) =>
    setSelected((previous) =>
      previous.includes(id)
        ? previous.filter((item) => item !== id)
        : previous.length < 50
          ? [...previous, id]
          : previous,
    );
  const toggleGroup = (group: StatisticsGroup) => {
    setSelectedGroups(
      effectiveGroups.includes(group)
        ? effectiveGroups.filter((item) => item !== group)
        : [...effectiveGroups, group],
    );
    setCustomGroups(true);
  };
  const run = async (event: FormEvent) => {
    event.preventDefault();
    if (lock.current) return;
    if (!selected.length || !effectiveGroups.length) {
      setError("请至少选择一份材料和一个统计组。");
      return;
    }
    lock.current = true;
    setBusy(true);
    setError("");
    setIssues([]);
    const submittedScope = scope;
    const ids = selected.filter((id) =>
      materials.some((item) => item.id === id),
    );
    try {
      const snapshot = await api<StatisticsSnapshot>(
        `/reports/${encodeURIComponent(report.id)}/statistics`,
        workspace,
        {
          method: "POST",
          body: JSON.stringify({
            expected_version: report.version,
            material_ids: ids,
            groups: effectiveGroups,
            attendance_roster: [
              ...new Set(
                roster
                  .split(/[,，\n]/)
                  .map((item) => item.trim())
                  .filter(Boolean),
              ),
            ],
            attendance_dates: [
              ...new Set(
                dates
                  .split(/\n/)
                  .map((item) => item.trim())
                  .filter(Boolean),
              ),
            ],
          }),
        },
      );
      if (!mounted.current || liveScope.current !== submittedScope) return;
      sequence.current += 1;
      setLoading(false);
      setSnapshots((previous) => [
        snapshot,
        ...previous.filter((item) => item.id !== snapshot.id),
      ]);
      setSnapshotId(snapshot.id);
    } catch (reason) {
      if (!mounted.current || liveScope.current !== submittedScope) return;
      setError(describe(reason));
      setIssues(reason instanceof ApiError ? reason.issues : []);
    } finally {
      if (mounted.current && liveScope.current === submittedScope) {
        lock.current = false;
        setBusy(false);
      }
    }
  };
  const snapshot = snapshots.find((item) => item.id === snapshotId);
  return (
    <section
      className="card statistics-card"
      aria-labelledby="statistics-heading"
    >
      <div className="statistics-heading">
        <div className="heading-with-icon">
          <BarChart3 size={20} />
          <h2 id="statistics-heading">整理与核对数据</h2>
        </div>
        <button
          type="button"
          className="text-button"
          disabled={loading || busy}
          onClick={() => setRefresh((value) => value + 1)}
        >
          <RefreshCw size={15} />
          刷新材料与历史
        </button>
      </div>
      <p className="field-hint">
        本次统计绑定已保存的草稿 v{report.version}：{report.department}，
        {report.start_date} 至 {report.end_date}
        （不含）。上方如有未保存修改，请先保存，再整理数据。
      </p>
      <p className="field-hint">
        统计会冻结材料版本、计算口径与来源位置，不调用模型。五角色协作会自动整理数据；此处供人工核对。合格报告可在协作结果或报告归档下载Markdown/PDF。
      </p>
      {loading && (
        <div className="statistics-loading" role="status">
          <Loader2 size={17} className="spin" />
          正在读取材料和统计历史…
        </div>
      )}
      {error && (
        <div className="notice error" role="alert">
          {error}
        </div>
      )}
      <Issues items={issues} />
      <form onSubmit={run}>
        <fieldset disabled={busy || loading} className="statistics-fields">
          <legend className="sr-only">选择报告的统计材料与口径</legend>
          <div className="statistics-selection-heading">
            <h3>选择材料版本</h3>
            <span>{selected.length} / 50</span>
          </div>
          {materials.length ? (
            <div className="statistics-materials">
              {materials.map((material) => (
                <label className="statistics-material" key={material.id}>
                  <input
                    type="checkbox"
                    checked={selected.includes(material.id)}
                    disabled={
                      selected.length >= 50 && !selected.includes(material.id)
                    }
                    onChange={() => toggleMaterial(material.id)}
                  />
                  <span>
                    <strong>{material.name}</strong>
                    <small>
                      {kindLabel(material.kind)} · v{material.version} ·{" "}
                      {material.row_count} 条记录
                    </small>
                  </span>
                </label>
              ))}
            </div>
          ) : (
            !loading && (
              <p className="field-hint">
                材料库为空。请先到“材料库”导入并确认材料，再回到这份报告刷新。
              </p>
            )
          )}
          <div className="statistics-selection-heading">
            <h3>统计范围</h3>
            <button
              type="button"
              className="text-button"
              onClick={() => setCustomGroups(false)}
            >
              按材料类别选择
            </button>
          </div>
          <div className="statistics-groups">
            {(Object.keys(groups) as StatisticsGroup[]).map((group) => (
              <label key={group}>
                <input
                  type="checkbox"
                  checked={effectiveGroups.includes(group)}
                  onChange={() => toggleGroup(group)}
                />
                {groups[group]}
              </label>
            ))}
          </div>
          {effectiveGroups.includes("attendance") && (
            <div className="statistics-attendance">
              <p className="field-hint">
                不填写以下两项时，只统计材料样本；整体出勤率和覆盖率未定义。只有明确人员与排班日期后，才能核对完整覆盖范围。
              </p>
              <div className="statistics-attendance-fields">
                <label className="field">
                  应出勤人员编号<span className="optional-label">选填</span>
                  <textarea
                    rows={3}
                    value={roster}
                    onChange={(event) => setRoster(event.target.value)}
                    placeholder="逗号或换行分隔，例如：DEMO-E01, DEMO-E02"
                  />
                </label>
                <label className="field">
                  排班日期<span className="optional-label">选填</span>
                  <textarea
                    rows={3}
                    value={dates}
                    onChange={(event) => setDates(event.target.value)}
                    placeholder="每行一个日期，例如：2026-06-29"
                  />
                </label>
              </div>
            </div>
          )}
          <div className="statistics-actions">
            <span className="field-hint">
              只读原始材料，结果保存为独立统计快照。
            </span>
            <button
              className="button primary"
              type="submit"
              disabled={
                !selected.length || !effectiveGroups.length || busy || loading
              }
            >
              {busy ? (
                <Loader2 size={16} className="spin" />
              ) : (
                <BarChart3 size={16} />
              )}
              {busy ? "正在核对数据…" : "整理并核对数据"}
            </button>
          </div>
        </fieldset>
      </form>
      {snapshots.length > 0 && (
        <div className="statistics-history">
          <label className="field">
            统计历史
            <select
              value={snapshotId}
              onChange={(event) => setSnapshotId(event.target.value)}
            >
              {snapshots.map((item) => (
                <option key={item.id} value={item.id}>
                  {time(item.created_at)} · 草稿 v{item.report_version}
                  {item.report_version !== report.version ? " · 旧草稿" : ""}
                </option>
              ))}
            </select>
          </label>
          {snapshot && (
            <Snapshot snapshot={snapshot} version={report.version} />
          )}
        </div>
      )}
    </section>
  );
}
