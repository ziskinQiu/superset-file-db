import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { registrations } from "./testUtils/supersetCore";

const DAY = 24 * 60 * 60 * 1000;

function mockFetchByPath() {
  const fn = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    const ok = (result: unknown) => ({
      ok: true,
      status: 200,
      statusText: "OK",
      json: async () => ({ result }),
    });
    if (url.includes("/notifications")) return ok([]);
    if (url.includes("/usage")) return ok({ datasources: 0, charts: 0, dashboards: 0 });
    if (url.endsWith("/files")) {
      return ok([
        {
          id: "f1",
          filename: "a.csv",
          file_size: 10,
          file_type: "csv",
          status: "active",
          created_by: "u1",
          upload_time: "2026-09-25T10:00:00",
          expiry_time: new Date(Date.now() + 3 * DAY).toISOString(),
          row_count: 2,
          column_count: 2,
          sheet_count: 1,
          encoding: "utf-8",
          delimiter: ",",
        },
      ]);
    }
    return ok({});
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("FileDbPanel", () => {
  it("registers the extension view on import", async () => {
    await import("./index");
    expect(registrations[0][0]).toEqual({ id: "my-org.file-db.panel", name: "文件数据库" });
    expect(registrations[0][1]).toBe("sqllab.panels");
  });

  it("requires a datasource name before creating datasets", async () => {
    mockFetchByPath();
    const { FileDbPanel } = await import("./index");
    render(<FileDbPanel />);

    fireEvent.click(screen.getByRole("button", { name: "配置" }));
    const createBtn = screen.getByRole("button", { name: "创建数据源" });
    expect(createBtn).toBeDisabled();

    fireEvent.change(screen.getByLabelText("数据源名称"), { target: { value: "DS1" } });
    expect(createBtn).toBeEnabled(); // live form values reach the create action
  });

  it("switches tabs and wires the file list", async () => {
    mockFetchByPath();
    const { FileDbPanel } = await import("./index");
    render(<FileDbPanel />);

    // upload tab is active first
    expect(await screen.findByText("拖放CSV或Excel文件到这里，或点击选择文件")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "管理" }));
    expect(await screen.findByText("a.csv")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "配置" }));
    expect(screen.getByText("文件配置")).toBeInTheDocument();
  });
});
