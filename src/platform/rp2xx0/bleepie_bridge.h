#pragma once
#include <stdint.h>

// Shared state between Meshtastic (core0) and the bleepie hexpansion/badge
// subsystem (core1). Core0 publishes mesh status into `mt`; core1's UART bridge
// reads it to answer the badge and sets `sendPending`/`sendText` when the badge
// asks to transmit. Kept deliberately simple (single-writer per field); a
// spinlock can be added if field-tearing on the strings becomes an issue.
struct BleepieBridge {
    volatile uint16_t nodeCount;
    char shortName[8];
    char lastMsg[64];

    // Badge -> mesh outbound request (core1 sets, core0 consumes + clears).
    volatile bool sendPending;
    char sendText[200];
};

#ifdef __cplusplus
extern "C" {
#endif
extern struct BleepieBridge g_bleepieBridge;
#ifdef __cplusplus
}
#endif
