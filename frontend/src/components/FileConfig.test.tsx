import { fireEvent, render, screen } from "@testing-library/react";
import React from "react";
import { describe, expect, it, vi } from "vitest";

import { FileConfig } from "./FileConfig";

const SHEETS = [
  { id: "s0", name: "销售数据", index: 0, row_count: 3, column_count: 2, selected: false },
  { id: "s1", name: "明细", index: 1, row_count: 1, column_count: 1, selected: false },
];

describe("FileConfig", () => {
  it("emits live values through onChange without saving", () => {
    const onChange = vi.fn();
    render(<FileConfig fileId="f1" fileType="csv" onChange={onChange} onSave={() => undefined} />);

    fireEvent.change(screen.getByLabelText("数据源名称"), { target: { value: "DS1" } });
    expect(onChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ datasource_name: "DS1" })
    );
  });

  it("requires a datasource name before saving", () => {
    const onSave = vi.fn();
    render(<FileConfig fileId="f1" fileType="csv" onSave={onSave} />);

    const button = screen.getByRole("button", { name: "保存配置" });
    expect(button).toBeDisabled();
    expect(screen.getByText("请填写数据源名称")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("数据源名称"), { target: { value: "Sales" } });
    expect(button).toBeEnabled();
  });

  it("renders csv delimiter and encoding options", () => {
    render(<FileConfig fileId="f1" fileType="csv" onSave={() => undefined} />);

    const delimiter = screen.getByLabelText("分隔符");
    for (const label of ["逗号", "分号", "制表符", "竖线", "空格"]) {
      expect(delimiter.textContent).toContain(label);
    }
    const encoding = screen.getByLabelText("编码");
    for (const option of ["utf-8", "gbk", "gb2312", "latin-1"]) {
      expect(encoding.textContent).toContain(option);
    }
  });

  it("supports multi-select sheets for excel with initial state", () => {
    const onSave = vi.fn();
    render(
      <FileConfig
        fileId="f1"
        fileType="excel"
        sheets={SHEETS}
        initial={{ datasource_name: "E", sheets: [0] }}
        onSave={onSave}
      />
    );

    const boxes = screen.getAllByRole("checkbox") as HTMLInputElement[];
    expect(boxes).toHaveLength(2);
    expect(boxes[0].checked).toBe(true);
    expect(boxes[1].checked).toBe(false);

    fireEvent.click(boxes[1]);
    fireEvent.click(screen.getByRole("button", { name: "保存配置" }));
    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({ datasource_name: "E", sheets: [0, 1] })
    );
  });

  it("prefills fields from initial and sends them back", () => {
    const onSave = vi.fn();
    render(
      <FileConfig
        fileId="f1"
        fileType="csv"
        initial={{ datasource_name: "Sales", description: "desc", delimiter: ";", encoding: "gbk" }}
        onSave={onSave}
      />
    );

    expect(screen.getByLabelText("数据源名称")).toHaveValue("Sales");
    expect(screen.getByLabelText("描述")).toHaveValue("desc");
    expect(screen.getByLabelText("分隔符")).toHaveValue(";");
    expect(screen.getByLabelText("编码")).toHaveValue("gbk");

    fireEvent.click(screen.getByRole("button", { name: "保存配置" }));
    expect(onSave).toHaveBeenCalledWith({
      datasource_name: "Sales",
      description: "desc",
      delimiter: ";",
      encoding: "gbk",
      sheets: [],
    });
  });
});
