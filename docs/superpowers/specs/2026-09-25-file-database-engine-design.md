# Superset文件数据库引擎扩展设计文档

## 1. 概述

### 1.1 项目目标
开发一个Superset扩展，允许用户像Tableau一样拖拽上传CSV/Excel文件，并将其作为数据源用于创建报表。该扩展不修改Superset源代码，通过Superset的扩展机制实现。

### 1.2 核心需求
- 用户拖拽上传CSV/Excel文件
- 支持数据预览、Excel工作表选择、CSV分隔符配置
- 支持列类型自动推断和手动调整（schema管理）
- 文件持久化保存半年
- 支持多用户同时上传
- CSV文件最大150MB，Excel文件可能几百MB
- 不修改Superset源代码

### 1.3 技术选型
- 查询引擎：DuckDB（高性能分析型数据库）
- 存储：本地文件系统（第一版），后期扩展到Google Cloud Storage
- 元数据：复用Superset的PostgreSQL数据库
- 前端：React/TypeScript，完全独立扩展

## 2. 系统架构

### 2.1 整体架构图
```
┌─────────────────────────────────────────────────────┐
│                   Superset前端                       │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  │
│  │ 拖拽上传    │  │ 数据预览    │  │ 文件管理    │  │
│  │ 组件        │  │ 组件        │  │ 组件        │  │
│  └─────────────┘  └─────────────┘  └─────────────┘  │
└─────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────┐
│                   REST API层                         │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  │
│  │ 文件上传    │  │ 数据预览    │  │ 数据源创建  │  │
│  │ API         │  │ API         │  │ API         │  │
│  └─────────────┘  └─────────────┘  └─────────────┘  │
└─────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────┐
│                   业务逻辑层                         │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  │
│  │ 存储管理器  │  │ 元数据管理  │  │ 查询引擎    │  │
│  │             │  │             │  │             │  │
│  └─────────────┘  └─────────────┘  └─────────────┘  │
└─────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────┐
│                   数据层                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  │
│  │ 本地文件    │  │ PostgreSQL  │  │ DuckDB      │  │
│  │ 存储        │  │ 元数据      │  │ 查询引擎    │  │
│  └─────────────┘  └─────────────┘  └─────────────┘  │
└─────────────────────────────────────────────────────┘
```

### 2.2 组件说明

#### 2.2.1 前端组件
- **拖拽上传组件**：支持CSV、Excel文件拖拽上传
- **数据预览表格**：显示前100行数据，支持滚动和搜索
- **配置界面**：Excel工作表选择、CSV分隔符设置、编码选择
- **文件管理列表**：显示用户上传的文件，支持删除和过期时间显示

#### 2.2.2 REST API层
- 文件上传API：处理文件上传，返回文件ID
- 文件预览API：返回文件前100行数据
- 元数据API：返回文件列信息、工作表信息
- 数据源创建API：创建Superset数据源
- 文件管理API：列出、删除用户文件

#### 2.2.3 业务逻辑层
- **存储管理器**：抽象存储接口，支持本地文件系统和GCS
- **元数据管理**：管理文件元数据、列信息、工作表信息
- **查询引擎**：自定义SQLAlchemy方言，基于DuckDB

## 3. 详细设计

### 3.1 存储层设计

#### 3.1.1 存储接口抽象
```python
from abc import ABC, abstractmethod
from typing import BinaryIO, Optional

class StorageBackend(ABC):
    """存储后端抽象接口"""
    
    @abstractmethod
    def save_file(self, file_data: BinaryIO, user_id: str, file_id: str, filename: str) -> str:
        """保存文件，返回存储路径"""
        pass
    
    @abstractmethod
    def get_file_path(self, storage_path: str) -> str:
        """获取文件本地路径（对于本地存储直接返回，对于GCS下载到临时目录）"""
        pass
    
    @abstractmethod
    def delete_file(self, storage_path: str) -> bool:
        """删除文件"""
        pass
    
    @abstractmethod
    def file_exists(self, storage_path: str) -> bool:
        """检查文件是否存在"""
        pass
```

