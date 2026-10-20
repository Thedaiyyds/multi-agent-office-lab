export type Workspace = "normal" | "demo";
export interface Draft {
  title: string;
  department: string;
  start_date: string;
  end_date: string;
  focus: string;
  sections: string[];
}
export interface Report extends Draft {
  id: string;
  workspace: Workspace;
  version: number;
  status: "draft" | "pending_review" | "needs_changes" | "approved";
  created_at: string;
  updated_at: string;
}
export interface SystemInfo {
  version: string;
  model_configured: boolean;
  capabilities: string[];
}
export type MaterialKind =
  "projects" | "attendance" | "achievements" | "satisfaction" | "notes";
export interface MaterialIssue {
  severity: "error" | "warning";
  location: string;
  message: string;
}
export interface MaterialPreview {
  location: string;
  values: Record<string, string>;
}
export interface ImportDraft {
  id: string;
  workspace: Workspace;
  name: string;
  kind: MaterialKind;
  source: "file" | "local_api" | "demo";
  sha256: string;
  byte_size: number;
  department: string;
  start_date: string;
  end_date: string;
  columns: string[];
  suggested_mapping: Record<string, string>;
  preview: MaterialPreview[];
  row_count: number;
  issues: MaterialIssue[];
  confirmed_material_id: string | null;
}
export interface MaterialVersion extends Omit<
  ImportDraft,
  "suggested_mapping" | "confirmed_material_id"
> {
  version: number;
  mapping: Record<string, string>;
  created_at: string;
}
export type StatisticsGroup =
  "projects" | "attendance" | "achievements" | "satisfaction";
export interface SourceRef {
  material_id: string;
  name: string;
  version: number;
  sha256: string;
  location: string;
  fields: string[];
}
export interface StatisticsMetric {
  id: string;
  label: string;
  value: number | null;
  unit: string;
  definition: string;
  source_refs: SourceRef[];
  limitations: string[];
}
export interface StatisticsSnapshot {
  id: string;
  report_id: string;
  report_version: number;
  department: string;
  start_date: string;
  end_date: string;
  policy_version: string;
  created_at: string;
  status: "ready" | "needs_input" | "invalid_data";
  material_ids: string[];
  materials: {
    id: string;
    name: string;
    kind: MaterialKind;
    version: number;
    sha256: string;
  }[];
  groups: StatisticsGroup[];
  metrics: StatisticsMetric[];
  issues: MaterialIssue[];
}
export type RunMode = "live" | "offline_mock";
export interface ReportOutline {
  groups: StatisticsGroup[];
  sections: { title: string; purpose: string; groups: StatisticsGroup[] }[];
}
export interface MaterialProfile {
  files: {
    id: string;
    name: string;
    kind: MaterialKind;
    sha256: string;
    row_count: number;
    scopes: { department: string; start_date: string; end_date: string }[];
  }[];
  scopes: { department: string; start_date: string; end_date: string }[];
}
export interface AgentRun {
  id: string;
  report_id: string | null;
  report_version: number | null;
  status:
    | "queued"
    | "running"
    | "needs_input"
    | "completed"
    | "review_failed"
    | "failed"
    | "cancelled"
    | "interrupted"
    | "awaiting_confirmation";
  stage: string;
  mode: RunMode;
  user_text: string;
  created_at?: string;
  events: {
    seq: number;
    role: string;
    event_type: string;
    message: string;
    created_at: string;
  }[];
  nodes: {
    role: string;
    inputs: unknown;
    output: unknown;
    candidate_output?: unknown;
    candidate_status?: string;
    status: string;
    revision?: number;
  }[];
  statistics?: StatisticsSnapshot | null;
  outline?: unknown;
  requirements?: Draft | null;
  material_profile?: MaterialProfile;
  plan_hash?: string;
  plan_evidence?: {
    gaps: string[];
    sections: { title: string; material_ids: string[] }[];
  };
  plan_confirmation?: {
    created_at: string;
    requirements: Draft;
    outline: ReportOutline;
  };
  request?: { planning_only?: boolean };
  draft_markdown?: string | null;
  review?: unknown;
  revision_history: unknown[];
  acceptance?: unknown;
  missing_fields: string[];
  questions: string[];
  cancel_requested: boolean;
  usage?: {
    request_budget: number;
    output_budget: number;
    request_count: number;
    reserved_output_tokens: number;
    prompt_tokens: number | null;
    completion_tokens: number | null;
    total_tokens: number | null;
    reasoning_tokens: number | null;
    mock_calls: number;
  } | null;
  error: { code: string; message: string } | null;
}
export interface Narrative {
  sections: { title: string; text: string }[];
  suggestions: string[];
}
export interface ReportRevision {
  id: string;
  workspace: Workspace;
  report_id: string;
  report_version: number;
  number: number;
  source_run_id: string | null;
  content_hash: string;
  status: "approved" | "needs_review" | "reviewing" | "needs_changes";
  mode: RunMode;
  created_at: string;
  updated_at: string;
  review_run_id: string | null;
  review: unknown;
  acceptance: unknown;
  review_error: { code: string; message: string } | null;
  current: boolean;
  artifacts: {
    format: "md" | "pdf";
    state: "missing" | "running" | "ready" | "failed";
    snapshot_hash: string;
    file_sha256: string | null;
    byte_size: number | null;
    error: string | null;
  }[];
}
export interface RevisionList {
  current_revision_id: string | null;
  report_version: number;
  items: ReportRevision[];
}
export interface RevisionDetail extends ReportRevision {
  snapshot: {
    requirements: Draft;
    mode: RunMode;
    narrative: Narrative;
    markdown: string;
    facts: StatisticsMetric[];
    notes: {
      id: string;
      text: string;
      material_id: string;
      name: string;
      version: number;
      sha256: string;
      location: string;
    }[];
  };
  review_attempts: unknown[];
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public issues: MaterialIssue[] = [],
  ) {
    super(message);
  }
}

