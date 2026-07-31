// BleepieMeshtastic — Waveshare RP2040-Tiny + Ai-Thinker Ra-01SH (SX1262)
//
// Same board as the bleepie POCSAG/MeshCore/LoRaWAN firmwares. Wiring confirmed
// on hardware: SX1262 on SPI0 (GPIO0-3), IRQ on DIO1, external TXEN/RXEN antenna
// switch, and a crystal (XTAL) rather than a TCXO. Client access is USB-serial
// only (bare RP2040 has no BLE/WiFi).

#define HAS_CPU_SHUTDOWN 1
#define USE_SX1262

// --- LoRa SPI bus (SPI0) ---
// No HW_SPI1_DEVICE => main.cpp drives the default SPI (spi0) with these pins.
#undef LORA_SCK
#undef LORA_MISO
#undef LORA_MOSI
#undef LORA_CS

#define LORA_SCK 2   // GPIO2
#define LORA_MISO 0  // GPIO0
#define LORA_MOSI 3  // GPIO3
#define LORA_CS 1    // GPIO1

#define LORA_DIO0 RADIOLIB_NC // not used by SX126x
#define LORA_RESET 26         // GPIO26
#define LORA_BUSY 4           // GPIO4
#define LORA_DIO1 6           // GPIO6 (IRQ)
#define LORA_DIO2 RADIOLIB_NC
#define LORA_DIO3 RADIOLIB_NC

#ifdef USE_SX1262
#define SX126X_CS LORA_CS
#define SX126X_DIO1 LORA_DIO1
#define SX126X_BUSY LORA_BUSY
#define SX126X_RESET LORA_RESET
// Ra-01SH switches its antenna with EXTERNAL TXEN/RXEN lines (not DIO2). Do NOT
// define SX126X_DIO2_AS_RF_SWITCH; defining RXEN/TXEN makes SX126xInterface call
// setRfSwitchPins(RXEN, TXEN).
#define SX126X_RXEN 8 // GPIO8
#define SX126X_TXEN 5 // GPIO5
// Ra-01SH is crystal-based: leave SX126X_DIO3_TCXO_VOLTAGE undefined (=> XTAL).
#endif

// --- Status NeoPixel (WS2812 on GPIO16) ---
#define HAS_NEOPIXEL
#define NEOPIXEL_COUNT 1
#define NEOPIXEL_DATA 16
#define NEOPIXEL_TYPE (NEO_GRB + NEO_KHZ800)

// --- Buzzer -> ExternalNotificationModule (auto-wired in NodeDB when PIN_BUZZER set) ---
#define PIN_BUZZER 15

// No user button wired on this board.
#define BUTTON_PIN -1

// Note: the Tildagon hexpansion I2C-slave EEPROM emulation and badge UART bridge
// (Phase B) live on core1 and use i2c0 on GPIO12/13 and Serial1 on GPIO28/29 —
// added as a separate compilation unit gated by BLEEPIE_MESHTASTIC, not here.
