import React, { useCallback, useEffect, useRef, useState } from "react";
import { useDropzone } from "react-dropzone";

import { UploadManager } from "../upload/UploadManager";

const ACCEPT = {
  "text/csv": [".csv"],
  "application/vnd.ms-excel": [".xls"],
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [".xlsx"],
};
const MAX_CSV_BYTES = 150 * 1024 * 1024;
const MAX_EXCEL_BYTES = 500 * 1024 * 1024;
const FILENAME_MAX_LEN = 255;
const FILENAME_RE = /^[A-Za-z0-9\u4e00-\u9fa5 ._\-()]+$/;

function validateFile(file: File): string | null {
  const lower = file.name.toLowerCase();
  const isCsv = lower.endsWith(".csv");
  const isExcel = lower.endsWith(".xls") || lower.endsWith(".xlsx");
  if (!isCsv && !isExcel) {
    return `${file.name}: 只支持 CSV 或 Excel 文件`;
  }
  if (file.name.length > FILENAME_MAX_LEN) {
    return `${file.name}: 文件名不能超过 ${FILENAME_MAX_LEN} 个字符`;
  }
  if (!FILENAME_RE.test(file.name)) {
    return `${file.name}: 文件名包含不允许的字符`;
  }
  const maxSize = isCsv ? MAX_CSV_BYTES : MAX_EXCEL_BYTES;
  if (file.size > maxSize) {
    return `${file.name}: 超出大小限制`;
  }
  return null;
}

export interface FileUploadProps {
  manager: UploadManager;
  onUploaded: (fileId: string) => void;
  onError: (msg: string) => void;
}

interface ProgressEntry {
  name: string;
  percent: number;
}

export const FileUpload: React.FC<FileUploadProps> = ({ manager, onUploaded, onError }) => {
  const [progress, setProgress] = useState<Record<string, ProgressEntry>>({});
  const callbacks = useRef({ onUploaded, onError });
  callbacks.current = { onUploaded, onError };

  useEffect(() => {
    const prev = manager.events;
    manager.events = {
      ...prev,
      onProgress: (clientId, percent) => {
        prev.onProgress?.(clientId, percent);
        setProgress((p) => ({
          ...p,
          [clientId]: { name: p[clientId]?.name ?? clientId, percent },
        }));
      },
      onFileDone: (clientId, serverFileId) => {
        prev.onFileDone?.(clientId, serverFileId);
        callbacks.current.onUploaded(serverFileId);
      },
      onFileError: (clientId, message) => {
        prev.onFileError?.(clientId, message);
        callbacks.current.onError(message);
      },
    };
  }, [manager]);

  const onDrop = useCallback(
    (accepted: File[]) => {
      for (const file of accepted) {
        const error = validateFile(file);
        if (error) {
          onError(error);
          continue;
        }
        const clientId = manager.enqueue(file);
        setProgress((p) => ({ ...p, [clientId]: { name: file.name, percent: 0 } }));
      }
    },
    [manager, onError]
  );

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: ACCEPT,
    multiple: true,
  });

  return (
    <div>
      <div {...getRootProps({ className: "file-upload-dropzone" })}>
        <input {...getInputProps()} />
        {isDragActive ? <p>拖放文件到这里...</p> : <p>拖放CSV或Excel文件到这里，或点击选择文件</p>}
      </div>
      <div className="file-upload-progress">
        {Object.entries(progress).map(([clientId, entry]) => (
          <div key={clientId} className="file-upload-progress-item">
            <span className="file-upload-progress-name">{entry.name}</span>
            <span className="file-upload-progress-pct">{entry.percent}%</span>
            <div className="file-upload-progress-bar">
              <div style={{ width: `${entry.percent}%` }} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};
