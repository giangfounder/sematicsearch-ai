# Multi-arch: chạy được cả amd64 và arm64 (Oracle A1). Không có torch/model local.
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY app ./app
COPY migrations ./migrations
COPY seeds ./seeds
COPY scripts ./scripts
EXPOSE 8000
# Nhận cổng động của nền tảng (Render đặt $PORT); mặc định 8000 cho docker-compose cục bộ.
HEALTHCHECK --interval=30s --timeout=5s --start-period=25s CMD python -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:%s/health'%os.environ.get('PORT','8000'),timeout=4)"
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --no-access-log"]
