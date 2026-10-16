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
  status: "draft";
  created_at: string;
  updated_at: string;
}
export interface SystemInfo {
  version: string;
  model_configured: boolean;
  capabilities: string[];
}
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
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
        "Content-Type": "application/json",
        "X-Workspace": workspace,
        ...options.headers,
      },
    });
    if (!response.ok) {
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
