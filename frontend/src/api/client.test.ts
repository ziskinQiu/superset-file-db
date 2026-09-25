import { afterEach, describe, expect, it, vi } from "vitest";

import { API_BASE, ApiClient } from "./client";
import { ApiError } from "../types";

function mockFetch(status: number, body?: unknown) {
  const fn = vi.fn(async (_url: string, _init?: RequestInit) => ({
    ok: status >= 200 && status < 300,
    status,
    statusText: "ERR",
    json: async () => body,
  }));
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => {
  vi.unstubAllGlobals();
  document.cookie = "csrftoken=; expires=Thu, 01 Jan 1970 00:00:00 GMT";
});

describe("ApiClient", () => {
  it("builds URL, method and JSON body", async () => {
    const fn = mockFetch(200, { result: { ok: 1 } });
    const out = await new ApiClient().post("/upload/init", { a: 1 });

    expect(fn).toHaveBeenCalledWith(
      `${API_BASE}/upload/init`,
      expect.objectContaining({
        method: "POST",
        credentials: "same-origin",
        body: JSON.stringify({ a: 1 }),
      })
    );
    expect(out).toEqual({ ok: 1 }); // unwraps {"result": ...}
  });

  it("injects the CSRF header from cookie", async () => {
    document.cookie = "csrftoken=abc";
    const fn = mockFetch(200, { result: [] });

    await new ApiClient().get("/files");

    const init = fn.mock.calls[0][1] as RequestInit;
    expect((init.headers as Record<string, string>)["X-CSRFToken"]).toBe("abc");
    expect(init.method).toBe("GET");
  });

  it("returns null on 204", async () => {
    mockFetch(204);
    expect(await new ApiClient().del("/files/f1")).toBeNull();
  });

  it("throws ApiError with status and message on non-2xx", async () => {
    mockFetch(403, { message: "denied" });
    const err = await new ApiClient().get("/files").catch((e) => e);

    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(403);
    expect(err.message).toBe("denied");
  });

  it("putBinary sends a Blob with octet-stream", async () => {
    const fn = mockFetch(200, { result: { received_chunks: [0] } });
    const blob = new Blob([new Uint8Array([1, 2, 3])]);

    const out = await new ApiClient().putBinary("/upload/up1/chunks/0", blob);

    const init = fn.mock.calls[0][1] as RequestInit;
    expect(init.body).toBe(blob);
    expect((init.headers as Record<string, string>)["Content-Type"]).toBe(
      "application/octet-stream"
    );
    expect(out).toEqual({ received_chunks: [0] });
  });
});