#### 3.1.2 本地存储实现
```python
import os
import shutil
from pathlib import Path

class LocalStorageBackend(StorageBackend):
    """本地文件系统存储"""
    
    def __init__(self, base_path: str = "/data/uploads"):
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
    
    def save_file(self, file_data: BinaryIO, user_id: str, file_id: str, filename: str) -> str:
        user_dir = self.base_path / user_id / file_id
        user_dir.mkdir(parents=True, exist_ok=True)
        file_path = user_dir / filename
        
        with open(file_path, "wb") as f:
            shutil.copyfileobj(file_data, f)
        
        return str(file_path.relative_to(self.base_path))
    
    def get_file_path(self, storage_path: str) -> str:
        return str(self.base_path / storage_path)
    
    def delete_file(self, storage_path: str) -> bool:
        file_path = self.base_path / storage_path
        if file_path.exists():
            if file_path.is_file():
                file_path.unlink()
            else:
                shutil.rmtree(file_path)
            return True
        return False
    
    def file_exists(self, storage_path: str) -> bool:
        return (self.base_path / storage_path).exists()
```

#### 3.1.3 GCS存储实现（后期扩展）
```python
class GCSStorageBackend(StorageBackend):
    """Google Cloud Storage存储"""
    
    def __init__(self, bucket_name: str, credentials_path: Optional[str] = None):
        # 初始化GCS客户端
        pass
    
    def save_file(self, file_data: BinaryIO, user_id: str, file_id: str, filename: str) -> str:
        # 上传到GCS
        pass
    
    def get_file_path(self, storage_path: str) -> str:
        # 下载到临时目录
        pass
    
    def delete_file(self, storage_path: str) -> bool:
        # 从GCS删除
        pass
    
    def file_exists(self, storage_path: str) -> bool:
        # 检查GCS文件是否存在
        pass
```

### 3.2 元数据设计

#### 3.2.1 数据库表结构
```sql
-- 上传文件表
CREATE TABLE uploaded_files (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL,
    filename VARCHAR(255) NOT NULL,
    file_size BIGINT NOT NULL,
    file_type VARCHAR(50) NOT NULL,  -- 'csv' or 'excel'
    storage_path VARCHAR(500) NOT NULL,
    upload_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expiry_time TIMESTAMP NOT NULL,
    status VARCHAR(20) DEFAULT 'active',  -- 'active', 'expired', 'deleted'
    sheet_count INTEGER DEFAULT 1,  -- Excel工作表数量
    row_count BIGINT,  -- 总行数
    column_count INTEGER,  -- 列数
    encoding VARCHAR(50) DEFAULT 'utf-8',  -- CSV编码
    delimiter VARCHAR(10) DEFAULT ',',  -- CSV分隔符
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 文件列信息表
CREATE TABLE file_columns (
    id VARCHAR(36) PRIMARY KEY,
    file_id VARCHAR(36) NOT NULL,
    column_name VARCHAR(255) NOT NULL,
    column_type VARCHAR(50) NOT NULL,  -- 'string', 'integer', 'float', 'datetime', 'boolean'
    column_format VARCHAR(100),  -- 列格式（如日期格式：'YYYY-MM-DD'）
    column_order INTEGER NOT NULL,
    is_nullable BOOLEAN DEFAULT true,
    sample_values TEXT,  -- JSON格式的示例值
    is_user_defined BOOLEAN DEFAULT false,  -- 是否用户手动定义
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (file_id) REFERENCES uploaded_files(id) ON DELETE CASCADE
);

-- Excel工作表信息表
CREATE TABLE file_sheets (
    id VARCHAR(36) PRIMARY KEY,
    file_id VARCHAR(36) NOT NULL,
    sheet_name VARCHAR(255) NOT NULL,
    sheet_index INTEGER NOT NULL,
    row_count BIGINT,
    column_count INTEGER,
    is_selected BOOLEAN DEFAULT false,  -- 用户是否选择此工作表
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (file_id) REFERENCES uploaded_files(id) ON DELETE CASCADE
);
```

