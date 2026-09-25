import React from "react";

import { PreviewDto, SheetDto } from "../types";

export interface DataPreviewProps {
  fileId: string;
  data: PreviewDto;
  columnTypes?: Record<string, { type: string; format?: string }>;
  sheetIndex?: number;
  onSheetChange?: (i: number) => void;
  sheets?: SheetDto[];
  loading?: boolean;
  error?: string;
}

export const DataPreview: React.FC<DataPreviewProps> = ({
  fileId,
  data,
  columnTypes,
  sheetIndex,
  onSheetChange,
  sheets,
  loading,
  error,
}) => {
  if (error) {
    return <div className="data-preview data-preview-error">数据预览加载失败：{error}</div>;
  }
  if (loading) {
    return <div className="data-preview data-preview-loading">加载中...</div>;
  }
  return (
    <div className="data-preview">
      <h3>数据预览</h3>
      <p>
        显示前 {data.rows.length} 行，共 {data.totalRows} 行
      </p>
      {sheets && onSheetChange && (
        <div className="data-preview-sheets">
          {sheets.map((sheet) => (
            <button
              key={sheet.id}
              type="button"
              className={sheet.index === sheetIndex ? "active" : ""}
              onClick={() => onSheetChange(sheet.index)}
            >
              {sheet.name}
            </button>
          ))}
        </div>
      )}
      <div className="preview-table-container">
        <table>
          <thead>
            <tr>
              {data.columns.map((col) => (
                <th key={col.name}>
                  <div className="column-header">
                    <span className="column-name">{col.name}</span>
                    <span className="column-type">
                      {columnTypes?.[col.name]?.type ?? col.type}
                    </span>
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.rows.map((row, rowIdx) => (
              <tr key={rowIdx}>
                {row.map((cell, cellIdx) => (
                  <td key={cellIdx}>{cell === null || cell === undefined ? "-" : String(cell)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};
