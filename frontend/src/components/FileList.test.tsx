import { fireEvent, render, screen } from "@testing-library/react";
import React from "react";
import { describe, expect, it, vi } from "vitest";

import { FileList } from "./FileList";
import { UploadedFileDto } from "../types";

const DAY = 24 * 60 * 60 * 1000;

function fileOf(overrides: Partial<UploadedFileDto> = {}): UploadedFileDto {
  return {
    id: "f1",
    filename: "a.csv",
    file_size: 1234,
    file_type: "csv",
    status: "active",
    created_by: "u1",
    upload_time: "2026-09-25T10:00:00",
    expiry_time: new Date(Date.now() + 3 * DAY).toISOString(),
    row_count: 10,
    column_count: 2,
    sheet_count: 1,
    encoding: "utf-8",
    delimiter: ",",
    usage: { datasources: 1, charts: 2, dashboards: 1 },
    ...overrides,
  };
}

describe("FileList", () => {
  it("renders file rows with usage and expiry countdown", () => {
    render(<FileList files={[fileOf()]} onDelete={() => undefined} onRefresh={() => undefined} />);

    const row = screen.getByText("a.csv").closest("tr")!;
    expect(row.textContent).toContain("csv");
    expect(row.textContent).toContain("10");
    expect(row.textContent).toContain("1 数据源");
    expect(row.textContent).toContain("2 图表");
    expect(row.textContent).toContain("3 天后过期");
  });

  it("asks for confirmation before deleting", () => {
    const onDelete = vi.fn();
    render(<FileList files={[fileOf()]} onDelete={onDelete} onRefresh={() => undefined} />);

    fireEvent.click(screen.getByRole("button", { name: "删除" }));
    expect(screen.getByText(/将同时删除关联的数据源/)).toBeInTheDocument();
    expect(onDelete).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "确认删除" }));
    expect(onDelete).toHaveBeenCalledWith("f1");
  });

  it("cancels deletion without calling onDelete", () => {
    const onDelete = vi.fn();
    render(<FileList files={[fileOf()]} onDelete={onDelete} onRefresh={() => undefined} />);

    fireEvent.click(screen.getByRole("button", { name: "删除" }));
    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    expect(onDelete).not.toHaveBeenCalled();
    expect(screen.queryByText(/将同时删除关联的数据源/)).not.toBeInTheDocument();
  });

  it("refreshes via the refresh button", () => {
    const onRefresh = vi.fn();
    render(<FileList files={[]} onDelete={() => undefined} onRefresh={onRefresh} />);

    fireEvent.click(screen.getByRole("button", { name: "刷新" }));
    expect(onRefresh).toHaveBeenCalledTimes(1);
  });
});
