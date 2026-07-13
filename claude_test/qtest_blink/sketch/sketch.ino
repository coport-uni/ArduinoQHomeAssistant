/* Blink the built-in LED to prove the STM32U585 (MCU) side of the
 * UNO Q can be compiled and flashed purely over WiFi + SSH. */

const unsigned long blink_period_ms = 100;

void setup() {
  pinMode(LED_BUILTIN, OUTPUT);
}

void loop() {
  digitalWrite(LED_BUILTIN, HIGH);
  delay(blink_period_ms);
  digitalWrite(LED_BUILTIN, LOW);
  delay(blink_period_ms);
}
