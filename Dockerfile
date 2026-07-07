# 多源勘察数据融合系统 —— 应用镜像
FROM python:3.10-slim

# 系统依赖（matplotlib/PostGIS 客户端需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 libsm6 libxext6 libxrender1 libgl1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先装依赖（利用层缓存）
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 拷贝代码
COPY backend/ ./backend/
COPY frontend/ ./frontend/

# 默认关闭数据库（容器内通过环境变量开启）
ENV FUSION_USE_DB=false \
    FUSION_HOST=0.0.0.0 \
    FUSION_PORT=8000 \
    PYTHONPATH=/app

EXPOSE 8000

# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://localhost:8000/api/health'); sys.exit(0)" || exit 1

CMD ["python", "-m", "uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
