#!/bin/bash
# OpenTrace 本地启动脚本（不使用 Docker）

echo "=============================================="
echo " OpenTrace 本地启动"
echo "=============================================="

# 设置环境变量
export APP_HOST=0.0.0.0
export APP_PORT=14100
export DEBUG=true

echo ""
echo "启动后端 API..."
echo "  访问: http://localhost:14100/api/v1/docs"
echo "  健康检查: http://localhost:14100/api/v1/health"
echo ""

# 进入项目目录并启动
cd /Users/tuwan/work/code/agentos/opentrace/gateway/api_gateway
python -m uvicorn main:app --host 0.0.0.0 --port 14100 --reload
