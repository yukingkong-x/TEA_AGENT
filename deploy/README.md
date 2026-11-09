# deploy —— compose 配套配置（队友 B 维护）

> 这里只放「容器启动需要、又不好写进 compose 内联」的文件。一键启动方法见根目录 README。

```
deploy/
├── mysql/my.cnf              # MySQL 8 字符集/时区/连接数（挂到 /etc/mysql/conf.d/）
└── mosquitto/
    ├── Dockerfile            # 基于 eclipse-mosquitto:2，首次启动按 .env 生成密码文件
    ├── mosquitto.conf        # 1883 监听 + 强制账号认证 + 持久化
    └── docker-entrypoint.sh  # 用 MQTT_USER / MQTT_PASSWORD 生成 passwd
```

## 端口表（PRD 19.5，宿主机侧；容器内仍是标准端口）

| 服务 | 宿主机 | 容器内 | 说明 |
| --- | --- | --- | --- |
| 前端 | 5173 | 80 | `--profile ui` 才起 |
| 后端 | 8000 | 8000 | `/docs` 看接口 |
| MySQL | **3307** | 3306 | 改 3307 是为了躲开本机已装的 MySQL |
| Redis | 6379 | 6379 | 带密码 |
| Mosquitto | 1883 | 1883 | 带账号 |
| Chroma | 8100 | 8000 | 可选，RAG 用 |

宿主机端口都能在 `.env` 里改：`MYSQL_HOST_PORT` / `REDIS_HOST_PORT` / `MQTT_HOST_PORT` / `CHROMA_HOST_PORT` / `BACKEND_PORT`。

## 改 MQTT 密码

密码文件落在具名卷 `mosquitto_data` 里，改 `.env` 不会自动生效。换账号密码：

```bash
docker compose rm -sf mosquitto
docker volume rm zhiqiu_mosquitto_data
docker compose up -d mosquitto
```

## Chroma 是可选的

`docker-compose.yml` 里 backend 对 chroma 是 `required: false`：镜像 1GB+，
网络不好时平台能先跑起来（RAG 接口返回 503，其余功能不受影响）。镜像到位后
`docker compose up -d chroma` 单独拉起即可。