#### 3.2.2 元数据管理类
```python
from datetime import datetime, timedelta
from typing import List, Optional
import uuid

class MetadataManager:
    """元数据管理器"""
    
    def __init__(self, db_session):
        self.db_session = db_session
    
    def create_file_record(self, user_id: str, filename: str, file_size: int, 
                          file_type: str, storage_path: str, **kwargs) -> str:
        """创建文件记录"""
        file_id = str(uuid.uuid4())
        expiry_time = datetime.now() + timedelta(days=180)  # 6个月过期
        
        # 插入文件记录
        # 插入列信息
        # 如果是Excel，插入工作表信息
        
        return file_id
    
    def get_file_metadata(self, file_id: str) -> Optional[dict]:
        """获取文件元数据"""
        pass
    
    def get_user_files(self, user_id: str, status: str = 'active') -> List[dict]:
        """获取用户文件列表"""
        pass
    
    def update_file_status(self, file_id: str, status: str) -> bool:
        """更新文件状态"""
        pass
    
    def update_column_type(self, file_id: str, column_id: str, column_type: str, 
                          column_format: Optional[str] = None) -> bool:
        """更新列类型和格式"""
        # 验证文件所有权
        # 验证列类型是否有效
        # 更新列类型和格式
        # 标记为用户定义
        pass
    
    def get_column_types(self, file_id: str) -> List[dict]:
        """获取文件所有列的类型信息"""
        # 返回列ID、列名、列类型、列格式等信息
        pass
    
    def delete_expired_files(self) -> List[str]:
        """删除过期文件，返回删除的文件ID列表"""
        pass
```

### 3.3 查询引擎设计

#### 3.3.1 自定义SQLAlchemy方言
```python
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
import duckdb

class FileDBDialect:
    """自定义文件数据库方言"""
    
    name = 'filedb'
    
    def create_connect_args(self, url):
        # 解析连接参数
        # 返回DuckDB连接参数
        pass
    
    def get_table_names(self, connection, schema=None, **kw):
        # 返回可用的文件数据源列表
        pass
    
    def get_columns(self, connection, table_name, schema=None, **kw):
        # 返回文件的列信息
        pass
    
    def get_view_names(self, connection, schema=None, **kw):
        # 返回视图名称
        pass
    
    def get_schema_names(self, connection, **kw):
        # 返回模式名称
        pass
```

#### 3.3.2 DuckDB查询引擎
```python
class FileQueryEngine:
    """文件查询引擎"""
    
    def __init__(self, storage_backend: StorageBackend):
        self.storage_backend = storage_backend
        self.connections = {}  # 缓存DuckDB连接
    
    def get_connection(self, file_id: str) -> duckdb.DuckDBPyConnection:
        """获取或创建DuckDB连接"""
        if file_id not in self.connections:
            conn = duckdb.connect(':memory:')
            self._register_file(conn, file_id)
            self.connections[file_id] = conn
        return self.connections[file_id]
    
    def _register_file(self, conn: duckdb.DuckDBPyConnection, file_id: str):
        """注册文件到DuckDB连接"""
        # 获取文件元数据（包括列信息）
        # 根据文件类型创建视图
        # CSV: 使用read_csv_auto
        # Excel: 先转换为Parquet，然后创建视图
        
        # 如果用户定义了列类型，应用类型转换
        # 例如：将字符串列转换为日期类型
        # 使用CAST或TRY_CAST进行类型转换
        pass
    
    def query(self, file_id: str, sql: str) -> pd.DataFrame:
        """执行查询"""
        conn = self.get_connection(file_id)
        return conn.execute(sql).fetchdf()
    
    def preview(self, file_id: str, limit: int = 100) -> pd.DataFrame:
        """预览数据"""
        return self.query(file_id, f"SELECT * FROM data LIMIT {limit}")
```

### 3.4 REST API设计

#### 3.4.1 API端点
```python
from flask import Blueprint, request, jsonify
from werkzeug.utils import secure_filename

file_db_bp = Blueprint('file_db', __name__, url_prefix='/api/v1/file-db')

@file_db_bp.route('/upload', methods=['POST'])
def upload_file():
    """文件上传API"""
    # 验证用户认证
    # 验证文件类型和大小
    # 保存文件到存储后端
    # 解析文件元数据
    # 创建数据库记录
    # 返回文件ID和预览数据
    pass

@file_db_bp.route('/preview/<file_id>', methods=['GET'])
def preview_file(file_id):
    """文件预览API"""
    # 获取文件元数据
    # 使用查询引擎获取前100行数据
    # 返回JSON格式数据
    pass

@file_db_bp.route('/metadata/<file_id>', methods=['GET'])
def get_metadata(file_id):
    """获取文件元数据API"""
    # 返回文件详细信息、列信息、工作表信息
    pass

@file_db_bp.route('/datasource', methods=['POST'])
def create_datasource():
    """创建数据源API"""
    # 接收文件ID、数据源名称、配置参数
    # 在Superset中注册数据源
    # 返回数据源ID
    pass

@file_db_bp.route('/columns/<file_id>', methods=['GET'])
def get_columns(file_id):
    """获取文件列信息API"""
    # 获取文件元数据
    # 返回列信息列表（列ID、列名、列类型、列格式等）
    pass

@file_db_bp.route('/columns/<file_id>/<column_id>', methods=['PUT'])
def update_column_type(file_id, column_id):
    """更新列类型API"""
    # 验证文件所有权
    # 验证请求数据（列类型、列格式）
    # 更新列类型
    # 返回更新后的列信息
    pass

@file_db_bp.route('/files', methods=['GET'])
def list_files():
    """列出用户文件API"""
    # 获取用户ID
    # 查询用户文件列表
    # 返回文件列表
    pass

@file_db_bp.route('/files/<file_id>', methods=['DELETE'])
def delete_file(file_id):
    """删除文件API"""
    # 验证文件所有权
    # 删除存储文件
    # 删除数据库记录
    # 返回删除结果
    pass
```

