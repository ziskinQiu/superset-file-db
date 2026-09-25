import { fireEvent, render, screen } from "@testing-library/react";
import React from "react";
import { describe, expect, it, vi } from "vitest";

import { DataPreview } from "./DataPreview";

const DATA = {
  columns: [
    { name: "id", type: "integer" as const },
    { name: "name", type: "string" as const },
  ],
  rows: [
    [1, "alice"],
    [2, null],
  ],
  totalRows: 150,
};

const SHEETS = [
  { id: "s0", name: "S0", index: 0, row_count: 2, column_count: 2, selected: true },
  { id: "s1", name: "S1", index: 1, row_count: 1, column_count: 1, selected: false },
];

describe("DataPreview", () => {
  it("renders headers, type badges and rows with '-' for empty cells", () => {
    render(<DataPreview fileId="f1" data={DATA} />);

    expect(screen.getByText("数据预览")).toBeInTheDocument();
    expect(screen.getByText("显示前 2 行，共 150 行")).toBeInTheDocument();
    expect(screen.getByText("id")).toBeInTheDocument();
    expect(screen.getByText("integer")).toBeInTheDocument();
    expect(screen.getByText("alice")).toBeInTheDocument();
    expect(screen.getAllByText("-")).toHaveLength(1);
  });

  it("shows sheet tabs with active highlight and click callback", () => {
    const onSheetChange = vi.fn();
    render(
      <DataPreview
        fileId="f1"
        data={DATA}
        sheets={SHEETS}
        sheetIndex={0}
        onSheetChange={onSheetChange}
      />
    );

    expect(screen.getByText("S0").closest("button")).toHaveClass("active");
    fireEvent.click(screen.getByText("S1"));
    expect(onSheetChange).toHaveBeenCalledWith(1);
  });

  it("renders loading and error states", () => {
    const { rerender } = render(<DataPreview fileId="f1" data={DATA} loading />);
    expect(screen.getByText("加载中...")).toBeInTheDocument();

    rerender(<DataPreview fileId="f1" data={DATA} error="boom" />);
    expect(screen.getByText(/boom/)).toBeInTheDocument();
  });
});
