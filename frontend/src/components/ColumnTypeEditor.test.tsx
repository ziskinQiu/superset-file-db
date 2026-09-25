import { fireEvent, render, screen } from "@testing-library/react";
import React from "react";
import { describe, expect, it, vi } from "vitest";

import { ColumnTypeEditor } from "./ColumnTypeEditor";

const COLUMNS = [
  {
    id: "c1",
    name: "amount",
    type: "float" as const,
    format: null,
    is_user_defined: false,
    sample_values: ["1.5", "2.0"],
  },
  {
    id: "c2",
    name: "day",
    type: "string" as const,
    format: null,
    is_user_defined: false,
    sample_values: ["2026-09-25"],
  },
];

describe("ColumnTypeEditor", () => {
  it("shows the format input only for datetime columns", () => {
    render(<ColumnTypeEditor columns={COLUMNS} onUpdate={() => undefined} onImport={() => undefined} />);

    expect(screen.queryByPlaceholderText("%Y-%m-%d")).not.toBeInTheDocument();

    fireEvent.change(screen.getAllByRole("combobox")[1], { target: { value: "datetime" } });
    expect(screen.getByPlaceholderText("%Y-%m-%d")).toBeInTheDocument();
  });

  it("calls onUpdate only for changed rows", () => {
    const onUpdate = vi.fn();
    render(<ColumnTypeEditor columns={COLUMNS} onUpdate={onUpdate} onImport={() => undefined} />);

    fireEvent.change(screen.getAllByRole("combobox")[1], { target: { value: "datetime" } });
    fireEvent.change(screen.getByPlaceholderText("%Y-%m-%d"), { target: { value: "%Y/%m/%d" } });
    fireEvent.click(screen.getByRole("button", { name: "保存列类型" }));

    expect(onUpdate).toHaveBeenCalledTimes(1);
    expect(onUpdate).toHaveBeenCalledWith("c2", "datetime", "%Y/%m/%d");
  });

  it("renders sample values and the five type options", () => {
    render(<ColumnTypeEditor columns={COLUMNS} onUpdate={() => undefined} onImport={() => undefined} />);

    expect(screen.getByText("1.5")).toBeInTheDocument();
    const select = screen.getAllByRole("combobox")[0];
    for (const value of ["string", "integer", "float", "datetime", "boolean"]) {
      expect(select.querySelector(`option[value="${value}"]`)).not.toBeNull();
    }
  });

  it("imports JSON config and shows parse errors", () => {
    const onImport = vi.fn();
    render(<ColumnTypeEditor columns={COLUMNS} onUpdate={() => undefined} onImport={onImport} />);

    fireEvent.change(screen.getByRole("textbox"), { target: { value: "{bad json" } });
    fireEvent.click(screen.getByRole("button", { name: "导入 JSON" }));
    expect(screen.getByRole("alert")).toHaveTextContent("JSON");
    expect(onImport).not.toHaveBeenCalled();

    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: '{"columns": [{"name": "amount", "type": "integer"}]}' },
    });
    fireEvent.click(screen.getByRole("button", { name: "导入 JSON" }));
    expect(onImport).toHaveBeenCalledTimes(1);
  });

  it("shows change history in a collapsible panel", () => {
    render(
      <ColumnTypeEditor
        columns={COLUMNS}
        onUpdate={() => undefined}
        onImport={() => undefined}
        history={[
          {
            column_name: "amount",
            old_type: "string",
            new_type: "float",
            old_format: null,
            new_format: null,
            changed_by: "u1",
            changed_at: "2026-09-25T10:00:00",
          },
        ]}
      />
    );

    fireEvent.click(screen.getByText("修改历史"));
    const panel = screen.getByText("修改历史").closest("details")!;
    expect(panel.textContent).toContain("amount: string → float");
    expect(panel.textContent).toContain("u1");
  });
});
