#include <Arduino.h>
#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <time.h>
#include "../include/config.h"

// ===== 设备信息（主题规划 = PRD 5.1）=====
const char* device_id       = "k10-act-03";
const char* status_topic    = "tea/device/k10-act-03/status";
const char* cmd_topic       = "tea/device/k10-act-03/cmd";
const char* ack_topic       = "tea/device/k10-act-03/ack";

// 该板无屏幕，已移除所有显示代码；状态通过串口 + MQTT status 上报。

const int  relay_pin    = 15;     // IO15，低电平触发（旧项目验证过；GPIO1 在定制K10上会抖动）
const long MAX_PUMP_S   = 120;    // 安全阀：单次最大 120s（PRD 4.3）

bool          is_pumping    = false;
bool          pump_clamped  = false;
unsigned long pump_start_ms = 0;
unsigned long pump_end_ms   = 0;
long          pump_duration_s = 0;
String current_task_id = "";
String current_msg_id  = "";

WiFiClient espClient;
PubSubClient client(espClient);

unsigned long last_status_ms = 0;

// ===== MQTT 指数退避重连（PRD 4.3 第5条）=====
unsigned long backoff_ms        = 1000;
unsigned long last_mqtt_attempt = 0;

// ===== NTP 时间同步（PRD 5.2）=====
void setup_time() {
    configTime(0, 0, "ntp.aliyun.com", "pool.ntp.org");
    setenv("TZ", "CST-8", 1);
    tzset();
}

long get_epoch() {
    time_t t = time(nullptr);
    if (t < 1700000000) return (long)(millis() / 1000);
    return (long)t;
}

void send_ack(const char* ref_msg_id, const char* task_id,
              const char* stage, const char* result,
              long executed_s = -1, bool clamped = false) {
    static unsigned long ack_seq = 0;
    StaticJsonDocument<512> doc;
    doc["msg_id"]     = String("ack-") + String(millis()) + String("-") + String(++ack_seq);
    doc["ref_msg_id"] = ref_msg_id;
    doc["task_id"]    = task_id;
    doc["device_id"]  = device_id;
    doc["stage"]      = stage;
    doc["result"]     = result;
    if (executed_s >= 0) {
        JsonObject detail = doc.createNestedObject("detail");
        detail["executed_s"] = executed_s;
        detail["clamped"]    = clamped;   // PRD 5.4：钳位时标注 clamped:true
    }
    doc["ts"] = get_epoch();

    char buffer[512];
    size_t len = serializeJson(doc, buffer);
    client.publish(ack_topic, buffer, len);   // 必须指定长度，否则尾部带随机字节变乱码
}

void setup_wifi() {
    WiFi.setAutoReconnect(true);
    WiFi.mode(WIFI_STA);
    WiFi.begin(ssid, password);
    Serial.print("[WiFi] connecting");
    unsigned long start = millis();
    while (WiFi.status() != WL_CONNECTED && millis() - start < 30000) {
        delay(500);
        Serial.print(".");
    }
    Serial.println(WiFi.status() == WL_CONNECTED ? "\n[WiFi] connected" : "\n[WiFi] first connect failed, will retry in loop");
}

