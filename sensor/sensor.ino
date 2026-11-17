// lennysleep sensor - Nano 33 BLE Sense Rev1 (LSM9DS1 0x6B, LPS22HB 0x5C, APDS9960 0x39).
// Raw I2C registers, no extra libraries. This unit has no HTS221, so humidity is blank.
// Every PERIOD_MS prints: movement,temp_c,humidity,light,loud_rms
// movement = # of 10 Hz IMU samples whose accel changed > MOVE_G since the last sample
// loud_rms = loudest 1-second RMS of the mic in the period. Audio is never stored or sent.
#include <Wire.h>
#include <PDM.h>

#ifndef PERIOD_MS
#define PERIOD_MS 60000
#endif
const float MOVE_G = 0.03;
const uint8_t IMU = 0x6B, BARO = 0x5C, LUX = 0x39;

short pdmBuf[512];
volatile double pdmSum = 0, pdmSq = 0;
volatile uint32_t pdmN = 0;

void onPDM() {
  int bytes = PDM.available();
  PDM.read(pdmBuf, bytes);
  for (int i = 0; i < bytes / 2; i++) { pdmSum += pdmBuf[i]; pdmSq += (double)pdmBuf[i] * pdmBuf[i]; }
  pdmN += bytes / 2;
}

void wr(uint8_t a, uint8_t r, uint8_t v) { Wire1.beginTransmission(a); Wire1.write(r); Wire1.write(v); Wire1.endTransmission(); }
bool rd(uint8_t a, uint8_t r, uint8_t *d, uint8_t k) {
  Wire1.beginTransmission(a); Wire1.write(r);
  if (Wire1.endTransmission(false) || Wire1.requestFrom(a, k) != k) return false;
  for (int i = 0; i < k; i++) d[i] = Wire1.read();
  return true;
}
int16_t s16(uint8_t *d) { return (int16_t)(d[0] | d[1] << 8); }

float px, py, pz, peakRms, tempC = NAN;
uint32_t moves, light, tImu, tSec, tOut;

void setup() {
  Serial.begin(115200);
  pinMode(PIN_ENABLE_SENSORS_3V3, OUTPUT); digitalWrite(PIN_ENABLE_SENSORS_3V3, HIGH);
  pinMode(PIN_ENABLE_I2C_PULLUP, OUTPUT); digitalWrite(PIN_ENABLE_I2C_PULLUP, HIGH);
  delay(50);
  Wire1.begin();
  wr(IMU, 0x20, 0x40);                     // accel 50 Hz, +-2 g
  wr(BARO, 0x10, 0x10);                    // LPS22HB 1 Hz continuous
  wr(LUX, 0x81, 0x00); wr(LUX, 0x8F, 0x01); // ATIME 712 ms, gain 4x
  wr(LUX, 0x80, 0x03);                     // power on + ambient light
  PDM.onReceive(onPDM);
  PDM.begin(1, 16000);
  uint8_t d[6];
  if (rd(IMU, 0x28, d, 6)) { px = s16(d) * 0.000061; py = s16(d + 2) * 0.000061; pz = s16(d + 4) * 0.000061; }
  tImu = tSec = tOut = millis();
}

void loop() {
  uint32_t now = millis();
  uint8_t d[6];
  if (now - tImu >= 100) {
    tImu = now;
    if (rd(IMU, 0x28, d, 6)) {
      float x = s16(d) * 0.000061, y = s16(d + 2) * 0.000061, z = s16(d + 4) * 0.000061;
      if (fabs(x - px) + fabs(y - py) + fabs(z - pz) > MOVE_G) moves++;
      px = x; py = y; pz = z;
    }
  }
  if (now - tSec >= 1000) {
    tSec = now;
    noInterrupts(); double s = pdmSum, q = pdmSq; uint32_t n = pdmN; pdmSum = pdmSq = 0; pdmN = 0; interrupts();
    if (n) { double m = s / n, v = q / n - m * m; float r = v > 0 ? sqrt(v) : 0; if (r > peakRms) peakRms = r; }
    if (rd(BARO, 0x2B, d, 2)) tempC = s16(d) / 100.0;
    if (rd(LUX, 0x94, d, 2)) light = d[0] | d[1] << 8;
  }
  if (now - tOut >= PERIOD_MS) {
    tOut = now;
    char line[64];
    snprintf(line, sizeof line, "%lu,%.2f,,%lu,%.1f", moves, tempC, light, peakRms);
    if (Serial) Serial.println(line);
    moves = 0; peakRms = 0;
  }
}
