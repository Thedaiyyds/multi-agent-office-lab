import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import {
  Check,
  Download,
  FileText,
  FolderOpen,
  Loader2,
  Plus,
  RefreshCw,
  Search,
  Upload,
  X,
} from "lucide-react";
import {
  api,
  ApiError,
  downloadMaterial,
  type ImportDraft,
  type MaterialIssue,
  type MaterialKind,
  type MaterialPreview,
  type MaterialVersion,
  type Workspace,
} from "./api";
import type { Confirm } from "./confirm";

const kinds: Record<MaterialKind, string> = {
  projects: "项目进度",
  attendance: "人员考勤",
  achievements: "成果统计",
  satisfaction: "服务满意度",
  notes: "文字说明",
};
const fields: Record<MaterialKind, Record<string, string>> = {
  projects: {
    project_id: "项目编号",
    department: "部门",
    effective_date: "业务生效日期",
    snapshot_date: "快照日期",
    status: "项目状态",
    progress: "进度百分比",
  },
  attendance: {
    person_id: "人员编号",
    department: "部门",
    date: "日期",
    planned_hours: "计划工时",
    actual_hours: "实际工时",
  },
  achievements: {
    achievement_id: "成果编号",
    department: "部门",
    date: "日期",
    category: "成果类别",
    name: "成果名称",
  },
  satisfaction: {
    feedback_id: "反馈编号",
    department: "部门",
    date: "日期",
    score: "评分",
    scale_min: "量表下限",
    scale_max: "量表上限",
  },
  notes: {},
};
const optionalFields: Partial<Record<MaterialKind, Record<string, string>>> = {
  projects: { completed_date: "完成日期" },
  attendance: {
    leave_hours: "请假工时",
    absent_hours: "缺勤工时",
    late_minutes: "迟到分钟",
  },
  achievements: { project_id: "关联项目编号" },
  satisfaction: { valid: "反馈有效标记" },
};
const mappingFields = (draft: ImportDraft) => ({
  ...fields[draft.kind],
  ...Object.fromEntries(
    Object.entries(optionalFields[draft.kind] || {}).filter(
      ([canonical, label]) =>
        draft.columns.includes(canonical) ||
        draft.columns.includes(label) ||
        Boolean(draft.suggested_mapping[canonical]),
    ),
  ),
});
const describe = (error: unknown) =>
  error instanceof Error ? error.message : "操作未完成，请重试。";
const sourceName = (source: ImportDraft["source"]) =>
  ({ file: "本地文件", local_api: "模拟接口", demo: "演示案例" })[source];