void callback(char* topic, byte* payload, unsigned int length) {
    StaticJsonDocument<512> doc;
    DeserializationError err = deserializeJson(doc, payload, length);
    if (err) return;

    const char* action  = doc["action"] | "";
    const char* msg_id  = doc["msg_id"] | "";
    const char* task_id = doc["task_id"] | "";

    if (strcmp(action, "pump") == 0) {
        if (is_pumping) {
            // 正在执行时拒绝新指令，避免继电器状态混乱
            send_ack(msg_id, task_id, "finished", "rejected");
            return;
        }
        long duration = doc["params"]["duration_s"] | 0;
        if (duration < 1) {
            // 参数非法：拒绝执行（PRD 5.4 result=rejected）
            send_ack(msg_id, task_id, "finished", "rejected");
            Serial.printf("[Pump] rejected, invalid duration_s=%ld\n", duration);
            return;
        }

        send_ack(msg_id, task_id, "received", "done");

        pump_clamped = false;
        if (duration > MAX_PUMP_S) {  // 安全阀：超过按 120s 执行
            duration = MAX_PUMP_S;
            pump_clamped = true;
        }
        current_msg_id  = String(msg_id);
        current_task_id = String(task_id);
        pump_duration_s = duration;
        pump_start_ms   = millis();
        pump_end_ms     = pump_start_ms + (unsigned long)duration * 1000;
        is_pumping      = true;

        digitalWrite(relay_pin, LOW);  // 低电平触发：闭合
        Serial.printf("[Pump] started, %ld s (clamped=%d)\n", duration, pump_clamped);

    } else if (strcmp(action, "relay_off") == 0) {
        // 紧急断开（人工救援通道）
        send_ack(msg_id, task_id, "received", "done");
        digitalWrite(relay_pin, HIGH);
        is_pumping = false;
        send_ack(msg_id, task_id, "finished", "done");
        Serial.println("[Pump] emergency OFF");

    } else if (strcmp(action, "reboot") == 0) {
        send_ack(msg_id, task_id, "received", "done");
        digitalWrite(relay_pin, HIGH);  // 重启前确保继电器断开
        delay(200);
        ESP.restart();
    }
}

void ensure_connection() {
    if (WiFi.status() != WL_CONNECTED) return;
    if (client.connected()) {
        backoff_ms = 1000;
        return;
    }
    if (millis() - last_mqtt_attempt < backoff_ms) return;
    last_mqtt_attempt = millis();

    Serial.printf("[MQTT] connecting... (backoff %lus)\n", backoff_ms / 1000);
    if (client.connect(device_id, mqtt_user, mqtt_password)) {
        Serial.println("[MQTT] connected");
        backoff_ms = 1000;
        client.publish(status_topic, "{\"online\": true}");
        client.subscribe(cmd_topic);
        Serial.printf("[MQTT] subscribed %s\n", cmd_topic);
    } else {
        backoff_ms = (backoff_ms >= 30000) ? 30000 : backoff_ms * 2;
    }
}

void setup() {
    Serial.begin(115200);
    Serial.println("\n=== k10_act (no-screen) boot ===");

    pinMode(relay_pin, OUTPUT);
    digitalWrite(relay_pin, HIGH);  // 上电即断开（低电平触发，高=断）

    setup_wifi();
    setup_time();
    client.setServer(mqtt_server, mqtt_port);
    client.setBufferSize(768);   // 默认256会丢弃带detail的finished ack
    client.setCallback(callback);
}

void loop() {
    ensure_connection();
    client.loop();

    if (is_pumping) {
        if (millis() >= pump_end_ms) {
            digitalWrite(relay_pin, HIGH);  // 断开
            is_pumping = false;
            // PRD 5.4：ack done 含实际执行秒数
            long executed_s = (long)((millis() - pump_start_ms) / 1000);
            send_ack(current_msg_id.c_str(), current_task_id.c_str(),
                     "finished", "done", executed_s, pump_clamped);
            Serial.printf("[Pump] finished, executed %ld s\n", executed_s);
        } else {
            static unsigned long last_display_update = 0;
            if (millis() - last_display_update > 1000) {
                last_display_update = millis();
                long remaining = (long)((pump_end_ms - millis()) / 1000);
                Serial.printf("[Pump] remaining %ld s\n", remaining);
            }
        }
    }

    if (millis() - last_status_ms > 15000) {  // 心跳每 15s
        last_status_ms = millis();
        StaticJsonDocument<160> doc;
        doc["online"]  = client.connected();
        doc["rssi"]    = WiFi.RSSI();
        doc["uptime"]  = (long)(millis() / 1000);
        doc["pumping"] = is_pumping;

        char buffer[160];
        size_t len = serializeJson(doc, buffer);
        client.publish(status_topic, buffer, len);
    }
}