### 3.5 前端组件设计

#### 3.5.1 拖拽上传组件
```tsx
import React, { useCallback } from 'react';
import { useDropzone } from 'react-dropzone';

interface FileUploadProps {
  onUploadComplete: (fileId: string) => void;
  onError: (error: string) => void;
}

const FileUpload: React.FC<FileUploadProps> = ({ onUploadComplete, onError }) => {
  const onDrop = useCallback(async (acceptedFiles: File[]) => {
    // 验证文件类型和大小
    // 创建FormData
    // 调用上传API
    // 处理响应
  }, []);
  
  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      'text/csv': ['.csv'],
      'application/vnd.ms-excel': ['.xls'],
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx']
    },
    maxSize: 150 * 1024 * 1024  // 150MB
  });
  
  return (
    <div {...getRootProps()} className="file-upload-dropzone">
      <input {...getInputProps()} />
      {isDragActive ? (
        <p>拖放文件到这里...</p>
      ) : (
        <p>拖放CSV或Excel文件到这里，或点击选择文件</p>
      )}
    </div>
  );
};
```

#### 3.5.2 数据预览组件
```tsx
import React from 'react';

interface DataPreviewProps {
  fileId: string;
  data: {
    columns: string[];
    rows: any[][];
    totalRows: number;
  };
  columnTypes?: Record<string, { type: string; format?: string }>;
}

const DataPreview: React.FC<DataPreviewProps> = ({ fileId, data, columnTypes }) => {
  return (
    <div className="data-preview">
      <h3>数据预览</h3>
      <p>显示前100行，共{data.totalRows}行</p>
      <div className="preview-table-container">
        <table>
          <thead>
            <tr>
              {data.columns.map((col, idx) => (
                <th key={idx}>
                  <div className="column-header">
                    <span className="column-name">{col}</span>
                    {columnTypes && columnTypes[col] && (
                      <span className="column-type">{columnTypes[col].type}</span>
                    )}
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.rows.map((row, rowIdx) => (
              <tr key={rowIdx}>
                {row.map((cell, cellIdx) => (
                  <td key={cellIdx}>{cell}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};
```

