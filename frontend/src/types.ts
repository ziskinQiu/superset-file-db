/** DTOs mirroring the backend service JSON (my_org.file_db.services). */

export type FileType = "csv" | "excel";
export type ColumnType = "string" | "integer" | "float" | "datetime" | "boolean";

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export interface SheetDto {
  id: string;
  name: string;
  index: number;
  row_count: number | null;
  column_count: number | null;
  selected: boolean;
}

export interface UploadedFileDto {
  id: string;
  filename: string;
  file_size: number;
  file_type: FileType;
  status: string;
  created_by: string;
  upload_time: string;
  expiry_time: string;
  row_count: number | null;
  column_count: number | null;
  sheet_count: number;
  encoding: string | null;
  delimiter: string | null;
  sheets?: SheetDto[];
  usage?: UsageDto;
}

export interface UsageDto {
  datasources: number;
  charts: number;
  dashboards: number;
}

export interface ColumnDto {
  id: string;
  name: string;
  type: ColumnType;
  format: string | null;
  is_user_defined: boolean;
  sample_values: string[];
}

export interface PreviewColumnDto {
  name: string;
  type: ColumnType;
  format?: string | null;
}

export type CellValue = string | number | boolean | null;

export interface PreviewDto {
  columns: PreviewColumnDto[];
  rows: CellValue[][];
  totalRows: number;
}

export interface FileConfigDto {
  datasource_name?: string;
  description?: string;
  sheets?: number[];
  delimiter?: string;
  encoding?: string;
}

export interface UploadInitDto {
  upload_id: string;
  chunk_size: number;
  total_chunks: number;
}

export interface UploadStatusDto {
  upload_id: string;
  filename: string;
  file_type: FileType;
  total_size: number;
  chunk_size: number;
  total_chunks: number;
  received_chunks: number[];
  status: string;
}

export interface DatasourceDto {
  id: string;
  datasource_id: number;
  datasource_name: string;
  sheet_id: string | null;
  created_at: string;
}

export interface CreatedDatasourceDto {
  datasource_id: number;
  name: string;
  sheet_index: number | null;
}

export interface ConnectionDto {
  id: number;
  name: string;
}

export interface ChangeLogDto {
  column_name: string;
  old_type: string;
  new_type: string;
  old_format: string | null;
  new_format: string | null;
  changed_by: string;
  changed_at: string;
}

export interface NotificationDto {
  file_id: string;
  filename: string;
  expiry_time: string;
  days_left: number;
}
