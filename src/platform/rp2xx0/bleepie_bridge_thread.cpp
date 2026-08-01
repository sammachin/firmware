// BleepieMeshtastic — core0 side of the Tildagon badge bridge.
//
// Publishes mesh status, the node list, the channel list, and recent messages
// (received + our own outgoing) into the shared BleepieBridge snapshot for
// core1's UART bridge, and consumes badge-composed send requests (to a channel
// or a specific node).
//
// Compiled only for the bleepie board. Registered by one guarded line in
// src/modules/Modules.cpp (bleepieBridgeInit()).

#ifdef BLEEPIE_MESHTASTIC

#include "concurrency/OSThread.h"
#include "mesh/MeshService.h"
#include "mesh/NodeDB.h"
#include "mesh/Router.h"
#include "mesh/Channels.h"
#include "mesh/SinglePortModule.h"
#include "bleepie_bridge.h"
#include <Arduino.h>
#include <cstring>
#include <cmath>

// Shared core0<->core1 snapshot (defined here so it exists even when the core1
// hexpansion file is compiled out).
struct BleepieBridge g_bleepieBridge = {};

static uint32_t g_msgSeq = 1; // monotonic message id

static void copyShort(char *dst, const char *src)
{
    strncpy(dst, src, BLP_SHORT - 1);
    dst[BLP_SHORT - 1] = '\0';
}

// Resolve a node number to its short name, or a hex fallback like "!3f".
static void shortNameFor(uint32_t num, char *dst)
{
    meshtastic_NodeInfoLite *n = nodeDB ? nodeDB->getMeshNode(num) : nullptr;
    if (n && n->has_user && n->user.short_name[0]) {
        copyShort(dst, n->user.short_name);
    } else {
        snprintf(dst, BLP_SHORT, "!%02x", (unsigned)(num & 0xFF));
    }
}

// Append a message to the ring (called on core0 only: from the RX tap and from
// the send-consumer, which never run concurrently under cooperative scheduling).
static void pushMsg(uint32_t fromNum, uint32_t peer, const char *fromShort,
                    uint8_t ch, uint8_t direct, const char *text)
{
    BleepieBridge &b = g_bleepieBridge;
    BlpMsg &m = b.msgs[b.msgHead];
    m.seq = g_msgSeq++;
    m.fromNum = fromNum;
    m.peer = peer;
    copyShort(m.from, fromShort);
    m.ch = ch;
    m.direct = direct;
    strncpy(m.text, text, BLP_TEXT - 1);
    m.text[BLP_TEXT - 1] = '\0';
    b.msgHead = (b.msgHead + 1) % BLP_MAX_MSGS;
    if (b.numMsgs < BLP_MAX_MSGS)
        b.numMsgs++;
}

// ---- Received-message tap (writes the ring on core0) ----
class BleepieTextTap : public SinglePortModule
{
  public:
    BleepieTextTap() : SinglePortModule("BleepieTextTap", meshtastic_PortNum_TEXT_MESSAGE_APP) {}

  protected:
    virtual ProcessMessage handleReceived(const meshtastic_MeshPacket &mp) override
    {
        size_t n = mp.decoded.payload.size;
        if (n == 0)
            return ProcessMessage::CONTINUE;

        char text[BLP_TEXT];
        if (n > BLP_TEXT - 1)
            n = BLP_TEXT - 1;
        memcpy(text, mp.decoded.payload.bytes, n);
        text[n] = '\0';

        char from[BLP_SHORT];
        shortNameFor(mp.from, from);
        uint8_t direct = (nodeDB && mp.to == nodeDB->getNodeNum()) ? 1 : 0;
        pushMsg(mp.from, direct ? mp.from : 0, from, mp.channel, direct, text);
        g_bleepieBridge.rxCount++;

        return ProcessMessage::CONTINUE; // let the normal text module run too
    }
};

// ---- Periodic publisher + send consumer (core0) ----
class BleepieBridgeThread : public concurrency::OSThread
{
  public:
    BleepieBridgeThread() : concurrency::OSThread("BleepieBridge") {}