#### 3.5.3 配置界面组件
```tsx
import React, { useState, useEffect } from 'react';

interface FileConfigProps {
  fileId: string;
  fileType: 'csv' | 'excel';
  sheets?: string[];
  columns?: ColumnInfo[];
  onConfigSave: (config: FileConfig) => void;
  onColumnTypeUpdate: (columnId: string, columnType: string, columnFormat?: string) => void;
}

interface ColumnInfo {
  id: string;
  name: string;
  type: string;
  format?: string;
  isUserDefined: boolean;
  sampleValues: any[];
}

interface FileConfig {
  selectedSheet?: string;
  delimiter?: string;
  encoding?: string;
  datasourceName: string;
}

const FileConfig: React.FC<FileConfigProps> = ({ 
  fileId, fileType, sheets, columns, onConfigSave, onColumnTypeUpdate 
}) => {
  const [config, setConfig] = useState<FileConfig>({
    datasourceName: '',
    delimiter: ',',
    encoding: 'utf-8'
  });
  
  const [columnTypes, setColumnTypes] = useState<Record<string, { type: string; format?: string }>>({});
  
  useEffect(() => {
    if (columns) {
      const initialTypes: Record<string, { type: string; format?: string }> = {};
      columns.forEach(col => {
        initialTypes[col.id] = { type: col.type, format: col.format };
      });
      setColumnTypes(initialTypes);
    }
  }, [columns]);
  
  const handleColumnTypeChange = (columnId: string, newType: string) => {
    setColumnTypes(prev => ({
      ...prev,
      [columnId]: { ...prev[columnId], type: newType }
    }));
  };
  
  const handleColumnFormatChange = (columnId: string, newFormat: string) => {
    setColumnTypes(prev => ({
      ...prev,
      [columnId]: { ...prev[columnId], format: newFormat }
    }));
  };
  
  const handleSaveColumnTypes = () => {
    if (columns) {
      columns.forEach(col => {
        const typeInfo = columnTypes[col.id];
        if (typeInfo && (typeInfo.type !== col.type || typeInfo.format !== col.format)) {
          onColumnTypeUpdate(col.id, typeInfo.type, typeInfo.format);
        }
      });
    }
  };
  
  return (
    <div className="file-config">
      <h3>文件配置</h3>
      
      <div className="config-field">
        <label>数据源名称</label>
        <input 
          type="text"
          value={config.datasourceName}
          onChange={(e) => setConfig({...config, datasourceName: e.target.value})}
        />
      </div>
      
      {fileType === 'excel' && sheets && (
        <div className="config-field">
          <label>选择工作表</label>
          <select 
            value={config.selectedSheet}
            onChange={(e) => setConfig({...config, selectedSheet: e.target.value})}
          >
            {sheets.map(sheet => (
              <option key={sheet} value={sheet}>{sheet}</option>
            ))}
          </select>
        </div>
      )}
      
      {fileType === 'csv' && (
        <>
          <div className="config-field">
            <label>分隔符</label>
            <select 
              value={config.delimiter}
              onChange={(e) => setConfig({...config, delimiter: e.target.value})}
            >
              <option value=",">逗号 (,)</option>
              <option value=";">分号 (;)</option>
              <option value="\t">制表符</option>
              <option value="|">竖线 (|)</option>
            </select>
          </div>
          
          <div className="config-field">
            <label>编码</label>
            <select 
              value={config.encoding}
              onChange={(e) => setConfig({...config, encoding: e.target.value})}
            >
              <option value="utf-8">UTF-8</option>
              <option value="gbk">GBK</option>
              <option value="gb2312">GB2312</option>
              <option value="latin-1">Latin-1</option>
            </select>
          </div>
        </>
      )}
      
      {columns && columns.length > 0 && (
        <div className="column-types-section">
          <h4>列类型配置</h4>
          <p>系统已自动推断列类型，您可以手动调整：</p>
          
          <div className="column-types-table">
            <table>
              <thead>
                <tr>
                  <th>列名</th>
                  <th>类型</th>
                  <th>格式</th>
                  <th>示例值</th>
                </tr>
              </thead>
              <tbody>
                {columns.map(col => (
                  <tr key={col.id}>
                    <td>{col.name}</td>
                    <td>
                      <select
                        value={columnTypes[col.id]?.type || col.type}
                        onChange={(e) => handleColumnTypeChange(col.id, e.target.value)}
                      >
                        <option value="string">字符串</option>
                        <option value="integer">整数</option>
                        <option value="float">浮点数</option>
                        <option value="datetime">日期时间</option>
                        <option value="boolean">布尔值</option>
                      </select>
                    </td>
                    <td>
                      {columnTypes[col.id]?.type === 'datetime' && (
                        <input
                          type="text"
                          value={columnTypes[col.id]?.format || ''}
                          onChange={(e) => handleColumnFormatChange(col.id, e.target.value)}
                          placeholder="YYYY-MM-DD"
                        />
                      )}
                    </td>
                    <td>
                      <div className="sample-values">
                        {col.sampleValues.slice(0, 3).map((val, idx) => (
                          <span key={idx} className="sample-value">{val}</span>
                        ))}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          
          <button onClick={handleSaveColumnTypes} className="save-column-types-btn">
            保存列类型
          </button>
        </div>
      )}
      
      <button onClick={() => onConfigSave(config)}>保存配置</button>
    </div>
  );
};
```

## 4. 实现计划

### 4.1 开发阶段

#### 阶段1：后端基础（1-2周）
1. 存储层抽象和本地存储实现
2. 元数据管理模块
3. 数据库表结构创建

#### 阶段2：查询引擎（1-2周）
1. 自定义SQLAlchemy方言开发
2. DuckDB集成和文件查询
3. CSV和Excel文件解析

