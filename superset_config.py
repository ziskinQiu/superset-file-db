# 启用扩展功能
FEATURE_FLAGS = {
    "ENABLE_EXTENSIONS": True,
}

# 设置扩展存放目录
EXTENSIONS_PATH = "/app/extensions"

# 设置 SECRET_KEY，确保它是一个随机且安全的字符串
SECRET_KEY = "your_random_secret_key_here"

# 元数据库连接字符串（与 docker-compose.yml 的 pg-db 服务对应）
SQLALCHEMY_DATABASE_URI = "postgresql://superset_meta:superset_meta_pass@pg-db:5432/superset_metadata"

# 可选：异步查询结果存储（推荐也切到 PG）
SQLALCHEMY_EXAMPLES_URI = SQLALCHEMY_DATABASE_URI
RESULTS_BACKEND_USE_MSGPACK = False

# 性能调优
SQLALCHEMY_POOL_SIZE = 10
SQLALCHEMY_MAX_OVERFLOW = 20
SQLALCHEMY_POOL_RECYCLE = 3600

# file-db 扩展的上传目录经环境变量 FILE_DB_UPLOAD_ROOT 透传
# （扩展 config.py 在导入时读取，默认 /data/uploads）
