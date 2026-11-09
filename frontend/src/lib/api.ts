import type {
  AuthConfig,
  DashboardStats,
  ProjectDetail,
  ProjectSummary,
  ReplicationRequest,
  OutputTarget,
  User,
} from "@/types";

const BASE = "/api";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) msg = body.detail;
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, msg);
  }
  return res.json() as Promise<T>;
}

export const api = {
  // Auth
  authConfig: () => req<AuthConfig>("/auth/config"),
  me: () => req<User>("/auth/me"),
  devLogin: () => req<User>("/auth/dev-login", { method: "POST" }),
  logout: () => req<{ ok: boolean }>("/auth/logout", { method: "POST" }),
  googleLoginUrl: () => `${BASE}/auth/google/login`,

  dashboard: () => req<DashboardStats>("/dashboard"),
  listProjects: () => req<ProjectSummary[]>("/projects"),
  getProject: (id: string) => req<ProjectDetail>(`/projects/${id}`),
  startReplication: (payload: ReplicationRequest) =>
    req<{ job_id: string; project_id: string; status: string }>("/replicate", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  cancel: (id: string) => req<{ cancelled: boolean }>(`/projects/${id}/cancel`, { method: "POST" }),
  remove: (id: string) => req<{ deleted: boolean }>(`/projects/${id}`, { method: "DELETE" }),
  downloadUrl: (id: string, target: OutputTarget = "static") =>
    `${BASE}/projects/${id}/download?target=${target}`,
  rerun: (id: string) => req<{ status: string }>(`/projects/${id}/rerun`, { method: "POST" }),
  addOutputs: (id: string, targets: OutputTarget[]) =>
    req<{ status: string }>(`/projects/${id}/outputs`, { method: "POST", body: JSON.stringify({ targets }) }),
  siteUrl: (id: string, path = "") => `${BASE}/projects/${id}/site/${path}`,
  screenshotUrl: (id: string, relPath: string) =>
    `${BASE}/projects/${id}/screenshots/${relPath.split("/").pop()}`,
};
