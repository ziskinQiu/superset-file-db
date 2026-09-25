import React, { useState } from "react";

import { ChangeLogDto, ColumnDto, ColumnType } from "../types";

const TYPE_OPTIONS: Array<{ value: ColumnType; label: string }> = [
  { value: "string", label: "字符串" },
  { value: "integer", label: "整数" },
  { value: "float", label: "浮点数" },
  { value: "datetime", label: "日期时间" },
  { value: "boolean", label: "布尔值" },
];

interface ColumnEdit {
  type: string;
  format?: string;
}

export interface ColumnTypeEditorProps {
  columns: ColumnDto[];
  onUpdate: (columnId: string, type: string, format?: string) => void;
  onImport: (json: string) => void;
  history?: ChangeLogDto[];
}

export const ColumnTypeEditor: React.FC<ColumnTypeEditorProps> = ({
  columns,
  onUpdate,
  onImport,
  history,
}) => {
  const [edits, setEdits] = useState<Record<string, ColumnEdit>>({});
  const [importText, setImportText] = useState("");
  const [importError, setImportError] = useState<string | null>(null);

  const effective = (col: ColumnDto): ColumnEdit =>
    edits[col.id] ?? { type: col.type, format: col.format ?? undefined };

  const setType = (col: ColumnDto, type: string) => {
    setEdits((prev) => ({
      ...prev,
      [col.id]: { type, format: prev[col.id]?.format ?? col.format ?? undefined },
    }));
  };

  const setFormat = (col: ColumnDto, format: string) => {
    setEdits((prev) => ({
      ...prev,
      [col.id]: { type: prev[col.id]?.type ?? col.type, format },
    }));
  };

  const saveChanges = () => {
    for (const [columnId, edit] of Object.entries(edits)) {
      onUpdate(columnId, edit.type, edit.format);
    }
  };

  const importConfig = () => {
    try {
      JSON.parse(importText);
    } catch (err) {
      setImportError(`JSON 格式无效：${err instanceof Error ? err.message : String(err)}`);
      return;
    }
    setImportError(null);
    const result = onImport(importText) as unknown as Promise<void> | void;
    if (result && typeof (result as Promise<void>).then === "function") {
      (result as Promise<void>).catch((err) =>
        setImportError(err instanceof Error ? err.message : String(err))
      );
    }
  };

  return (
    <div className="column-type-editor">
      <h4>列类型配置</h4>
      <p>系统已自动推断列类型，您可以手动调整：</p>

      <table className="column-types-table">
        <thead>
          <tr>
            <th>列名</th>
            <th>类型</th>
            <th>格式</th>
            <th>示例值</th>
          </tr>
        </thead>
        <tbody>
          {columns.map((col) => {
            const current = effective(col);
            return (
              <tr key={col.id}>
                <td>{col.name}</td>
                <td>
                  <select value={current.type} onChange={(e) => setType(col, e.target.value)}>
                    {TYPE_OPTIONS.map((opt) => (
                      <option key={opt.value} value={opt.value}>
                        {opt.label}
                      </option>
                    ))}
                  </select>
                </td>
                <td>
                  {current.type === "datetime" && (
                    <input
                      type="text"
                      placeholder="%Y-%m-%d"
                      value={current.format ?? ""}
                      onChange={(e) => setFormat(col, e.target.value)}
                    />
                  )}
                </td>
                <td>
                  <div className="sample-values">
                    {col.sample_values.slice(0, 3).map((val, idx) => (
                      <span key={idx} className="sample-value">
                        {val}
                      </span>
                    ))}
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      <button type="button" onClick={saveChanges}>
        保存列类型
      </button>

      <div className="column-import">
        <textarea
          value={importText}
          onChange={(e) => setImportText(e.target.value)}
          placeholder='{"columns": [{"name": "...", "type": "...", "format": "..."}]}'
        />
        <button type="button" onClick={importConfig}>
          导入 JSON
        </button>
        {importError && (
          <div role="alert" className="column-import-error">
            {importError}
          </div>
        )}
      </div>

      {history && history.length > 0 && (
        <details className="column-history">
          <summary>修改历史</summary>
          <ul>
            {history.map((log, idx) => (
              <li key={idx}>
                {log.column_name}: {log.old_type} → {log.new_type}（{log.changed_by}，{log.changed_at}）
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
};
