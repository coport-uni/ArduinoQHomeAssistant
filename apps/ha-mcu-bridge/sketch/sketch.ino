// HA MCU Bridge sketch: registers the RPC endpoints the Linux side
// (python/main.py) drives. set_led3_rgb and set_led4_rgb back the two
// Home Assistant MQTT lights, set_pin_by_name drives header pins for
// the optional MQTT switches, and show_load renders CPU/memory bars on
// the on-board 8x13 LED matrix. Pin table mirrors the unoq-pin-toggle
// example.
//
// LED3 (PH10/11/12) is the only user LED with PWM channels behind it
// (pwm5 ch1-3, 500 Hz, inverted polarity in the devicetree, which
// cancels the active-low wiring: 255 is full brightness, 0 is off), so
// it gets true 24-bit colour and brightness through analogWrite.
//
// CRITICAL: never call pinMode() or digitalWrite() on the LED3 pins.
// analogWrite() only calls pwm_set_pulse_dt() and never re-applies
// pinctrl, so once a pad has been configured for GPIO the PWM signal
// stops reaching it until the MCU is reset. Verified on hardware --
// see claude_test/led3_pwm_probe. LED4 (PH13/14/15) has no PWM
// mapping and is GPIO-only, which is why it is on/off per channel.

#include <Arduino_RouterBridge.h>

// LED matrix (8 rows x 13 cols, 104 blue LEDs). These symbols come
// from the base firmware (variant syms-dynamic.ld) -- no library
// entry in sketch.yaml is needed. Raw frame format (verified against
// the official air-quality example icons, see
// claude_test/decode_matrix_frame.py): pixel i = row*13 + col lives
// at word[i/32], bit i%32; row 0 = top, col 0 = left.
extern "C" void matrixBegin();
extern "C" void matrixWrite(const uint32_t* buf);

static const int kMatrixCols = 13;
// Bar row assignments (user-chosen layout): rows 1-2 CPU, row 3
// blank, rows 4-6 MEM, rows 0/7 dark margins.
static const int kCpuRowStart = 1;
static const int kCpuRowEnd   = 2;
static const int kMemRowStart = 4;
static const int kMemRowEnd   = 6;

// LED3 red/green/blue sit at LED_BUILTIN + 0/1/2, LED4 at + 3/4/5.
static const int kLed3Red   = LED_BUILTIN + 0;
static const int kLed4Red   = LED_BUILTIN + 3;
static const int kRgbChannels = 3;

struct PinEntry { const char* name; uint8_t pin; };

// Header pins only. The LED3 channels are deliberately absent so no
// code path can put those pads into GPIO mode and kill their PWM;
// LED4 is driven by set_led4_rgb() instead of by name.
static const PinEntry kPins[] = {
  {"D2",  D2 }, {"D3",  D3 }, {"D4",  D4 }, {"D5",  D5 },
  {"D6",  D6 }, {"D7",  D7 }, {"D8",  D8 }, {"D9",  D9 },
  {"D10", D10}, {"D11", D11}, {"D12", D12}, {"D13", D13},
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

// Each argument is a 0-255 duty cycle already scaled for brightness by
// the Python side.
void set_led3_rgb(int r, int g, int b) {
  analogWrite(kLed3Red + 0, r);
  analogWrite(kLed3Red + 1, g);
  analogWrite(kLed3Red + 2, b);
}

// LED4 has no PWM channels, so any nonzero channel is fully on. The
// LEDs are active-low: LOW lights them.
void set_led4_rgb(int r, int g, int b) {
  const int wanted[kRgbChannels] = {r, g, b};
  for (int i = 0; i < kRgbChannels; ++i) {
    digitalWrite(kLed4Red + i, wanted[i] > 0 ? LOW : HIGH);
  }
}

static inline void setPixel(uint32_t* frame, int row, int col) {
  int i = row * kMatrixCols + col;
  frame[i / 32] |= (1UL << (i % 32));
}

// Map 0-100 % to 0-13 bar columns, round-to-nearest, but any nonzero
// load lights at least one LED so small loads stay visible.
static int barCols(int pct) {
  if (pct < 0) pct = 0;
  if (pct > 100) pct = 100;
  int cols = (pct * kMatrixCols + 50) / 100;
  if (pct > 0 && cols == 0) cols = 1;
  return cols;
}

void show_load(int cpu, int mem) {
  uint32_t frame[4] = {0, 0, 0, 0};
  int cpuCols = barCols(cpu);
  int memCols = barCols(mem);
  for (int r = kCpuRowStart; r <= kCpuRowEnd; ++r) {
    for (int c = 0; c < cpuCols; ++c) setPixel(frame, r, c);
  }
  for (int r = kMemRowStart; r <= kMemRowEnd; ++r) {
    for (int c = 0; c < memCols; ++c) setPixel(frame, r, c);
  }
  matrixWrite(frame);
}

void setup() {
  for (auto &e : kPins) pinMode(e.pin, OUTPUT);

  // LED4 is GPIO; start it off (active-low, so HIGH is off).
  for (int i = 0; i < kRgbChannels; ++i) {
    pinMode(kLed4Red + i, OUTPUT);
    digitalWrite(kLed4Red + i, HIGH);
  }
  // LED3 is claimed by PWM only -- no pinMode here, on purpose.
  set_led3_rgb(0, 0, 0);

  matrixBegin();
  const uint32_t clear_frame[4] = {0, 0, 0, 0};
  matrixWrite(clear_frame);

  Bridge.begin();
  Bridge.provide("set_pin_by_name", set_pin_by_name);
  Bridge.provide("set_led3_rgb", set_led3_rgb);
  Bridge.provide("set_led4_rgb", set_led4_rgb);
  Bridge.provide("show_load", show_load);
}

void loop() {}
