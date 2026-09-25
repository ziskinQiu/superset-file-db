#!/bin/bash
set -e

# 首次启动检测：元数据库无版本记录时执行初始化
TABLE_EXISTS=$(superset db current | grep -c "Current revision" || true)
if [ "$TABLE_EXISTS" -eq 0 ]; then
    echo ">>> 首次启动：检测到数据库未初始化，开始初始化..."

    # 1. 执行数据库迁移
    superset db upgrade

    # 2. 创建管理员账号（若已存在则忽略报错，防止脚本中断）
    superset fab create-admin --username admin --password admin --firstname Admin --lastname User --email admin@superset.com || true

    # 3. 初始化角色和权限
    superset init

    echo ">>> 初始化完成！"
else
    echo ">>> 非首次启动：检测到数据库已初始化，跳过初始化，直接启动服务..."
fi

# 启动 Superset Web 服务
exec /usr/bin/run-server.sh
