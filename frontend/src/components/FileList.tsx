import React, { useState } from "react";

import { UploadedFileDto } from "../types";

const DAY = 24 * 60 * 60 * 1000;

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function expiryText(expiryTime: string): string {
  const days = Math.ceil((new Date(expiryTime).getTime() - Date.now()) / DAY);
  return days < 0 ? "已过期" : `${days} 天后过期`;
}

export interface FileListProps {
  files: UploadedFileDto[];
  onDelete: (fileId: string) => void;
  onRefresh: () => void;
}

export const FileList: React.FC<FileListProps> = ({ files, onDelete, onRefresh }) => {
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);

  return (
    <div className="file-list">
      <button type="button" onClick={onRefresh}>
        刷新
      </button>
      <table>
        <thead>
          <tr>
            <th>文件名</th>
            <th>大小</th>
            <th>类型</th>
            <th>行数</th>
            <th>列数</th>
            <th>上传时间</th>
            <th>过期时间</th>
            <th>使用情况</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          {files.map((file) => (
            <tr key={file.id}>
              <td>{file.filename}</td>
              <td>{formatSize(file.file_size)}</td>
              <td>{file.file_type}</td>
              <td>{file.row_count ?? "-"}</td>
              <td>{file.column_count ?? "-"}</td>
              <td>{file.upload_time.slice(0, 10)}</td>
              <td>{expiryText(file.expiry_time)}</td>
              <td>
                {file.usage
                  ? `${file.usage.datasources} 数据源 · ${file.usage.charts} 图表`
                  : "-"}
              </td>
              <td>
                <button type="button" onClick={() => setPendingDelete(file.id)}>
                  删除
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {pendingDelete && (
        <div role="dialog" className="delete-confirm">
          <p>将同时删除关联的数据源，确定删除该文件吗？</p>
          <button
            type="button"
            onClick={() => {
              onDelete(pendingDelete);
              setPendingDelete(null);
            }}
          >
            确认删除
          </button>
          <button type="button" onClick={() => setPendingDelete(null)}>
            取消
          </button>
        </div>
      )}
    </div>
  );
};
