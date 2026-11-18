#include <Arduino.h>
#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include "../include/config.h"

// ============================================================
// 诊断固件：不读任何传感器，只连 WiFi + MQTT，每 2 秒上报固定测试值。
// 目的：二分定位——若后端能看到 25.5℃ 说明网络层 OK，问题在原固件的
//       RS485 读取；若看不到，问题在 WiFi/MQTT 连接本身。
// ============================================================
const char* DEV = "k10-field-01";
const char* TOPIC_TELEMETRY = "tea/device/k10-field-01/telemetry";
const char* TOPIC_STATUS    = "tea/device/k10-field-01/status";

WiFiClient espClient;
PubSubClient client(espClient);
unsigned long seq = 0;
unsigned long last_pub = 0;

void setup() {
    Serial.begin(115200);
    delay(300);
    Serial.println("\n=== DIAG FIRMWARE BOOT ===");

    WiFi.mode(WIFI_STA);
    WiFi.begin(ssid, password);
    Serial.printf("[DIAG] WiFi connecting to %s\n", ssid);
    unsigned long t0 = millis();
    while (WiFi.status() != WL_CONNECTED && millis() - t0 < 20000) {
        delay(500);
        Serial.print(".");
    }
    Serial.println();
    Serial.printf("[DIAG] WiFi status=%d ip=%s\n",
                  WiFi.status(), WiFi.localIP().toString().c_str());

    client.setServer(mqtt_server, mqtt_port);
    client.setBufferSize(512);
}

void loop() {
    if (WiFi.status() != WL_CONNECTED) {
        delay(1000);
        return;
    }
    if (!client.connected()) {
        Serial.printf("[DIAG] MQTT connecting to %s:%d...\n", mqtt_server, mqtt_port);
        bool ok = client.connect(DEV, mqtt_user, mqtt_password);
        Serial.printf("[DIAG] MQTT connect result=%d\n", ok);
        if (!ok) { delay(3000); return; }
        Serial.println("[DIAG] MQTT CONNECTED");
    }
    client.loop();

    if (millis() - last_pub > 2000) {
        last_pub = millis();
        StaticJsonDocument<256> doc;
        doc["device_id"] = DEV;
        doc["ts"] = (long)(millis() / 1000);   // 后端会纠正为服务器时间
        doc["seq"] = seq++;
        doc["rssi"] = WiFi.RSSI();
        JsonObject m = doc.createNestedObject("metrics");
        m["temperature_c"] = 25.5;             // ★显眼测试值
        m["humidity_air"]  = 50.0;
        m["lux"]           = 500;
        char buf[256];
        size_t len = serializeJson(doc, buf);
        client.publish(TOPIC_TELEMETRY, buf, len);
        client.publish(TOPIC_STATUS, "{\"online\":true,\"rssi\":-50,\"uptime\":1}");
        Serial.printf("[DIAG] published seq=%lu len=%u\n", seq, len);
    }
}
