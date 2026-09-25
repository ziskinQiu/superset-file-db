import { ApiError } from "../types";

// REST API base path (plan naming lock): extension APIs mount at /extensions/<publisher>/<name>
export const API_BASE = "/extensions/my-org/file-db";

function csrfToken(): string {
  const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]*)/);
  return match ? decodeURIComponent(match[1]) : "";
}

async function unwrap(resp: Response): Promise<any> {
  if (resp.status === 204) {
    return null;
  }
  const payload = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    const message = payload?.message ?? payload?.error ?? resp.statusText;
    throw new ApiError(resp.status, message);
  }
  return payload && typeof payload === "object" && "result" in payload
    ? payload.result
    : payload;
}

export class ApiClient {
  async get(path: string): Promise<any> {
    return this.request("GET", path);
  }

  async post(path: string, body?: unknown): Promise<any> {
    return this.request("POST", path, body);
  }

  async put(path: string, body?: unknown): Promise<any> {
    return this.request("PUT", path, body);
  }

  async del(path: string): Promise<any> {
    return this.request("DELETE", path);
  }

  async putBinary(path: string, data: Blob): Promise<any> {
    const resp = await fetch(API_BASE + path, {
      method: "PUT",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/octet-stream",
        "X-CSRFToken": csrfToken(),
      },
      body: data,
    });
    return unwrap(resp);
  }

  private async request(method: string, path: string, body?: unknown): Promise<any> {
    const headers: Record<string, string> = { "X-CSRFToken": csrfToken() };
    const init: RequestInit = { method, credentials: "same-origin", headers };
    if (body !== undefined) {
      headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(body);
    }
    return unwrap(await fetch(API_BASE + path, init));
  }
}
