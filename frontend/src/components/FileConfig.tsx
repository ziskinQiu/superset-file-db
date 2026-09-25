import React, { useEffect, useMemo, useRef, useState } from "react";

import { ColumnDto, FileConfigDto, SheetDto } from "../types";

const DELIMITERS = [
  { value: ",", label: "逗号 (,)" },
  { value: ";", label: "分号 (;)" },
  { value: "\t", label: "制表符" },
  { value: "|", label: "竖线 (|)" },
  { value: " ", label: "空格" },
];

const ENCODINGS = ["utf-8", "gbk", "gb2312", "latin-1"];

export interface FileConfigProps {
  fileId: string;
  fileType: "csv" | "excel";
  sheets?: SheetDto[];
  columns?: ColumnDto[];
  initial?: FileConfigDto;
  onChange?: (cfg: FileConfigDto) => void;
  onSave: (cfg: FileConfigDto) => void;
}

export const FileConfig: React.FC<FileConfigProps> = ({
  fileId,
  fileType,
  sheets,
  initial,
  onChange,
  onSave,
}) => {
  const [name, setName] = useState(initial?.datasource_name ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [delimiter, setDelimiter] = useState(initial?.delimiter ?? ",");
  const [encoding, setEncoding] = useState(initial?.encoding ?? "utf-8");
  const [selected, setSelected] = useState<number[]>(initial?.sheets ?? []);

  const currentCfg: FileConfigDto = useMemo(
    () => ({
      datasource_name: name,
      description,
      delimiter,
      encoding,
      sheets: [...selected].sort((a, b) => a - b),
    }),
    [name, description, delimiter, encoding, selected]
  );
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;
  useEffect(() => {
    onChangeRef.current?.(currentCfg);
  }, [currentCfg]);

  const toggleSheet = (index: number) => {
    setSelected((prev) =>
      prev.includes(index) ? prev.filter((i) => i !== index) : [...prev, index]
    );
  };

  const save = () => {
    onSave(currentCfg);
  };

  return (
    <div className="file-config">
      <h3>文件配置</h3>

      <div className="config-field">
        <label htmlFor="file-config-name">数据源名称</label>
        <input
          id="file-config-name"
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        {!name.trim() && <div className="config-hint">请填写数据源名称</div>}
      </div>

      <div className="config-field">
        <label htmlFor="file-config-desc">描述</label>
        <input
          id="file-config-desc"
          type="text"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
      </div>

      {fileType === "excel" && sheets && (
        <div className="config-field">
          <span>工作表</span>
          {sheets.map((sheet) => (
            <label key={sheet.id}>
              <input
                type="checkbox"
                checked={selected.includes(sheet.index)}
                onChange={() => toggleSheet(sheet.index)}
              />
              {sheet.name}（{sheet.row_count ?? 0} 行 × {sheet.column_count ?? 0} 列）
            </label>
          ))}
        </div>
      )}

      {fileType === "csv" && (
        <>
          <div className="config-field">
            <label htmlFor="file-config-delimiter">分隔符</label>
            <select
              id="file-config-delimiter"
              value={delimiter}
              onChange={(e) => setDelimiter(e.target.value)}
            >
              {DELIMITERS.map((d) => (
                <option key={d.value} value={d.value}>
                  {d.label}
                </option>
              ))}
            </select>
          </div>

          <div className="config-field">
            <label htmlFor="file-config-encoding">编码</label>
            <select
              id="file-config-encoding"
              value={encoding}
              onChange={(e) => setEncoding(e.target.value)}
            >
              {ENCODINGS.map((enc) => (
                <option key={enc} value={enc}>
                  {enc}
                </option>
              ))}
            </select>
          </div>
        </>
      )}

      <button type="button" onClick={save} disabled={!name.trim()}>
        保存配置
      </button>
    </div>
  );
};