#### 阶段3：REST API（1周）
1. 文件上传API
2. 数据预览API
3. 数据源创建API
4. 文件管理API
5. 列类型管理API（获取和更新列类型）

#### 阶段4：前端组件（2-3周）
1. 拖拽上传组件
2. 数据预览组件（包含列类型显示）
3. 配置界面组件（包含列类型编辑）
4. 文件管理组件

#### 阶段5：集成和测试（1周）
1. 前后端集成
2. 功能测试
3. 性能测试
4. 部署文档

### 4.2 部署要求

#### 4.2.1 系统要求
- Python 3.8+
- Node.js 14+（前端构建）
- PostgreSQL 12+（元数据存储）
- 磁盘空间：根据文件存储需求

#### 4.2.2 依赖包
- 后端：sqlalchemy, duckdb, pandas, flask, openpyxl
- 前端：react, typescript, superset-ui

#### 4.2.3 安装步骤
1. 安装Python包：`pip install -e .`
2. 安装前端依赖：`npm install`
3. 构建前端：`npm run build`
4. 配置Superset启用扩展
5. 运行数据库迁移
6. 启动Superset服务

## 5. 详细设计决策

### 5.1 数据源设计
- **方案B**：所有文件共享一个"File Database"连接，每个文件对应一个Dataset
- **数据库连接创建**：Admin手动创建，用户选择连接
- **支持多个File Database连接**：用户可以选择不同的连接

### 5.2 文件存储设计
- **存储路径**：Admin配置大目录，系统自动创建用户ID子目录
- **文件命名**：UUID重命名，记录原始文件名
- **文件格式**：只支持CSV和Excel（.xlsx/.xls）
- **Excel处理**：先转换为Parquet格式再查询

### 5.3 文件解析设计
- **解析时机**：延迟解析（第一次查询时解析）
- **数据预览**：用户点击预览时再解析
- **预览数据量**：100行

### 5.4 文件大小限制
- **CSV**：≤150MB
- **Excel**：≤500MB
- **用户配额**：不限制总配额

### 5.5 上传功能设计
- **批量上传**：支持批量上传
- **并行上传**：支持并行上传，最多3个并发
- **断点续传**：支持断点续传
- **进度显示**：显示每个文件的上传进度
- **拖拽上传**：支持拖拽到特定区域

### 5.6 文件验证设计
- **文件类型验证**：验证文件类型（只允许CSV和Excel）
- **文件大小验证**：验证文件大小
- **文件名验证**：验证文件名（不允许特殊字符，最长255个字符）
- **文件内容验证**：不验证

### 5.7 编码和分隔符设计
- **编码检测**：自动检测，失败时让用户手动选择
- **分隔符**：手动选择，支持逗号、分号、制表符、竖线、空格

### 5.8 Excel工作表设计
- **工作表选择**：显示所有工作表，支持选择多个
- **工作表预览**：预览每个工作表的数据（100行）
- **数据源创建**：每个工作表创建为独立的数据源
- **批量创建**：支持批量创建数据源，统一配置

### 5.9 列类型管理设计
- **列类型检测**：自动检测
- **列类型修改**：允许用户修改，创建后也可以修改
- **修改后处理**：重新解析文件
- **修改历史**：记录修改历史，永久保留
- **批量操作**：逐个修改，不支持撤销和重置
- **导入导出**：支持JSON格式导入，不支持导出
- **导入验证**：验证配置格式，失败时拒绝导入

### 5.10 数据源命名设计
- **数据源命名**：用户手动输入
- **数据源描述**：支持添加描述
- **数据源标签**：使用Superset原生tag
- **创建流程**：上传后立即创建

### 5.11 文件管理设计
- **管理入口**：数据源管理页面
- **管理页面**：独立的文件管理页面
- **使用情况**：显示文件使用情况
- **文件下载**：不支持下载原始文件
- **文件重命名**：不支持重命名

### 5.12 文件删除设计
- **删除检查**：检查是否被使用
- **删除确认**：二次确认
- **删除内容**：同时删除关联的数据源、存储文件、Parquet文件、DuckDB连接、相关元数据
- **删除日志**：记录删除日志（日志ID、文件ID、文件名、删除时间、删除原因、操作用户ID）
- **日志存储**：Superset元数据库
- **日志清理**：永久保留

### 5.13 文件清理设计
- **清理方式**：两者结合（自动清理为主，Admin可以手动删除）
- **过期提醒**：过期前提醒用户
- **通知方式**：界面内通知