  protected:
    int32_t runOnce() override
    {
        BleepieBridge &b = g_bleepieBridge;

        // --- status + our short name ---
        copyShort(b.myName, owner.short_name);
        if (nodeDB)
            b.nodeCount = (uint16_t)nodeDB->getNumMeshNodes();

        // --- node list ---
        uint8_t nn = 0;
        if (nodeDB) {
            size_t total = nodeDB->getNumMeshNodes();
            for (size_t i = 0; i < total && nn < BLP_MAX_NODES; i++) {
                meshtastic_NodeInfoLite *ni = nodeDB->getMeshNodeByIndex(i);
                if (!ni)
                    continue;
                b.nodes[nn].num = ni->num;
                if (ni->has_user && ni->user.short_name[0])
                    copyShort(b.nodes[nn].shortName, ni->user.short_name);
                else
                    snprintf(b.nodes[nn].shortName, BLP_SHORT, "!%02x", (unsigned)(ni->num & 0xFF));
                b.nodes[nn].snr = (int8_t)lroundf(ni->snr);
                nn++;
            }
        }
        b.numNodes = nn;

        // --- channel list ---
        uint8_t nc = 0;
        uint8_t total = channels.getNumChannels();
        for (uint8_t i = 0; i < total && nc < BLP_MAX_CHANS; i++) {
            const meshtastic_Channel &ch = channels.getByIndex(i);
            if (ch.role == meshtastic_Channel_Role_DISABLED)
                continue; // getName() names disabled slots too, so filter on role

            // Use the channel's own name if set; otherwise label the primary
            // "Primary" (matching the Meshtastic apps) rather than the preset name.
            const char *name;
            if (ch.settings.name[0])
                name = ch.settings.name;
            else if (ch.role == meshtastic_Channel_Role_PRIMARY)
                name = "Primary";
            else
                name = channels.getName(i);
            if (!name || !name[0])
                continue;

            b.chans[nc].index = i; // preserve real channel index for directed send
            strncpy(b.chans[nc].name, name, BLP_CHNAME - 1);
            b.chans[nc].name[BLP_CHNAME - 1] = '\0';
            nc++;
        }
        b.numChans = nc;

        // --- consume a badge send request ---
        if (b.sendPending) {
            if (router && service && b.sendText[0]) {
                meshtastic_MeshPacket *p = router->allocForSending();
                if (p) {
                    p->decoded.portnum = meshtastic_PortNum_TEXT_MESSAGE_APP;
                    p->want_ack = false;
                    if (b.sendIsNode) {
                        p->to = b.sendDest;
                    } else {
                        p->to = NODENUM_BROADCAST;
                        p->channel = (uint8_t)b.sendDest;
                    }
                    size_t len = strlen(b.sendText);
                    if (len > sizeof(p->decoded.payload.bytes))
                        len = sizeof(p->decoded.payload.bytes);
                    p->decoded.payload.size = len;
                    memcpy(p->decoded.payload.bytes, b.sendText, len);
                    service->sendToMesh(p, RX_SRC_LOCAL, true);
                    b.txCount++;
                    // reflect our own message into the chat history
                    if (b.sendIsNode)
                        pushMsg(0, b.sendDest, "me", 0, 1, b.sendText);
                    else
                        pushMsg(0, 0, "me", (uint8_t)b.sendDest, 0, b.sendText);
                }
            }
            b.sendPending = false;
        }

        b.gen++;
        return 1000; // re-run in 1 s
    }
};

static BleepieBridgeThread *bleepieBridgeThread = nullptr;
static BleepieTextTap *bleepieTextTap = nullptr;

// Called from setupModules() (core0) after the mesh stack is up.
void bleepieBridgeInit()
{
    if (!bleepieBridgeThread)
        bleepieBridgeThread = new BleepieBridgeThread();
    if (!bleepieTextTap)
        bleepieTextTap = new BleepieTextTap();
}

#endif // BLEEPIE_MESHTASTIC
