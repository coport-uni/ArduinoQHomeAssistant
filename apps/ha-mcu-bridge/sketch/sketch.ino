// HA MCU Bridge sketch: registers two RPC endpoints for the Linux
// side (python/main.py). set_pin_by_name drives MCU pins for the Home
// Assistant MQTT switches; show_load renders CPU/memory bars on the
// on-board 8x13 LED matrix. Pin table mirrors the unoq-pin-toggle
// example; the RGB user LEDs are active-low, which the Python side
// compensates for before calling here.

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
  // RGB user LEDs are active-low: HIGH == off.
  for (int i = 0; i < 6; ++i) digitalWrite(LED_BUILTIN + i, HIGH);

  matrixBegin();
  const uint32_t clear_frame[4] = {0, 0, 0, 0};
  matrixWrite(clear_frame);

  Bridge.begin();
  Bridge.provide("set_pin_by_name", set_pin_by_name);
  Bridge.provide("show_load", show_load);
}

void loop() {}
