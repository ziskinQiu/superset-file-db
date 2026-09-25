import { ApiClient } from "../api/client";
import { FileType, UploadInitDto } from "../types";

export type UploadEvents = {
  onProgress?: (clientFileId: string, percent: number) => void;
  onFileDone?: (clientFileId: string, serverFileId: string) => void;
  onFileError?: (clientFileId: string, message: string) => void;
  onQueueChange?: (activeCount: number) => void;
};

type TaskState = "queued" | "uploading" | "done" | "error" | "cancelled";

interface UploadTask {
  id: string;
  file: File;
  state: TaskState;
  uploadId?: string;
}

const DEFAULT_CONCURRENCY = 3;
const MAX_CHUNK_RETRIES = 3;
const DEFAULT_RETRY_DELAY_MS = 500;

function fileTypeOf(name: string): FileType {
  return /\.xlsx?$/i.test(name) ? "excel" : "csv";
}

export class UploadManager {
  events: UploadEvents;

  private readonly api: ApiClient;
  private readonly concurrency: number;
  private readonly retryDelayMs: number;
  private readonly queue: UploadTask[] = [];
  private readonly tasks = new Map<string, UploadTask>();
  private active = 0;
  private seq = 0;

  constructor(
    api: ApiClient,
    events: UploadEvents = {},
    opts: { concurrency?: number; retryDelayMs?: number } = {}
  ) {
    this.api = api;
    this.events = events;
    this.concurrency = opts.concurrency ?? DEFAULT_CONCURRENCY;
    this.retryDelayMs = opts.retryDelayMs ?? DEFAULT_RETRY_DELAY_MS;
  }

  get activeCount(): number {
    return this.active;
  }

  enqueue(file: File): string {
    const id = `f${++this.seq}`;
    const task: UploadTask = { id, file, state: "queued" };
    this.tasks.set(id, task);
    this.queue.push(task);
    this.pump();
    return id;
  }

  cancel(clientFileId: string): void {
    const task = this.tasks.get(clientFileId);
    if (!task || task.state === "done" || task.state === "error" || task.state === "cancelled") {
      return;
    }
    task.state = "cancelled";
    const queuedIndex = this.queue.indexOf(task);
    if (queuedIndex >= 0) {
      this.queue.splice(queuedIndex, 1);
    }
    if (task.uploadId) {
      void this.api.post(`/upload/${task.uploadId}/abort`).catch(() => undefined);
    }
    if (queuedIndex >= 0) {
      this.events.onQueueChange?.(this.active);
    }
  }

  private pump(): void {
    while (this.active < this.concurrency && this.queue.length > 0) {
      const task = this.queue.shift()!;
      this.active++;
      this.events.onQueueChange?.(this.active);
      void this.run(task).finally(() => {
        this.active--;
        this.events.onQueueChange?.(this.active);
        this.pump();
      });
    }
  }

  private isCancelled(task: UploadTask): boolean {
    return task.state === "cancelled";
  }

  private async run(task: UploadTask): Promise<void> {
    task.state = "uploading";
    try {
      const total = task.file.size;
      let lastPercent = -1;
      const emitProgress = (percent: number) => {
        if (percent !== lastPercent) {
          lastPercent = percent;
          this.events.onProgress?.(task.id, percent);
        }
      };
      const init = (await this.api.post("/upload/init", {
        filename: task.file.name,
        file_type: fileTypeOf(task.file.name),
        total_size: total,
      })) as UploadInitDto;
      task.uploadId = init.upload_id;
      if (this.isCancelled(task)) {
        return;
      }
      emitProgress(0);

      let uploaded = 0;
      for (let index = 0; index < init.total_chunks; index++) {
        if (this.isCancelled(task)) {
          return;
        }
        const start = index * init.chunk_size;
        const chunk = task.file.slice(start, Math.min(start + init.chunk_size, total));
        await this.withRetry(() =>
          this.api.putBinary(`/upload/${init.upload_id}/chunks/${index}`, chunk)
        );
        uploaded += chunk.size;
        emitProgress(Math.min(100, Math.floor((uploaded / total) * 100)));
      }

      if (this.isCancelled(task)) {
        return;
      }
      const done = (await this.api.post(`/upload/${init.upload_id}/complete`)) as {
        file_id: string;
      };
      emitProgress(100);
      task.state = "done";
      this.events.onFileDone?.(task.id, done.file_id);
    } catch (err) {
      if (this.isCancelled(task)) {
        return;
      }
      task.state = "error";
      this.events.onFileError?.(task.id, err instanceof Error ? err.message : String(err));
    }
  }

  private async withRetry<T>(fn: () => Promise<T>): Promise<T> {
    let lastError: unknown;
    for (let attempt = 0; attempt <= MAX_CHUNK_RETRIES; attempt++) {
      try {
        return await fn();
      } catch (err) {
        lastError = err;
        if (attempt < MAX_CHUNK_RETRIES) {
          await new Promise((resolve) => setTimeout(resolve, this.retryDelayMs * 2 ** attempt));
        }
      }
    }
    throw lastError;
  }
}
