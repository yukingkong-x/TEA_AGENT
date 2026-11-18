#include <Arduino.h>
#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include "../include/config.h"

// ============================================================
// k10_rs485 · 行空板 K10 直读两个 RS485 传感器
// 设计原则：loop 永不阻塞——无论传感器读到与否，都每 2 秒上报一次，
//           并在 metrics 里带 w_ok/s_ok 标志，便于无串口时远程诊断。
//   气象 -> tea/device/k10-field-01/telemetry
//   土壤 -> tea/device/esp32-soil-02/telemetry
// ============================================================
const char* DEV_FIELD = "k10-field-01";
const char* DEV_SOIL  = "esp32-soil-02";
const char* TOPIC_FIELD_TELEMETRY = "tea/device/k10-field-01/telemetry";
const char* TOPIC_SOIL_TELEMETRY  = "tea/device/esp32-soil-02/telemetry";
const char* TOPIC_FIELD_STATUS    = "tea/device/k10-field-01/status";
const char* TOPIC_SOIL_STATUS     = "tea/device/esp32-soil-02/status";

const uint16_t WEATHER_REG_START = 0x01F8;
const uint8_t  WEATHER_REG_COUNT = 8;
const uint16_t SOIL_REG_START    = 0x0000;
const uint8_t  SOIL_REG_COUNT    = 4;

HardwareSerial rs485(RS485_UART_NUM);
WiFiClient espClient;
PubSubClient client(espClient);

unsigned long seq = 0, last_pub = 0, mqtt_retry = 0;
float g_temp=-1, g_humi=-1, g_lux=-1, g_pressure=-1, g_wind=-1, g_noise=-1;
float g_soil_moisture=-1, g_soil_temp=-1;
uint16_t g_soil_raw=0;
int g_w_ok=0, g_s_ok=0, rs485_inited=0;
int g_w_raw=0, g_s_raw=0;   // 最近一次收到的字节数（诊断用）

// 自动方向模块：把 TX 强制拉高，逼模块回到接收模式
void force_rx_mode() {
    pinMode(RS485_TX_PIN, INPUT_PULLUP);
    delay(3);
}

uint16_t crc16(const uint8_t* d, size_t n) {
    uint16_t crc = 0xFFFF;
    for (size_t i=0;i<n;i++){ crc ^= d[i]; for(int j=0;j<8;j++){ crc = (crc&1)?(crc>>1)^0xA001:(crc>>1); } }
    return crc;
}

// 返回: 1=成功, 0=无响应, -1=CRC错, -2=帧头/字节数错; raw_n 带回收到的字节数
int modbus_read_once(uint8_t addr, uint16_t reg, uint8_t count, uint16_t* out, int* raw_n) {
    uint8_t f[8];
    f[0]=addr; f[1]=0x03; f[2]=(reg>>8)&0xFF; f[3]=reg&0xFF; f[4]=0; f[5]=count;
    uint16_t crc=crc16(f,6); f[6]=crc&0xFF; f[7]=(crc>>8)&0xFF;
    force_rx_mode();                    // 发送前强制接收模式，清掉残留
    while (rs485.available()) rs485.read();
    pinMode(RS485_TX_PIN, OUTPUT);      // 交还 UART 控制发送
    rs485.write(f,8);
    rs485.flush();
    force_rx_mode();                    // ★发完立即强制回接收模式（关键）
    unsigned long t0=millis();
    while (rs485.available()<5 && millis()-t0<600) delay(1);
    delay(15);
    uint8_t b[64]; int n=0;
    while (rs485.available() && n<(int)sizeof(b)) b[n++]=rs485.read();
    *raw_n = n;
    if (n<5) return 0;
    // 找响应帧头：addr + 0x03(无异常位) + 字节数在合理范围
    int pos=-1;
    for (int i=0;i<=n-5;i++) {
        if (b[i]==addr && b[i+1]==0x03 && b[i+2]>=2 && b[i+2]<=16 && (i+3+b[i+2]+1<n+1)) { pos=i; break; }
    }
    if (pos<0) return -2;
    uint8_t* p=b+pos;
    uint8_t bc=p[2];
    if (n-pos < 3+bc+2) return -2;
    if (crc16(p,3+bc) != (uint16_t)(p[3+bc]|(p[4+bc]<<8))) return -1;
    for (int i=0;i<bc/2 && i<count;i++) out[i]=(p[3+i*2]<<8)|p[4+i*2];
    return 1;
}

// 失败自动重试 4 次；返回最终错误码（成功=1）
int g_last_w_err=0, g_last_s_err=0;
int modbus_read(uint8_t addr, uint16_t reg, uint8_t count, uint16_t* out, int* raw_n) {
    int r=-9;
    for (int attempt=0; attempt<4; attempt++) {
        r = modbus_read_once(addr, reg, count, out, raw_n);
        if (r==1) return 1;
        delay(100);
    }
    return r;
}

