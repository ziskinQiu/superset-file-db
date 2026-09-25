# 1. 基于官方镜像
FROM apache/superset:6.1.0

# 2. 切换到 root 用户以便进行文件操作
USER root

# 新增：安装运行时依赖（duckdb/pandas/openpyxl/chardet/xlrd/pyarrow/psycopg2）
COPY ./backend/requirement.txt /app/requirement.txt
RUN /app/.venv/bin/python -m ensurepip --upgrade \
    && /app/.venv/bin/python -m pip install -r /app/requirement.txt \
    && /app/.venv/bin/python -m pip list

# 3. 创建扩展目录，并将扩展文件复制进去
RUN mkdir -p /app/extensions
COPY file-db-0.1.0.supx /app/extensions/

# 4. 将自定义配置文件复制到容器内
COPY superset_config.py /app/pythonpath/superset_config.py

# 5. 设置环境变量，指定自定义配置文件的路径
ENV SUPERSET_CONFIG_PATH=/app/pythonpath/superset_config.py

# 6. 复制初始化脚本并赋予执行权限
COPY init-superset.sh /app/
RUN chmod +x /app/init-superset.sh

# 7. 切换回 superset 用户运行服务（安全最佳实践）
USER superset

# 8. 使用自定义启动脚本
CMD ["/app/init-superset.sh"]
