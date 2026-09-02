// Probe sketch for issue #40. LED3's R/G/B pads (PH10/11/12) are
// declared BOTH as gpio-leds and as TIM5 PWM channels in the UNO Q
// devicetree. The Arduino core's analogWrite() only calls
// pwm_set_pulse_dt() -- it never re-applies pinctrl -- so a pad left
// in GPIO mode may swallow the PWM signal. These three endpoints
// separate the possible outcomes:
//
//   pwm_raw        analogWrite on a pad never touched by pinMode
//   pwm_after_gpio pinMode(OUTPUT) first, then analogWrite
//   gpio_set       the known-working digitalWrite path (control)
//
// setup() deliberately leaves LED3 alone so pwm_raw gets a clean pad.

#include <Arduino_RouterBridge.h>

// NOTE: pwm_pin_index() cannot be called from a sketch -- GCC inlines
// it into analogWrite() and no symbol survives in core.a. The pin ->
// PWM channel mapping was verified statically instead: LED_BUILTIN is
// index 50 in digital-pin-gpios (gpioh 0xa) and gpioh 0xa/b/c are
// entries 6/7/8 of pwm-pin-gpios, so analogWrite(LED_BUILTIN + 0..2)
// resolves to pwm5 channels 1..3.

// LED3 red/green/blue live at LED_BUILTIN + 0/1/2; LED4 at + 3/4/5.
// All six are active-low. The LED3 PWM channels are declared with
// inverted polarity in the devicetree, which cancels the active-low
// wiring: analogWrite(255) is full brightness, analogWrite(0) is off.
static const int kLed3Channels = 3;

void pwm_raw(int r, int g, int b) {
  analogWrite(LED_BUILTIN + 0, r);
  analogWrite(LED_BUILTIN + 1, g);
  analogWrite(LED_BUILTIN + 2, b);
}

void pwm_after_gpio(int r, int g, int b) {
  for (int i = 0; i < kLed3Channels; ++i) pinMode(LED_BUILTIN + i, OUTPUT);
  analogWrite(LED_BUILTIN + 0, r);
  analogWrite(LED_BUILTIN + 1, g);
  analogWrite(LED_BUILTIN + 2, b);
}

// Control path: nonzero means the channel is fully on (active-low, so
// LOW lights the LED).
void gpio_set(int r, int g, int b) {
  const int wanted[kLed3Channels] = {r, g, b};
  for (int i = 0; i < kLed3Channels; ++i) {
    pinMode(LED_BUILTIN + i, OUTPUT);
    digitalWrite(LED_BUILTIN + i, wanted[i] > 0 ? LOW : HIGH);
  }
}

// Introspection: which Arduino pin number does LED_BUILTIN resolve to?
int led_builtin_pin() {
  return (int)LED_BUILTIN;
}

void setup() {
  Bridge.begin();
  Bridge.provide("led_builtin_pin", led_builtin_pin);
  Bridge.provide("pwm_raw", pwm_raw);
  Bridge.provide("pwm_after_gpio", pwm_after_gpio);
  Bridge.provide("gpio_set", gpio_set);
}

void loop() {}