function Issues({ issues }: { issues: MaterialIssue[] }) {
  if (!issues.length) return null;
  return (
    <div className="material-issues" aria-label="材料校验问题">
      <h3>校验提示 · {issues.length} 项</h3>
      <ul>
        {issues.map((issue, index) => (
          <li key={`${issue.location}-${index}`} className={issue.severity}>
            <span>{issue.severity === "error" ? "错误" : "提醒"}</span>
            <strong>{issue.location}</strong>
            {issue.message}
          </li>
        ))}
      </ul>
    </div>
  );
}
function Preview({
  columns,
  rows,
  count,
}: {
  columns: string[];
  rows: MaterialPreview[];
  count: number;
}) {
  return (
    <div className="material-preview">
      <div className="preview-caption">
        <h3>内容预览</h3>
        <span>
          共 {count} 条 · 展示前 {rows.length} 条
        </span>
      </div>
      {rows.length ? (
        <div
          className="table-scroll"
          tabIndex={0}
          role="region"
          aria-label="材料预览，可横向滚动"
        >
          <table>
            <thead>
              <tr>
                <th>来源位置</th>
                {columns.map((column) => (
                  <th key={column}>{column}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, index) => (
                <tr key={`${row.location}-${index}`}>
                  <th>{row.location}</th>
                  {columns.map((column) => (
                    <td key={column}>{String(row.values[column] ?? "")}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="field-hint">没有可预览的内容，请检查材料格式。</p>
      )}
    </div>
  );
}
export function DemoMaterials({
  workspace,
  navigate,
  onSaving,
}: {
  workspace: Workspace;
  navigate: (path: string) => void;
  onSaving: (value: boolean) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [catalog, setCatalog] = useState<{
    title: string;
    request: string;
    files: { name: string; kind: MaterialKind }[];
  } | null>(null);
  const alive = useRef(true);
  const lock = useRef(false);
  useEffect(() => {
    alive.current = true;
    if (workspace === "demo")
      api<typeof catalog>("/demo/catalog", workspace)
        .then((result) => {
          if (alive.current) setCatalog(result);
        })
        .catch((reason) => {
          if (alive.current) setError(describe(reason));
        });
    return () => {
      alive.current = false;
      onSaving(false);
    };
  }, [workspace, onSaving]);
  if (workspace !== "demo") return null;
  const load = async () => {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    onSaving(true);
    setError("");
    try {
      await api("/demo/load", workspace, { method: "POST" });
      if (alive.current) {
        onSaving(false);
        navigate("/materials");
      }
    } catch (reason) {
      if (alive.current) setError(describe(reason));
    } finally {
      lock.current = false;
      onSaving(false);
      if (alive.current) setBusy(false);
    }
  };
  return (
    <section className="card help-card demo-material-card">
      <div className="heading-with-icon">
        <FolderOpen size={21} />
        <h2>技术部季度汇报演示材料</h2>
      </div>
      <p>
        {catalog?.request ||
          "加载技术部季度案例的项目、考勤、成果及文字说明材料。"}
      </p>
      {catalog && (
        <ul className="demo-file-list">
          {catalog.files.map((file) => (
            <li key={file.name}>
              <FileText size={14} />
              <span>{file.name}</span>
              <small>{kinds[file.kind]}</small>
            </li>
          ))}
        </ul>
      )}
      <p>
        点击后材料仅写入演示空间；重复加载会复用相同版本。你也可以在材料库自行上传
        TXT、CSV、DOCX，体验预览、字段映射和校验。
      </p>
      {error && (
        <div className="notice error" role="alert">
          {error}
        </div>
      )}
      <button className="button primary" onClick={load} disabled={busy}>
        {busy ? <Loader2 size={17} className="spin" /> : <Plus size={17} />}
        {busy ? "正在加载…" : "加载演示材料"}
      </button>
      <div className="notice">
        当前 alpha.2
        可演示材料接入与草稿保存；五角色协作和报告导出将按后续版本开放。该操作不调用模型。
      </div>
    </section>
  );
}
export default function Materials({
  workspace,
  onDirty,
  onSaving,
  confirm,
}: {
  workspace: Workspace;
  onDirty: (value: boolean) => void;
  onSaving: (value: boolean) => void;
  confirm: Confirm;
}) {
  const [items, setItems] = useState<MaterialVersion[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("");
  const [uploading, setUploading] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [kind, setKind] = useState<MaterialKind>("projects");
  const [department, setDepartment] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [draft, setDraft] = useState<ImportDraft | null>(null);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [issues, setIssues] = useState<MaterialIssue[]>([]);
  const [selected, setSelected] = useState<MaterialVersion | null>(null);
  const [busy, setBusy] = useState(false);
  const alive = useRef(true);
  const lock = useRef(false);
  const detailRequest = useRef(0);
  const dirty =
    uploading && Boolean(file || draft || department || start || end);
  useEffect(() => {
    onDirty(dirty);
    return () => onDirty(false);
  }, [dirty, onDirty]);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      detailRequest.current += 1;
      onSaving(false);
    };
  }, [onSaving]);
  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const result = await api<{ items: MaterialVersion[] }>(
        "/materials",
        workspace,
      );
      if (alive.current) setItems(result.items);
    } catch (reason) {
      if (alive.current) setError(describe(reason));
    } finally {
      if (alive.current) setLoading(false);
    }
  }, [workspace]);
  useEffect(() => {
    void refresh();
  }, [refresh]);
  const startImport = async () => {
    if (busy) return;
    if (
      dirty &&
      !(await confirm(
        "重新选择材料会放弃当前尚未确认的导入设置。",
        "重新导入材料？",
        "重新选择",
      ))
    )
      return;
    detailRequest.current += 1;
    setUploading(true);
    setFile(null);
    setDraft(null);
    setSelected(null);
    setDepartment("");
    setStart("");
    setEnd("");
    setMapping({});
    setIssues([]);
    setError("");
    setSuccess("");
  };
  const cancelImport = async () => {
    if (
      dirty &&
      !(await confirm(
        "当前材料尚未确认入库。关闭将放弃页面中的导入设置，原始文件不会改变。",
        "取消本次导入？",
        "放弃导入",
      ))
    )
      return;
    setUploading(false);
    setFile(null);
    setDraft(null);
    setIssues([]);
    setError("");
    onDirty(false);
  };
  const runImport = async (event?: FormEvent, fromApi = false) => {
    event?.preventDefault();
    if (lock.current || (!file && !fromApi)) return;
    if (
      file &&
      !fromApi &&
      (!/\.(txt|csv|docx)$/i.test(file.name) || file.size > 10 * 1024 * 1024)
    ) {
      setError("请选择 TXT、CSV 或 DOCX 文件，单个文件不超过 10 MiB。");
      return;
    }
    lock.current = true;
    setBusy(true);
    onSaving(true);
    setError("");
    setIssues([]);
    setSuccess("");
    try {
      const body = new FormData();
      if (file) body.append("file", file);
      body.append("kind", kind);
      body.append("department", department.trim());
      body.append("start_date", start);
      body.append("end_date", end);
      const result = await api<ImportDraft>(
        fromApi ? "/materials/from-demo-api" : "/materials/import",
        workspace,
        {
          method: "POST",
          body: fromApi ? JSON.stringify({ kind }) : body,
        },
      );
      if (!alive.current) return;
      setUploading(true);
      setDraft(result);
      setKind(result.kind);
      setDepartment(result.department || department);
      setStart(result.start_date || start);
      setEnd(result.end_date || end);
      setMapping(result.suggested_mapping);
      setIssues(result.issues);
    } catch (reason) {
      if (alive.current) {
        setError(describe(reason));
        if (reason instanceof ApiError) setIssues(reason.issues);
      }
    } finally {
      lock.current = false;
      onSaving(false);
      if (alive.current) setBusy(false);
    }
  };
  const confirmImport = async (event: FormEvent) => {
    event.preventDefault();
    if (!draft || lock.current) return;
    if (Object.keys(fields[draft.kind]).some((field) => !mapping[field])) {
      setError("请为所有必需字段选择来源列。");
      return;
    }
    if (draft.kind === "notes" && (!department.trim() || !start || !end)) {
      setError("文字说明需要确认所属部门与起止日期。");
      return;
    }
    if ((start && !end) || (!start && end) || (start && end && start >= end)) {
      setError("请填写完整的日期范围，结束日期须晚于开始日期且不包含当天。");
      return;
    }
    lock.current = true;
    try {
      if (
        items.some(
          (item) => item.name === draft.name && item.kind === draft.kind,
        ) &&
        !(await confirm(
          "该分类下已有同名材料。系统将按内容和映射核对：相同内容复用原版本，修改后的内容保存为新版本，历史版本保留。",
          "确认材料版本",
          "确认入库",
        ))
      )
        return;
      setBusy(true);
      onSaving(true);
      setError("");
      setIssues([]);
      const result = await api<MaterialVersion>(
        `/imports/${encodeURIComponent(draft.id)}/confirm`,
        workspace,
        {
          method: "POST",
          body: JSON.stringify({
            mapping: Object.fromEntries(
              Object.entries(mapping).filter(([, column]) => Boolean(column)),
            ),
            department: department.trim(),
            start_date: start,
            end_date: end,
          }),
        },
      );
      if (!alive.current) return;
      const duplicate = items.some((item) => item.id === result.id);
      setSelected(result);
      setDraft(null);
      setFile(null);
      setUploading(false);
      onDirty(false);
      setSuccess(
        duplicate
          ? `相同内容及设置已入库，复用已有版本 v${result.version}，没有新增重复材料。`
          : `材料已确认入库 · v${result.version}。原始文件与映射记录已保存。`,
      );
      await refresh();
    } catch (reason) {
      if (alive.current) {
        setError(describe(reason));
        if (reason instanceof ApiError) setIssues(reason.issues);
      }
    } finally {
      lock.current = false;
      onSaving(false);
      if (alive.current) setBusy(false);
    }
  };
  const open = async (material: MaterialVersion) => {
    if (busy) return;
    if (
      dirty &&
      !(await confirm(
        "打开材料详情会放弃本次尚未确认的导入设置。",
        "查看已入库材料？",
        "查看材料",
      ))
    )
      return;
    const sequence = ++detailRequest.current;
    setUploading(false);
    setFile(null);
    setDraft(null);
    setSelected(null);
    setIssues([]);
    setError("");
    onDirty(false);
    try {
      const result = await api<MaterialVersion>(
        `/materials/${encodeURIComponent(material.id)}`,
        workspace,
      );
      if (alive.current && sequence === detailRequest.current)
        setSelected(result);
    } catch (reason) {
      if (alive.current && sequence === detailRequest.current)
        setError(describe(reason));
    }
  };
  const download = async () => {
    if (!selected || lock.current) return;
    lock.current = true;
    setBusy(true);
    onSaving(true);
    try {
      await downloadMaterial(selected.id, selected.name, workspace);
    } catch (reason) {
      if (alive.current) setError(describe(reason));
    } finally {
      lock.current = false;
      onSaving(false);
      if (alive.current) setBusy(false);
    }
  };
  const filtered = items.filter(
    (item) =>
      (!filter || item.kind === filter) &&
      `${item.name} ${item.department}`
        .toLowerCase()
        .includes(search.toLowerCase()),
  );
  return (
    <>
      <div className="page-heading">
        <div>
          <div className="eyebrow">MATERIAL LIBRARY</div>
          <h1>材料库</h1>
          <p>整理原始材料，确认数据来源，为工作汇报做好准备。</p>
        </div>
        <button
          className="button primary"
          onClick={startImport}
          disabled={busy}
        >
          <Upload size={17} />
          导入材料
        </button>
      </div>
      {error && (
        <div className="notice error" role="alert">
          {error}
        </div>
      )}
      {success && (
        <div className="notice success" role="status">
          <Check size={17} />
          {success}
        </div>
      )}
      {uploading && (
        <section className="card material-import">
          <div className="material-section-heading">
            <div>
              <h2>{draft ? "确认材料与字段" : "导入原始材料"}</h2>
              <p>
                {draft
                  ? "检查预览与定位信息，确认后保存不可变材料版本。"
                  : "支持 TXT、CSV、DOCX，单个文件不超过 10 MiB。"}
              </p>
            </div>
            <button
              className="icon-button"
              aria-label="关闭导入"
              onClick={cancelImport}
              disabled={busy}
            >
              <X size={19} />
            </button>
          </div>
          <form onSubmit={draft ? confirmImport : (event) => runImport(event)}>
            <fieldset disabled={busy}>
              {!draft && (
                <div className="material-file-zone">
                  <Upload size={25} />
                  <label className="field">
                    选择本地文件
                    <input
                      type="file"
                      accept=".txt,.csv,.docx"
                      onChange={(event) =>
                        setFile(event.target.files?.[0] || null)
                      }
                    />
                  </label>
                  <p>
                    CSV / DOCX 表格用于结构化数据；TXT 或 DOCX
                    正文可归类为文字说明。项目进度按 0–100 填写。
                  </p>
                </div>
              )}
              <div className="material-metadata">
                <label className="field">
                  材料分类
                  <select
                    value={kind}
                    disabled={Boolean(draft)}
                    onChange={(event) =>
                      setKind(event.target.value as MaterialKind)
                    }
                  >
                    {Object.entries(kinds).map(([value, label]) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="field">
                  所属部门{" "}
                  <span className="optional-label">
                    {kind === "notes" ? "必填" : "选填，可由数据列提供"}
                  </span>
                  <input
                    maxLength={80}
                    value={department}
                    onChange={(event) => setDepartment(event.target.value)}
                    placeholder="填写材料所属部门"
                  />
                </label>
                <label className="field">
                  开始日期
                  <input
                    type="date"
                    value={start}
                    onChange={(event) => setStart(event.target.value)}
                  />
                </label>
                <label className="field">
                  结束日期 <span className="optional-label">不含当日</span>
                  <input
                    type="date"
                    value={end}
                    onChange={(event) => setEnd(event.target.value)}
                  />
                </label>
              </div>
              {draft && (
                <>
                  <div className="material-facts">
                    <strong>{draft.name}</strong>
                    <span>
                      {sourceName(draft.source)} ·{" "}
                      {draft.byte_size.toLocaleString()} 字节
                    </span>
                    <code>SHA-256: {draft.sha256}</code>
                  </div>
                  {Object.keys(fields[draft.kind]).length > 0 && (
                    <div className="mapping-block">
                      <h3>字段映射</h3>
                      <p>
                        选择原始列名；每个必需字段都需要对应的来源列，系统将校验日期、数值与业务记录。项目进度统一采用
                        0–100；可选字段无需强制映射。
                      </p>
                      <div className="mapping-grid">
                        {Object.entries(mappingFields(draft)).map(
                          ([canonical, label]) => (
                            <label className="field" key={canonical}>
                              {label}
                              {!(canonical in fields[draft.kind]) && (
                                <span className="optional-label">选填</span>
                              )}
                              <span className="mapping-code">{canonical}</span>
                              <select
                                required={canonical in fields[draft.kind]}
                                value={mapping[canonical] || ""}
                                onChange={(event) =>
                                  setMapping((previous) => ({
                                    ...previous,
                                    [canonical]: event.target.value,
                                  }))
                                }
                              >
                                <option value="">请选择来源列</option>
                                {draft.columns.map((column) => (
                                  <option key={column} value={column}>
                                    {column}
                                  </option>
                                ))}
                              </select>
                            </label>
                          ),
                        )}
                      </div>
                    </div>
                  )}
                  <Preview
                    columns={draft.columns}
                    rows={draft.preview}
                    count={draft.row_count}
                  />
                </>
              )}
              <Issues issues={issues} />
              <div className="material-form-actions">
                <span>
                  {busy
                    ? "正在处理材料…"
                    : draft
                      ? "确认前，材料不会加入正式材料列表。"
                      : "上传仅解析文件，不会调用模型。"}
                </span>
                <div>
                  <button
                    type="button"
                    className="button secondary"
                    onClick={cancelImport}
                  >
                    取消
                  </button>
                  <button
                    className="button primary"
                    type="submit"
                    disabled={!draft && !file}
                  >
                    {busy ? (
                      <Loader2 size={17} className="spin" />
                    ) : draft ? (
                      <Check size={17} />
                    ) : (
                      <Upload size={17} />
                    )}
                    {draft ? "确认入库" : "上传并预览"}
                  </button>
                </div>
              </div>
            </fieldset>
          </form>
          {!draft && workspace === "demo" && (
            <div className="demo-api-import">
              <span>也可以使用演示空间的本地模拟接口</span>
              <button
                className="button secondary"
                disabled={busy || kind === "notes"}
                onClick={() => runImport(undefined, true)}
              >
                从模拟接口导入 {kind === "notes" ? "（请选择数据分类）" : ""}
              </button>
            </div>
          )}
        </section>
      )}
      <section className="card material-library">
        <div className="list-toolbar">
          <label className="search-field">
            <Search size={17} />
            <span className="sr-only">搜索材料名称或部门</span>
            <input
              placeholder="搜索材料名称或部门"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
          </label>
          <label className="material-filter">
            <span className="sr-only">按材料分类筛选</span>
            <select
              value={filter}
              onChange={(event) => setFilter(event.target.value)}
            >
              <option value="">全部分类</option>
              {Object.entries(kinds).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <span className="list-count">{filtered.length} 个版本</span>
          <button
            className="icon-button"
            onClick={() => {
              setError("");
              void refresh();
            }}
            aria-label="刷新材料列表"
            disabled={loading || busy}
          >
            <RefreshCw size={17} className={loading ? "spin" : ""} />
          </button>
        </div>
        {loading ? (
          <div className="loading-panel" role="status">
            <Loader2 size={22} className="spin" />
            正在读取材料…
          </div>
        ) : filtered.length ? (
          <div className="material-rows">
            {filtered.map((item) => (
              <button
                className={`material-row ${selected?.id === item.id ? "selected" : ""}`}
                key={item.id}
                onClick={() => open(item)}
                disabled={busy}
              >
                <span className="document-icon">
                  <FileText size={21} />
                </span>
                <span className="material-row-content">
                  <strong>{item.name}</strong>
                  <span>
                    {kinds[item.kind]} · {item.department || "部门见数据列"} ·{" "}
                    {item.row_count} 条 · {sourceName(item.source)}
                  </span>
                  <small>
                    {new Date(item.created_at).toLocaleString("zh-CN", {
                      hour12: false,
                    })}
                  </small>
                </span>
                <span className="status-badge">v{item.version}</span>
              </button>
            ))}
          </div>
        ) : (
          <div className="empty-state compact">
            <div className="empty-icon">
              <FolderOpen size={28} />
            </div>
            <h3>
              {search || filter ? "没有匹配的材料" : "汇报从可靠的材料开始"}
            </h3>
            <p>
              {search || filter
                ? "尝试其他名称或分类。"
                : "上传项目、考勤或成果资料，预览并确认后会保存在这里。"}
            </p>
            {!search && !filter && (
              <div className="empty-actions">
                <button className="button secondary" onClick={startImport}>
                  <Plus size={17} />
                  导入第一份材料
                </button>
              </div>
            )}
          </div>
        )}
        {filtered.length > 0 && (
          <p className="material-history-note">
            同名、同分类材料的新内容保留为新版本；以下列表包含历史版本。相同内容和导入设置会复用已有记录。
          </p>
        )}
      </section>
      {selected && !uploading && (
        <section className="card material-detail">
          <div className="material-section-heading">
            <div>
              <h2>{selected.name}</h2>
              <p>
                {kinds[selected.kind]} · 版本 {selected.version} ·{" "}
                {sourceName(selected.source)}
              </p>
            </div>
            <button
              className="button secondary"
              disabled={busy}
              onClick={download}
            >
              <Download size={16} />
              下载原始材料
            </button>
          </div>
          <div className="material-facts">
            <span>
              部门：{selected.department || "由数据列提供"} · 范围：
              {selected.start_date || "由数据列提供"} →{" "}
              {selected.end_date || "由数据列提供"}
              {selected.end_date ? "（不含结束日）" : ""}
            </span>
            <code>SHA-256: {selected.sha256}</code>
          </div>
          {Object.keys(selected.mapping).length > 0 && (
            <div className="confirmed-mapping">
              {Object.entries(selected.mapping).map(([canonical, column]) => (
                <span key={canonical}>
                  {fields[selected.kind][canonical] ||
                    optionalFields[selected.kind]?.[canonical] ||
                    canonical}
                  <strong>{column}</strong>
                </span>
              ))}
            </div>
          )}
          <Preview
            columns={selected.columns}
            rows={selected.preview}
            count={selected.row_count}
          />
          <Issues issues={selected.issues} />
        </section>
      )}
    </>
  );
}
