// HA MCU Bridge sketch: registers a single RPC endpoint so the Linux
// side (python/main.py) can drive MCU pins. Pin table mirrors the
// unoq-pin-toggle example; the RGB user LEDs are active-low, which the
// Python side compensates for before calling here.

#include <Arduino_RouterBridge.h>

struct PinEntry { const char* name; uint8_t pin; };

static const PinEntry kPins[] = {
  {"D2",  D2 }, {"D3",  D3 }, {"D4",  D4 }, {"D5",  D5 },
  {"D6",  D6 }, {"D7",  D7 }, {"D8",  D8 }, {"D9",  D9 },
  {"D10", D10}, {"D11", D11}, {"D12", D12}, {"D13", D13},
  {"LED3_R", LED_BUILTIN},     {"LED3_G", LED_BUILTIN + 1},
  {"LED3_B", LED_BUILTIN + 2}, {"LED4_R", LED_BUILTIN + 3},
  {"LED4_G", LED_BUILTIN + 4}, {"LED4_B", LED_BUILTIN + 5},
};

static inline int findIndex(const char* n) {
  for (size_t i = 0; i < sizeof(kPins) / sizeof(kPins[0]); ++i) {
    if (strcmp(kPins[i].name, n) == 0) return (int)i;
  }
  return -1;
}

void set_pin_by_name(String name, bool s) {
  int idx = findIndex(name.c_str());
  if (idx < 0) return;
  digitalWrite(kPins[idx].pin, s ? HIGH : LOW);
}

void setup() {
  for (auto &e : kPins) pinMode(e.pin, OUTPUT);
  // RGB user LEDs are active-low: HIGH == off.
  for (int i = 0; i < 6; ++i) digitalWrite(LED_BUILTIN + i, HIGH);

  Bridge.begin();
  Bridge.provide("set_pin_by_name", set_pin_by_name);
}

void loop() {}
