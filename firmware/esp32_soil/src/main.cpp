#include <Arduino.h>
#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <Preferences.h>
#include <time.h>
#include "../include/config.h"

// ===== 设备信息（主题规划 = PRD 5.1）=====
const char* device_id       = "esp32-soil-02";
const char* telemetry_topic = "tea/device/esp32-soil-02/telemetry";
const char* status_topic    = "tea/device/esp32-soil-02/status";
const char* cmd_topic       = "tea/device/esp32-soil-02/cmd";
const char* ack_topic       = "tea/device/esp32-soil-02/ack";

const int soil_pin = 34;  // ADC1_CH7，仅输入（PRD 4.2 接线表）

Preferences preferences;
int dry_val = 3200;  // 默认干燥基准（ADC 原始值），首次烧录后必须标定
int wet_val = 1200;  // 默认湿润基准

WiFiClient espClient;
PubSubClient client(espClient);

unsigned long last_telemetry_ms = 0;
unsigned long last_status_ms    = 0;
unsigned long seq               = 0;

// ===== MQTT 指数退避重连（PRD 4.3 第5条）=====
unsigned long backoff_ms        = 1000;
unsigned long last_mqtt_attempt = 0;

// ===== NTP 时间同步（PRD 5.2：ts 为设备 Unix 时间戳，秒）=====
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
              const char* stage, const char* result) {
    StaticJsonDocument<320> doc;
    doc["msg_id"]     = String("ack-") + String(millis());
    doc["ref_msg_id"] = ref_msg_id;
    doc["task_id"]    = task_id;
    doc["device_id"]  = device_id;
    doc["stage"]      = stage;
    doc["result"]     = result;
    doc["ts"]         = get_epoch();

    char buffer[320];
    serializeJson(doc, buffer);
    client.publish(ack_topic, buffer);
}

// ===== ADC 采样 10 次取中位数（PRD 4.3 esp32-soil 专属）=====
int read_adc_median() {
    int s[10];
    for (int i = 0; i < 10; i++) {
        s[i] = analogRead(soil_pin);
        delay(5);
    }
    for (int i = 1; i < 10; i++) {  // 插入排序
        int key = s[i];
        int j = i - 1;
        while (j >= 0 && s[j] > key) { s[j + 1] = s[j]; j--; }
        s[j + 1] = key;
    }
    return (s[4] + s[5]) / 2;
}

void callback(char* topic, byte* payload, unsigned int length) {
    StaticJsonDocument<384> doc;
    DeserializationError err = deserializeJson(doc, payload, length);
    if (err) return;

    const char* action  = doc["action"] | "";
    const char* msg_id  = doc["msg_id"] | "";
    const char* task_id = doc["task_id"] | "";

    if (strcmp(action, "calibrate_dry") == 0) {
        // 标定流程（PRD 4.3）：当前 ADC 原始值存为干燥基准，NVS 持久化
        send_ack(msg_id, task_id, "received", "done");
        dry_val = read_adc_median();
        preferences.putInt("dry", dry_val);
        send_ack(msg_id, task_id, "finished", "done");
        Serial.printf("[Calibrate] dry = %d\n", dry_val);
    } else if (strcmp(action, "calibrate_wet") == 0) {
        send_ack(msg_id, task_id, "received", "done");
        wet_val = read_adc_median();
        preferences.putInt("wet", wet_val);
        send_ack(msg_id, task_id, "finished", "done");
        Serial.printf("[Calibrate] wet = %d\n", wet_val);
    } else if (strcmp(action, "read_now") == 0) {
        send_ack(msg_id, task_id, "received", "done");
        last_telemetry_ms = 0;  // 立即补测上报
        send_ack(msg_id, task_id, "finished", "done");
    } else if (strcmp(action, "reboot") == 0) {
        send_ack(msg_id, task_id, "received", "done");
        delay(200);
        ESP.restart();
    }
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
    } else {
        backoff_ms = (backoff_ms >= 30000) ? 30000 : backoff_ms * 2;
    }
}

float adc_to_moisture(int adc) {
    // 线性映射：干 = 0%，湿 = 100%
    float moisture = (float)(adc - dry_val) * 100.0f / (float)(wet_val - dry_val);
    if (moisture < 0)   moisture = 0;
    if (moisture > 100) moisture = 100;
    return moisture;
}

void send_telemetry() {
    int adc = read_adc_median();
    float moisture = adc_to_moisture(adc);

    StaticJsonDocument<320> doc;
    doc["device_id"] = device_id;
    doc["ts"]        = get_epoch();
    doc["seq"]       = seq++;
    doc["rssi"]      = WiFi.RSSI();

    JsonObject metrics = doc.createNestedObject("metrics");
    metrics["soil_moisture"] = moisture;
    metrics["adc_raw"]       = adc;

    char buffer[320];
    serializeJson(doc, buffer);
    client.publish(telemetry_topic, buffer);
    Serial.printf("[Telemetry] moisture=%.1f%% adc=%d\n", moisture, adc);
}

void send_status() {
    StaticJsonDocument<160> doc;
    doc["online"] = client.connected();
    doc["rssi"]   = WiFi.RSSI();
    doc["uptime"] = (long)(millis() / 1000);

    char buffer[160];
    serializeJson(doc, buffer);
    client.publish(status_topic, buffer);
}

void setup() {
    Serial.begin(115200);
    analogReadResolution(12);  // 0-4095

    // 从 NVS 读回标定基准
    preferences.begin("soil", false);
    dry_val = preferences.getInt("dry", 3200);
    wet_val = preferences.getInt("wet", 1200);
    Serial.printf("[Calibrate] loaded: dry=%d wet=%d\n", dry_val, wet_val);

    setup_wifi();
    setup_time();
    client.setServer(mqtt_server, mqtt_port);
    client.setCallback(callback);
}

void loop() {
    ensure_connection();
    client.loop();

    unsigned long now = millis();
    if (now - last_telemetry_ms > 30000) {  // 遥测每 30s
        last_telemetry_ms = now;
        send_telemetry();
    }
    if (now - last_status_ms > 15000) {  // 心跳每 15s
        last_status_ms = now;
        send_status();
    }
}
