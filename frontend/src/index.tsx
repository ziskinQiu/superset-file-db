import React, { useCallback, useEffect, useMemo, useState } from "react";
import { views } from "@apache-superset/core";

import { ApiClient } from "./api/client";
import { ColumnTypeEditor } from "./components/ColumnTypeEditor";
import { DataPreview } from "./components/DataPreview";
import { FileConfig } from "./components/FileConfig";
import { FileList } from "./components/FileList";
import { FileUpload } from "./components/FileUpload";
import { Notifications } from "./components/Notifications";
import { UploadManager } from "./upload/UploadManager";
import {
  ChangeLogDto,
  ColumnDto,
  FileConfigDto,
  NotificationDto,
  PreviewDto,
  UploadedFileDto,
} from "./types";

type Tab = "upload" | "config" | "manage";

export const FileDbPanel: React.FC = () => {
  const [tab, setTab] = useState<Tab>("upload");
  const [files, setFiles] = useState<UploadedFileDto[]>([]);
  const [notifications, setNotifications] = useState<NotificationDto[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [current, setCurrent] = useState<UploadedFileDto | null>(null);
  const [columns, setColumns] = useState<ColumnDto[]>([]);
  const [history, setHistory] = useState<ChangeLogDto[]>([]);
  const [preview, setPreview] = useState<PreviewDto | null>(null);
  const [sheetIndex, setSheetIndex] = useState<number | undefined>(undefined);
  const [config, setConfig] = useState<FileConfigDto>({});

  const api = useMemo(() => new ApiClient(), []);
  const manager = useMemo(() => new UploadManager(api), [api]);

  const fail = useCallback((err: unknown) => {
    setError(err instanceof Error ? err.message : String(err));
  }, []);

  const refreshFiles = useCallback(async () => {
    try {
      const list: UploadedFileDto[] = await api.get("/files");
      const withUsage = await Promise.all(
        list.map(async (file) => ({
          ...file,
          usage: await api.get(`/files/${file.id}/usage`).catch(() => undefined),
        }))
      );
      setFiles(withUsage);
    } catch (err) {
      fail(err);
    }
  }, [api, fail]);

  const loadPreview = useCallback(
    async (fileId: string, index?: number) => {
      const query = index === undefined ? "" : `?sheet_index=${index}`;
      setPreview(await api.get(`/files/${fileId}/preview${query}`));
    },
    [api]
  );

  const openFile = useCallback(
    async (fileId: string) => {
      try {
        const file: UploadedFileDto = await api.get(`/files/${fileId}`);
        const cols: ColumnDto[] = await api.get(`/files/${fileId}/columns`);
        const logs: ChangeLogDto[] = await api.get(`/files/${fileId}/columns/history`);
        const firstSheet = file.sheets && file.sheets.length ? 0 : undefined;
        setCurrent(file);
        setColumns(cols);
        setHistory(logs);
        setSheetIndex(firstSheet);
        await loadPreview(fileId, firstSheet);
        setTab("config");
      } catch (err) {
        fail(err);
      }
    },
    [api, fail, loadPreview]
  );

  useEffect(() => {
    void refreshFiles();
    void api
      .get("/notifications")
      .then(setNotifications)
      .catch(() => undefined);
  }, [api, refreshFiles]);

  const saveConfig = useCallback(
    async (cfg: FileConfigDto) => {
      if (!current) return;
      setConfig(cfg);
      try {
        await api.put(`/files/${current.id}/config`, cfg);
        if (cfg.sheets && cfg.sheets.length) {
          setSheetIndex(cfg.sheets[0]);
          await loadPreview(current.id, cfg.sheets[0]);
        }
      } catch (err) {
        fail(err);
      }
    },
    [api, current, fail, loadPreview]
  );

  const createDatasources = useCallback(async () => {
    if (!current || !config.datasource_name?.trim()) return;
    try {
      await saveConfig(config); // persist sheet selection etc. before creating
      await api.post("/datasources", {
        file_id: current.id,
        sheet_indices: config.sheets ?? [],
        name: config.datasource_name,
        description: config.description,
      });
      await refreshFiles();
    } catch (err) {
      fail(err);
    }
  }, [api, config, current, fail, refreshFiles, saveConfig]);

  const updateColumn = useCallback(
    async (columnId: string, type: string, format?: string) => {
      if (!current) return;
      try {
        await api.put(`/files/${current.id}/columns/${columnId}`, { type, format });
        setColumns(await api.get(`/files/${current.id}/columns`));
        setHistory(await api.get(`/files/${current.id}/columns/history`));
      } catch (err) {
        fail(err);
      }
    },
    [api, current, fail]
  );

  const importColumns = useCallback(
    async (json: string) => {
      if (!current) return;
      await api.post(`/files/${current.id}/columns/import`, JSON.parse(json));
      setColumns(await api.get(`/files/${current.id}/columns`));
      setHistory(await api.get(`/files/${current.id}/columns/history`));
    },
    [api, current]
  );

  const deleteFile = useCallback(
    async (fileId: string) => {
      try {
        await api.del(`/files/${fileId}`);
        if (current?.id === fileId) {
          setCurrent(null);
          setPreview(null);
        }
        await refreshFiles();
      } catch (err) {
        fail(err);
      }
    },
    [api, current, fail, refreshFiles]
  );

  return (
    <div className="file-db-panel">
      {error && (
        <div role="alert" className="panel-error">
          {error}
        </div>
      )}

      <div className="panel-tabs">
        {(["upload", "config", "manage"] as Tab[]).map((id) => (
          <button
            key={id}
            type="button"
            className={id === tab ? "active" : ""}
            onClick={() => setTab(id)}
          >
            {id === "upload" ? "上传" : id === "config" ? "配置" : "管理"}
          </button>
        ))}
      </div>

      {tab === "upload" && (
        <FileUpload manager={manager} onUploaded={(fileId) => void openFile(fileId)} onError={fail} />
      )}

      {tab === "config" && (
        <div className="panel-config">
          <FileConfig
            fileId={current?.id ?? ""}
            fileType={current?.file_type ?? "csv"}
            sheets={current?.sheets}
            columns={columns}
            initial={config.datasource_name ? config : undefined}
            onChange={(cfg) => setConfig(cfg)}
            onSave={(cfg) => void saveConfig(cfg)}
          />
          <button
            type="button"
            onClick={() => void createDatasources()}
            disabled={!config.datasource_name?.trim()}
          >
            创建数据源
          </button>
          {preview && (
            <DataPreview
              fileId={current?.id ?? ""}
              data={preview}
              sheets={current?.sheets}
              sheetIndex={sheetIndex}
              onSheetChange={(i) => {
                setSheetIndex(i);
                if (current) void loadPreview(current.id, i);
              }}
            />
          )}
          <ColumnTypeEditor
            columns={columns}
            onUpdate={(columnId, type, format) => void updateColumn(columnId, type, format)}
            onImport={(json) => void importColumns(json)}
            history={history}
          />
        </div>
      )}

      {tab === "manage" && (
        <div className="panel-manage">
          <Notifications
            items={notifications}
            onDismiss={(id) => setNotifications((prev) => prev.filter((n) => n.file_id !== id))}
          />
          <FileList
            files={files}
            onDelete={(fileId) => void deleteFile(fileId)}
            onRefresh={() => void refreshFiles()}
          />
        </div>
      )}
    </div>
  );
};

views.registerView(
  { id: "my-org.file-db.panel", name: "文件数据库" },
  "sqllab.panels",
  () => <FileDbPanel />
);
