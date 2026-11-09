FROM eclipse-mosquitto:2

# 官方镜像不带账号，这里在首次启动时用环境变量生成密码文件，
# 之后复用 mosquitto_data 卷里的 /mosquitto/data/passwd（改密码 → 删卷重建即可）
COPY mosquitto.conf /mosquitto/config/mosquitto.conf
COPY docker-entrypoint.sh /docker-entrypoint-custom.sh
RUN chmod +x /docker-entrypoint-custom.sh

ENTRYPOINT ["/docker-entrypoint-custom.sh"]