### 5.14 连接和缓存设计
- **DuckDB连接**：每个文件独立连接
- **并发处理**：允许重复上传

## 6. 权限管理

### 6.1 设计原则
- 复用Superset原生的权限管理体系
- 不创建自定义权限系统
- 文件上传后创建为数据源，数据源权限通过Superset管理

### 6.2 权限角色

#### 6.2.1 文件管理权限
- **文件上传**：所有登录用户（Superset默认权限）
- **文件删除**：仅文件上传者和Admin角色
- **文件配置修改**：仅文件上传者和Admin角色
- **列类型修改**：仅文件上传者和Admin角色

#### 6.2.2 数据访问权限
- **创建数据源**：文件上传者（或其他有数据源创建权限的用户）
- **查看数据源**：通过Superset数据源权限控制
- **创建图表**：通过Superset数据集权限控制
- **查看报表**：通过Superset报表权限控制

### 6.3 权限实现

#### 6.3.1 数据库设计
在`uploaded_files`表中添加`created_by`字段，记录文件上传者：
```sql
ALTER TABLE uploaded_files ADD COLUMN created_by VARCHAR(36) NOT NULL;
```

#### 6.3.2 API权限检查
- 文件删除API：检查当前用户是否为文件上传者或Admin
- 文件配置API：检查当前用户是否为文件上传者或Admin
- 数据源创建API：检查当前用户是否有数据源创建权限

#### 6.3.3 Superset权限集成
- 文件创建为数据源后，自动应用Superset数据源权限
- 数据源权限由Superset管理员在"数据源"管理界面配置
- 支持行级安全（RLS）和列级安全（CLS）

### 6.4 权限流程

```
用户上传文件
    ↓
文件存储，记录created_by
    ↓
用户创建数据源（需要数据源创建权限）
    ↓
数据源创建成功，应用Superset默认权限
    ↓
管理员配置数据源权限（可选）
    ↓
其他用户根据权限访问数据源
```

### 6.5 权限示例

#### 场景1：私有文件
- 用户A上传文件，创建数据源
- 默认只有用户A可以访问数据源
- 用户A可以将数据源权限授予其他用户

#### 场景2：共享文件
- 用户A上传文件，创建数据源
- 管理员将数据源权限授予Gamma角色
- 所有Gamma用户都可以访问数据源

#### 场景3：报表共享
- 用户A基于数据源创建报表
- 用户A将报表共享给用户B（老板）
- 用户B可以查看报表，即使没有数据源直接访问权限

## 7. 测试策略

### 7.1 单元测试
- 存储层测试
- 元数据管理测试
- 查询引擎测试
- API测试

### 7.2 集成测试
- 文件上传流程测试
- 数据源创建流程测试
- 查询功能测试

### 7.3 性能测试
- 大文件上传测试
- 并发上传测试
- 查询性能测试

### 7.4 用户测试
- 用户界面测试
- 用户体验测试
- 错误处理测试

## 8. 风险评估

### 8.1 技术风险
- DuckDB对Excel文件支持有限（需要转换）
- 大文件内存使用问题
- 并发访问文件锁问题

### 8.2 缓解措施
- Excel文件转换为Parquet格式
- 实现流式处理，限制内存使用
- 使用文件锁或数据库锁管理并发

### 8.3 时间风险
- 前端开发可能需要更多时间
- 集成测试可能发现问题

### 8.4 缓解措施
- 前端使用现有组件库
- 早期进行集成测试

## 9. 后续扩展

### 9.1 功能扩展
- 支持更多文件格式（Parquet、JSON等）
- 数据转换和清洗功能
- 数据可视化预览
- 文件版本管理

### 9.2 性能优化
- 文件索引优化
- 查询缓存
- 分布式存储支持

### 9.3 集成扩展
- 与其他BI工具集成
- API开放给第三方应用
- 数据共享功能

## 10. 附录

### 10.1 参考文档
- Superset扩展开发文档
- DuckDB文档
- SQLAlchemy方言开发指南

### 10.2 术语表
- **文件数据库引擎**：自定义数据库引擎，用于查询文件数据
- **存储后端**：文件存储的抽象接口
- **元数据**：描述文件结构和属性的数据
- **DuckDB**：分析型数据库，用于高效查询文件数据

### 10.3 变更记录
- 2026-09-25：初始版本