export async function api<T>(
  path: string,
  workspace: Workspace,
  options: RequestInit = {},
): Promise<T> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 15_000);
  const cancel = () => controller.abort();
  options.signal?.addEventListener("abort", cancel, { once: true });
  if (options.signal?.aborted) controller.abort();
  try {
    const response = await fetch(`/api/v1${path}`, {
      ...options,
      signal: controller.signal,
      headers: {
        ...(options.body instanceof FormData
          ? {}
          : { "Content-Type": "application/json" }),
        "X-Workspace": workspace,
        ...options.headers,
      },
    });
    if (!response.ok) {
      if (
        path.startsWith("/materials") ||
        path.startsWith("/imports") ||
        path.startsWith("/demo") ||
        path.split("?")[0] === "/runs" ||
        path.startsWith("/runs/") ||
        /^\/reports\/[^/]+\/(?:statistics|revisions(?:\/|$))/.test(path)
      ) {
        const payload = await response.json().catch(() => null);
        const detail = payload?.detail;
        const isRun =
          path.split("?")[0] === "/runs" || path.startsWith("/runs/");
        const isStatistics = /^\/reports\/[^/]+\/statistics$/.test(path);
        const rawIssues = Array.isArray(detail?.issues) ? detail.issues : [];
        const issues = rawIssues.length
          ? rawIssues.filter(
              (issue: MaterialIssue) =>
                issue &&
                typeof issue.location === "string" &&
                typeof issue.message === "string" &&
                ["error", "warning"].includes(issue.severity),
            )
          : [];
        throw new ApiError(
          response.status,
          typeof detail?.message === "string"
            ? detail.message
            : typeof detail === "string"
              ? detail
              : Array.isArray(detail)
                ? detail
                    .map(
                      (item: { loc?: unknown[]; msg?: string }) =>
                        `${item.loc?.join(" / ") || "请求"}：${item.msg || "内容无效"}`,
                    )
                    .join("；")
                : isRun
                  ? "协作任务操作未完成，请检查需求、材料与模型配置。"
                  : path.includes("/revisions")
                    ? "报告修订操作未完成，请刷新状态并检查审核结果。"
                    : isStatistics
                      ? "数据整理未成功，请检查所选材料、人员清单与排班日期。"
                      : "材料操作未成功，请检查文件和填写内容后重试。",
          issues,
        );
      }
      if (response.status === 409)
        throw new ApiError(
          409,
          "这份草稿已在其他页面更新。请先查看最新版本，避免覆盖他人的修改。",
        );
      if (response.status === 404)
        throw new ApiError(
          404,
          "没有找到这份报告。请检查当前工作空间，或返回报告任务。",
        );
      if (response.status === 422)
        throw new ApiError(
          422,
          "内容未通过校验，请检查填写长度、起止日期和章节内容。你的输入已保留。",
        );
      throw new ApiError(
        response.status,
        "操作暂未成功，请稍后重试。你的输入已保留。",
      );
    }
    try {
      return (await response.json()) as T;
    } catch (reason) {
      if (controller.signal.aborted) throw reason;
      throw new ApiError(
        response.status,
        "服务返回了无法读取的响应，请检查服务地址后重试。你的输入已保留。",
      );
    }
  } catch (reason) {
    if (reason instanceof ApiError) throw reason;
    if (controller.signal.aborted)
      throw new ApiError(
        0,
        "服务响应超时，请稍后重试。保存结果可能已写入；重试将核对原请求，你的输入已保留。",
      );
    throw new ApiError(
      0,
      "无法连接服务，请确认本地服务已启动后重试。你的输入仍保留在页面中。",
    );
  } finally {
    window.clearTimeout(timeout);
    options.signal?.removeEventListener("abort", cancel);
  }
}

export async function downloadMaterial(
  id: string,
  name: string,
  workspace: Workspace,
) {
  return downloadFile(
    `/materials/${encodeURIComponent(id)}/download`,
    name,
    workspace,
    "无法下载原始材料，请刷新列表后重试。",
  );
}

export async function downloadReport(
  reportId: string,
  revisionId: string,
  format: "md" | "pdf",
  name: string,
  workspace: Workspace,
) {
  return downloadFile(
    `/reports/${encodeURIComponent(reportId)}/revisions/${encodeURIComponent(revisionId)}/exports/${format}`,
    name,
    workspace,
    "无法下载报告文件，请检查修订审核状态与文件生成结果后重试。",
  );
}

async function downloadFile(
  path: string,
  name: string,
  workspace: Workspace,
  failureMessage: string,
) {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 15_000);
  try {
    const response = await fetch(`/api/v1${path}`, {
      headers: { "X-Workspace": workspace },
      signal: controller.signal,
    });
    if (!response.ok) throw new ApiError(response.status, failureMessage);
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    try {
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = name;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
    } finally {
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    }
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError(0, "下载未完成，请检查本地服务连接后重试。");
  } finally {
    window.clearTimeout(timeout);
  }
}
