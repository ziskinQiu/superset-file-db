import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { describe, expect, it, vi } from "vitest";

import { FileUpload } from "./FileUpload";

function mockManager() {
  return {
    events: {} as Record<string, (...args: any[]) => void>,
    enqueue: vi.fn((file: File) => `f${file.name}`),
    cancel: vi.fn(),
    activeCount: 0,
  } as any;
}

function dropFile(root: HTMLElement, file: File) {
  fireEvent.drop(root, {
    dataTransfer: {
      files: [file],
      items: [{ kind: "file", type: file.type, getAsFile: () => file }],
      types: ["Files"],
    },
  });
}

function fileOf(name: string, size: number): File {
  const file = new File([new Uint8Array(1)], name);
  Object.defineProperty(file, "size", { value: size });
  return file;
}

describe("FileUpload", () => {
  it("shows dropzone copy and switches to drag-active copy", async () => {
    const manager = mockManager();
    const { container } = render(
      <FileUpload manager={manager} onUploaded={() => undefined} onError={() => undefined} />
    );

    expect(screen.getByText("拖放CSV或Excel文件到这里，或点击选择文件")).toBeInTheDocument();

    const root = container.querySelector(".file-upload-dropzone") as HTMLElement;
    fireEvent.dragEnter(root, { dataTransfer: { types: ["Files"], files: [] } });
    // react-dropzone dispatches drag state asynchronously
    expect(await screen.findByText("拖放文件到这里...")).toBeInTheDocument();

    fireEvent.dragLeave(root, { dataTransfer: { types: ["Files"], files: [] } });
    expect(await screen.findByText("拖放CSV或Excel文件到这里，或点击选择文件")).toBeInTheDocument();
  });

  it("rejects oversized csv via onError and does not enqueue", async () => {
    const manager = mockManager();
    const onError = vi.fn();
    const { container } = render(
      <FileUpload manager={manager} onUploaded={() => undefined} onError={onError} />
    );

    dropFile(
      container.querySelector(".file-upload-dropzone") as HTMLElement,
      fileOf("big.csv", 151 * 1024 * 1024)
    );

    await waitFor(() =>
      expect(onError).toHaveBeenCalledWith(expect.stringContaining("big.csv"))
    );
    expect(manager.enqueue).not.toHaveBeenCalled();
  });

  it("rejects illegal filenames and enqueues valid files", async () => {
    const manager = mockManager();
    const onError = vi.fn();
    const { container } = render(
      <FileUpload manager={manager} onUploaded={() => undefined} onError={onError} />
    );
    const root = container.querySelector(".file-upload-dropzone") as HTMLElement;

    dropFile(root, fileOf("bad;name.csv", 10));
    await waitFor(() => expect(onError).toHaveBeenCalledTimes(1));
    expect(manager.enqueue).not.toHaveBeenCalled();

    dropFile(root, fileOf("ok.csv", 10));
    await waitFor(() => expect(manager.enqueue).toHaveBeenCalledTimes(1));
  });

  it("renders per-file progress and reports uploaded files", () => {
    const manager = mockManager();
    const onUploaded = vi.fn();
    render(<FileUpload manager={manager} onUploaded={onUploaded} onError={() => undefined} />);

    const file = fileOf("ok.csv", 10);
    dropFile(screen.getByText("拖放CSV或Excel文件到这里，或点击选择文件").closest(
      ".file-upload-dropzone"
    ) as HTMLElement, file);

    manager.events.onProgress("fok.csv", 40);
    expect(screen.getByText("40%")).toBeInTheDocument();

    manager.events.onFileDone("fok.csv", "server-1");
    expect(onUploaded).toHaveBeenCalledWith("server-1");
  });
});
