import { describe, expect, it, vi } from "vitest";

import { UploadManager } from "./UploadManager";

function makeFile(bytes: number, name = "a.csv"): File {
  return new File([new Uint8Array(bytes)], name, { type: "text/csv" });
}

function tick(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

describe("UploadManager", () => {
  it("caps concurrent uploads at 3", async () => {
    const release: Array<() => void> = [];
    let inFlight = 0;
    let maxInFlight = 0;
    const done: string[] = [];
    const api = {
      post: vi.fn(async (path: string) => {
        if (path === "/upload/init") {
          inFlight++;
          maxInFlight = Math.max(maxInFlight, inFlight);
          await new Promise<void>((resolve) => release.push(resolve));
          inFlight--;
          return { upload_id: "up", chunk_size: 4, total_chunks: 1 };
        }
        return { file_id: "sf" };
      }),
      putBinary: vi.fn(async () => ({})),
    };
    const manager = new UploadManager(api as any, {
      onFileDone: (_id) => done.push(_id),
      onQueueChange: () => undefined,
    });

    for (let i = 0; i < 5; i++) {
      manager.enqueue(makeFile(1, `f${i}.csv`));
    }
    await tick();
    expect(manager.activeCount).toBe(3);

    for (let guard = 0; guard < 200 && done.length < 5; guard++) {
      while (release.length) release.shift()!();
      await tick();
    }

    expect(done).toHaveLength(5);
    expect(maxInFlight).toBe(3);
  });

  it("uploads chunks in order with a smaller tail chunk", async () => {
    const calls: Array<{ path: string; size: number }> = [];
    const api = {
      post: vi.fn(async (path: string) => {
        if (path === "/upload/init") {
          return { upload_id: "up1", chunk_size: 10, total_chunks: 3 };
        }
        return { file_id: "sf1" };
      }),
      putBinary: vi.fn(async (path: string, blob: Blob) => {
        calls.push({ path, size: blob.size });
        return {};
      }),
    };
    const manager = new UploadManager(api as any, {});
    manager.enqueue(makeFile(25)); // 2.5 chunks

    for (let guard = 0; guard < 50 && calls.length + 0 < 3; guard++) await tick();
    await tick();

    expect(calls.map((c) => c.path)).toEqual([
      "/upload/up1/chunks/0",
      "/upload/up1/chunks/1",
      "/upload/up1/chunks/2",
    ]);
    expect(calls.map((c) => c.size)).toEqual([10, 10, 5]);
  });

  it("retries a failed chunk and only re-sends the missing chunk", async () => {
    const attempts = new Map<string, number>();
    const api = {
      post: vi.fn(async (path: string) => {
        if (path === "/upload/init") return { upload_id: "up1", chunk_size: 10, total_chunks: 3 };
        return { file_id: "sf1" };
      }),
      putBinary: vi.fn(async (path: string) => {
        const n = (attempts.get(path) ?? 0) + 1;
        attempts.set(path, n);
        if (path.endsWith("/chunks/1") && n === 1) {
          throw new Error("500");
        }
        return {};
      }),
    };
    const manager = new UploadManager(api as any, {}, { retryDelayMs: 1 });
    manager.enqueue(makeFile(30));

    for (let guard = 0; guard < 50 && !attempts.has("/upload/up1/chunks/2"); guard++) await tick();
    await tick();

    expect(attempts.get("/upload/up1/chunks/0")).toBe(1);
    expect(attempts.get("/upload/up1/chunks/1")).toBe(2); // retried once
    expect(attempts.get("/upload/up1/chunks/2")).toBe(1);
  });

  it("emits byte-based progress 0/33/66/100", async () => {
    const progress: number[] = [];
    const api = {
      post: vi.fn(async (path: string) => {
        if (path === "/upload/init") return { upload_id: "up1", chunk_size: 10, total_chunks: 3 };
        return { file_id: "sf1" };
      }),
      putBinary: vi.fn(async () => ({})),
    };
    const manager = new UploadManager(api as any, {
      onProgress: (_id, pct) => progress.push(pct),
      onFileDone: () => undefined,
    });
    manager.enqueue(makeFile(30));

    for (let guard = 0; guard < 50 && progress[progress.length - 1] !== 100; guard++) await tick();

    expect(progress).toEqual([0, 33, 66, 100]);
  });

  it("cancel stops remaining chunks, aborts the session and updates queue", async () => {
    const sent: string[] = [];
    const posted: string[] = [];
    let releaseChunk1: (() => void) | undefined;
    let managerRef: UploadManager | undefined;
    const api = {
      post: vi.fn(async (path: string) => {
        posted.push(path);
        if (path === "/upload/init") return { upload_id: "up1", chunk_size: 10, total_chunks: 3 };
        return { file_id: "sf1" };
      }),
      putBinary: vi.fn(async (path: string) => {
        sent.push(path);
        if (path.endsWith("/chunks/1")) {
          await new Promise<void>((resolve) => (releaseChunk1 = resolve));
        }
        return {};
      }),
    };
    const queueChanges: number[] = [];
    const manager = new UploadManager(
      api as any,
      {
        onQueueChange: (n) => queueChanges.push(n),
        onFileDone: () => undefined,
        onFileError: () => undefined,
      },
      { retryDelayMs: 1 }
    );
    managerRef = manager;
    manager.enqueue(makeFile(30));
    const clientId = "f1"; // first enqueued id

    for (let guard = 0; guard < 50 && !sent.includes("/upload/up1/chunks/1"); guard++) await tick();
    manager.cancel(clientId);
    releaseChunk1!();
    await tick();
    await tick();

    expect(sent).toEqual(["/upload/up1/chunks/0", "/upload/up1/chunks/1"]); // chunk 2 never sent
    expect(posted).toContain("/upload/up1/abort");
    expect(queueChanges[queueChanges.length - 1]).toBe(0); // active count settled
  });

  it("reports a terminal error after retries are exhausted", async () => {
    const errors: string[] = [];
    const api = {
      post: vi.fn(async (path: string) => {
        if (path === "/upload/init") return { upload_id: "up1", chunk_size: 10, total_chunks: 1 };
        return { file_id: "sf1" };
      }),
      putBinary: vi.fn(async () => {
        throw new Error("500");
      }),
    };
    const manager = new UploadManager(
      api as any,
      { onFileError: (_id, message) => errors.push(message) },
      { retryDelayMs: 1 }
    );
    manager.enqueue(makeFile(10));

    for (let guard = 0; guard < 50 && errors.length === 0; guard++) await tick();
    await tick();

    expect(errors).toHaveLength(1);
    expect(errors[0]).toBe("500");
    expect(api.putBinary).toHaveBeenCalledTimes(4); // 1 attempt + 3 retries
  });
});
