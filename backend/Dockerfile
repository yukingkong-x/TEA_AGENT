# 后端镜像（PRD 21.2：python:3.11-slim 自建）
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Shanghai

WORKDIR /app

# curl 供 healthcheck 用；tzdata 供 TZ 生效
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

COPY requirements.txt ./
# 网络受限时可传 --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ARG PIP_INDEX_URL=https://pypi.org/simple
RUN pip install --no-cache-dir -i "$PIP_INDEX_URL" -r requirements.txt

COPY . .

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=40s --retries=12 \
    CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
