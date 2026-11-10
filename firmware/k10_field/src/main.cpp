#include <Arduino.h>
#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <DFRobot_AHT20.h>
#include <DFRobot_GDL.h>
#include <time.h>
#include "../include/config.h"

// ===== 设备信息（主题规划 = PRD 5.1）=====
const char* device_id       = "k10-field-01";
const char* telemetry_topic = "tea/device/k10-field-01/telemetry";
const char* status_topic    = "tea/device/k10-field-01/status";
const char* cmd_topic       = "tea/device/k10-field-01/cmd";
const char* ack_topic       = "tea/device/k10-field-01/ack";

// ===== 屏幕配置（K10 板载 ST7789）=====
#define TFT_DC  13
#define TFT_CS  7
#define TFT_RST 14
#define TFT_BL  21
// DFRobot_GDL 未提供灰色，手动定义 RGB565 灰色（离线状态点用）
#ifndef COLOR_RGB565_GREY
#define COLOR_RGB565_GREY 0x8410
#endif
DFRobot_ST7789_240x320_HW_SPI screen(TFT_DC, TFT_CS, TFT_RST);

WiFiClient espClient;
PubSubClient client(espClient);
DFRobot_AHT20 aht20;
bool aht20_ok = false;

unsigned long last_telemetry_ms = 0;
unsigned long last_status_ms    = 0;
unsigned long seq               = 0;
float cur_temp = 0, cur_humi = 0;
int   cur_lux  = 0;

// ===== MQTT 指数退避重连（PRD 4.3 第5条：1s/2s/4s/...上限30s）=====
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
    if (t < 1700000000) {
        // NTP 尚未同步，退化为运行秒数（后端可识别）
        return (long)(millis() / 1000);
    }
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

void update_display() {
    screen.fillScreen(COLOR_RGB565_BLACK);
    screen.setTextSize(2);
    screen.setTextColor(COLOR_RGB565_GREEN);
    screen.setCursor(10, 10);
    screen.println("TEA AGENT - FIELD");

    screen.setTextSize(1);
    // 在线状态点：绿=在线，灰=离线
    screen.fillCircle(230, 14, 5, client.connected() ? COLOR_RGB565_GREEN : COLOR_RGB565_GREY);
    screen.setTextColor(COLOR_RGB565_WHITE);
    screen.setCursor(10, 40);
    screen.printf("ID: %s", device_id);
    screen.setCursor(10, 60);
    screen.printf("IP: %s", WiFi.localIP().toString().c_str());
    screen.setCursor(10, 80);
    screen.printf("Status: %s", client.connected() ? "ONLINE" : "OFFLINE");

    screen.setTextSize(2);
    screen.setCursor(10, 120);
    screen.printf("Temp: %.1f C", cur_temp);
    screen.setCursor(10, 150);
    screen.printf("Humi: %.1f %%", cur_humi);
    screen.setCursor(10, 180);
    screen.printf("Lux: %d", cur_lux);
}

void setup_wifi() {
    WiFi.setAutoReconnect(true);  // WiFi 断线自动重连
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
    StaticJsonDocument<384> doc;
    DeserializationError err = deserializeJson(doc, payload, length);
    if (err) return;

    const char* action  = doc["action"] | "";
    const char* msg_id  = doc["msg_id"] | "";
    const char* task_id = doc["task_id"] | "";

    if (strcmp(action, "read_now") == 0) {
        // PRD 4.3 第4条：先回 received，执行完回 finished
        send_ack(msg_id, task_id, "received", "done");
        last_telemetry_ms = 0;  // 触发立即补测上报
        send_ack(msg_id, task_id, "finished", "done");
    } else if (strcmp(action, "reboot") == 0) {
        send_ack(msg_id, task_id, "received", "done");
        delay(200);
        ESP.restart();
    }
}

void ensure_connection() {
    if (WiFi.status() != WL_CONNECTED) {
        // WiFi 由 autoReconnect 处理，MQTT 等 WiFi 恢复后再试
        return;
    }
    if (client.connected()) {
        backoff_ms = 1000;  // 连接正常，重置退避
        return;
    }
    if (millis() - last_mqtt_attempt < backoff_ms) return;
    last_mqtt_attempt = millis();

    Serial.printf("[MQTT] connecting... (backoff %lus)\n", backoff_ms / 1000);
    if (client.connect(device_id, mqtt_user, mqtt_password)) {
        Serial.println("[MQTT] connected");
        backoff_ms = 1000;
        // PRD 4.3 第1条：上线即发 online:true，并订阅自己的 cmd 主题
        client.publish(status_topic, "{\"online\": true}");
        client.subscribe(cmd_topic);
        update_display();
    } else {
        backoff_ms = (backoff_ms >= 30000) ? 30000 : backoff_ms * 2;
    }
}

void send_telemetry() {
    StaticJsonDocument<320> doc;
    doc["device_id"] = device_id;
    doc["ts"]        = get_epoch();
    doc["seq"]       = seq++;
    doc["rssi"]      = WiFi.RSSI();

    JsonObject metrics = doc.createNestedObject("metrics");
    metrics["temperature_c"] = cur_temp;
    metrics["humidity_air"]  = cur_humi;
    metrics["lux"]           = cur_lux;

    char buffer[320];
    serializeJson(doc, buffer);
    client.publish(telemetry_topic, buffer);
    Serial.println("[Telemetry] sent");
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

void read_sensors() {
    if (aht20_ok && aht20.startMeasurementReady()) {
        cur_temp = aht20.getTemperature_C();
        cur_humi = aht20.getHumidity_RH();
    }
    // 板载光照传感器：原始 ADC 线性映射为 lux（粗略值，实测后可校准）
    int raw = analogRead(A0);
    cur_lux = map(raw, 0, 4095, 0, 10000);
}

void setup() {
    Serial.begin(115200);

    screen.begin();
    pinMode(TFT_BL, OUTPUT);
    digitalWrite(TFT_BL, HIGH);
    screen.fillScreen(COLOR_RGB565_BLACK);
    screen.setTextSize(2);
    screen.setCursor(10, 10);
    screen.println("Initializing...");

    setup_wifi();
    setup_time();
    client.setServer(mqtt_server, mqtt_port);
    client.setCallback(callback);

    // AHT20 最多等 5 次，失败则降级为只上报光照（PRD 4.1 注：传感器不可用固件降级，平台不受影响）
    for (int i = 0; i < 5; i++) {
        if (aht20.begin() == 0) { aht20_ok = true; break; }
        Serial.println("[AHT20] not found, retrying...");
        delay(1000);
    }
    read_sensors();
    update_display();
}

void loop() {
    ensure_connection();
    client.loop();

    unsigned long now = millis();
    if (now - last_telemetry_ms > 30000) {  // 遥测每 30s
        last_telemetry_ms = now;
        read_sensors();
        send_telemetry();
        update_display();
    }
    if (now - last_status_ms > 15000) {  // 心跳每 15s
        last_status_ms = now;
        send_status();
    }
}
