#!/bin/sh
# Mosquitto 启动脚本：首次启动时按 .env 的 MQTT_USER / MQTT_PASSWORD 生成密码文件
# 注意：mosquitto 进程会降权成 mosquitto 用户，密码文件必须给它可读权限，否则
#       "password-file: Error: Unable to open pwfile" 然后无限重启。
set -e

PASSWD_FILE=/mosquitto/data/passwd
mkdir -p /mosquitto/data

if [ ! -s "$PASSWD_FILE" ]; then
    if [ -z "$MQTT_USER" ] || [ -z "$MQTT_PASSWORD" ]; then
        echo "[mosquitto] 缺少 MQTT_USER / MQTT_PASSWORD 环境变量，拒绝以匿名模式启动" >&2
        exit 1
    fi
    echo "[mosquitto] 首次启动，生成密码文件：user=$MQTT_USER"
    mosquitto_passwd -b -c "$PASSWD_FILE" "$MQTT_USER" "$MQTT_PASSWORD"
else
    echo "[mosquitto] 复用已有密码文件 $PASSWD_FILE"
fi

# 具名卷首次挂载是 root 所有，统一交给 mosquitto 用户
chown -R mosquitto:mosquitto /mosquitto/data
chmod 600 "$PASSWD_FILE"

exec /usr/sbin/mosquitto -c /mosquitto/config/mosquitto.conf