void read_sensors() {
    if (!rs485_inited) return;
    uint16_t w[8], s[4];
    // 每次采集前硬复位 UART，尝试解锁自动方向模块的锁死状态
    rs485.end();
    delay(20);
    rs485.begin(RS485_BAUD, SERIAL_8N1, RS485_RX_PIN, RS485_TX_PIN);
    delay(20);
    g_last_w_err = modbus_read(WEATHER_ADDR, WEATHER_REG_START, WEATHER_REG_COUNT, w, &g_w_raw);
    g_w_ok = (g_last_w_err==1) ? 1 : 0;
    if (g_w_ok) {
        g_humi=w[0]*0.1f; g_temp=w[1]*0.1f; g_noise=w[2]*0.1f; g_wind=w[3]*0.1f;
        g_pressure=w[5]*0.1f; g_lux=(float)w[7];
    }
    delay(300);   // 两个从站之间给总线足够恢复时间
    g_last_s_err = modbus_read(SOIL_ADDR, SOIL_REG_START, SOIL_REG_COUNT, s, &g_s_raw);
    g_s_ok = (g_last_s_err==1) ? 1 : 0;
    if (g_s_ok) { g_soil_moisture=s[0]*0.1f; g_soil_temp=s[1]*0.1f; g_soil_raw=s[0]; }
}

void setup() {
    Serial.begin(115200);
    delay(200);
    Serial.println("\n=== k10_rs485 boot ===");

    WiFi.mode(WIFI_STA);
    WiFi.begin(ssid, password);
    Serial.print("[WiFi] connecting");
    unsigned long t0=millis();
    while (WiFi.status()!=WL_CONNECTED && millis()-t0<20000) { delay(500); Serial.print("."); }
    Serial.println();
    Serial.printf("[WiFi] status=%d ip=%s\n", WiFi.status(), WiFi.localIP().toString().c_str());

    client.setServer(mqtt_server, mqtt_port);
    client.setBufferSize(512);

    // RS485 放在最后初始化，避免影响 WiFi/MQTT 启动
    rs485.begin(RS485_BAUD, SERIAL_8N1, RS485_RX_PIN, RS485_TX_PIN);
    rs485_inited = 1;
    Serial.printf("[CFG] RS485 TX=%d RX=%d @%ld addr 0x%02X/0x%02X\n",
                  RS485_TX_PIN, RS485_RX_PIN, RS485_BAUD, WEATHER_ADDR, SOIL_ADDR);
}

void loop() {
    if (WiFi.status()!=WL_CONNECTED) { delay(500); return; }
    if (!client.connected()) {
        if (millis()-mqtt_retry>2000) {
            mqtt_retry=millis();
            client.connect(DEV_FIELD, mqtt_user, mqtt_password);
        }
        delay(50);
        return;
    }
    client.loop();

    if (millis()-last_pub>5000) {
        last_pub=millis();
        read_sensors();

        StaticJsonDocument<256> f;
        f["device_id"]=DEV_FIELD; f["ts"]=(long)(millis()/1000); f["seq"]=seq++; f["rssi"]=WiFi.RSSI();
        JsonObject fm=f.createNestedObject("metrics");
        fm["temperature_c"]=g_w_ok?g_temp:-999;
        fm["humidity_air"]=g_w_ok?g_humi:-999;
        fm["lux"]=g_w_ok?g_lux:-999;
        fm["pressure"]=g_w_ok?g_pressure:-999;
        fm["w_ok"]=g_w_ok;
        fm["w_err"]=g_last_w_err;   // 1=成功 0=无响应 -1=CRC错 -2=帧头错
        fm["w_raw"]=g_w_raw;        // 收到的字节数
        char fb[256]; size_t fl=serializeJson(f,fb);
        client.publish(TOPIC_FIELD_TELEMETRY, fb, fl);

        StaticJsonDocument<256> s;
        s["device_id"]=DEV_SOIL; s["ts"]=(long)(millis()/1000); s["seq"]=seq++; s["rssi"]=WiFi.RSSI();
        JsonObject sm=s.createNestedObject("metrics");
        sm["soil_moisture"]=g_s_ok?g_soil_moisture:-999;
        sm["adc_raw"]=g_s_ok?g_soil_raw:0;
        sm["soil_temp"]=g_s_ok?g_soil_temp:-999;
        sm["s_ok"]=g_s_ok;
        sm["s_err"]=g_last_s_err;
        sm["s_raw"]=g_s_raw;
        char sb[256]; size_t sl=serializeJson(s,sb);
        client.publish(TOPIC_SOIL_TELEMETRY, sb, sl);

        client.publish(TOPIC_FIELD_STATUS, "{\"online\":true,\"rssi\":-50,\"uptime\":1}");
        client.publish(TOPIC_SOIL_STATUS, "{\"online\":true,\"rssi\":-50,\"uptime\":1}");
        Serial.printf("[PUB] w_ok=%d s_ok=%d temp=%.1f soil=%.1f\n", g_w_ok,g_s_ok,g_temp,g_soil_moisture);
    }
}
