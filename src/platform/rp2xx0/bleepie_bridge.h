#pragma once
#include <stdint.h>

// Shared state between Meshtastic (core0) and the bleepie hexpansion/badge
// subsystem (core1).
//
// core0 (BleepieBridgeThread + BleepieTextTap) publishes mesh status, the node
// list, recent received messages, and the channel list into this struct; core1's
// UART bridge serialises them to the Tildagon badge on request and sets a send
// request when the badge composes a message.
//
// Single-writer-per-field discipline: core0 owns everything except the send-*
// fields (core1 sets, core0 consumes + clears sendPending). Arrays are refreshed
// wholesale by core0 ~1 Hz; `gen` is bumped after each refresh. There is no hard
// lock — a torn read is at worst one cosmetically-wrong row for one badge frame.

#define BLP_MAX_NODES 20
#define BLP_MAX_MSGS  20
#define BLP_MAX_CHANS 8
#define BLP_SHORT     6   // 4-char Meshtastic short name + NUL (padded)
#define BLP_TEXT      64
#define BLP_CHNAME    16

struct BlpNode {
    uint32_t num;
    char shortName[BLP_SHORT];
    int8_t snr;   // dB, rounded
};

struct BlpMsg {
    uint32_t seq;     // monotonic id (for badge-side ordering + dedup)
    uint32_t fromNum; // sender node num; 0 = us (outgoing)
    uint32_t peer;    // for DMs: the other party's node num; 0 for channel msgs
    char from[BLP_SHORT];  // display short name of sender ("me" if outgoing)
    uint8_t ch;       // channel index (channel broadcasts)
    uint8_t direct;   // 1 = direct message, 0 = channel broadcast
    char text[BLP_TEXT];
};

struct BlpChan {
    uint8_t index;   // real Meshtastic channel index (list may skip empty ones)
    char name[BLP_CHNAME];
};

struct BleepieBridge {
    // --- status ---
    char myName[BLP_SHORT];
    volatile uint16_t nodeCount;
    volatile uint32_t rxCount;
    volatile uint32_t txCount;

    // --- node list ---
    volatile uint8_t numNodes;
    struct BlpNode nodes[BLP_MAX_NODES];

    // --- channel list ---
    volatile uint8_t numChans;
    struct BlpChan chans[BLP_MAX_CHANS];

    // --- received-message ring (newest at msgs[(head-1) mod MAX]) ---
    volatile uint8_t numMsgs;   // valid entries, 0..BLP_MAX_MSGS
    volatile uint8_t msgHead;   // next write slot
    struct BlpMsg msgs[BLP_MAX_MSGS];

    // --- badge -> mesh send request (core1 sets, core0 consumes) ---
    volatile bool sendPending;
    uint8_t  sendIsNode;   // 1 => sendDest is a node num (DM); 0 => channel index
    uint32_t sendDest;
    char sendText[200];

    volatile uint32_t gen;  // bumped by core0 after each snapshot refresh
};

#ifdef __cplusplus
extern "C" {
#endif
extern struct BleepieBridge g_bleepieBridge;
#ifdef __cplusplus
}
#endif
