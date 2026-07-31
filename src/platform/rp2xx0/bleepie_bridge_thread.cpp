// BleepieMeshtastic — core0 side of the badge bridge.
//
// A periodic OSThread (runs on core0 via mainController) that publishes mesh
// status into the shared BleepieBridge snapshot for core1's UART/hexpansion to
// serve to the Tildagon badge, and consumes the badge's outbound send requests
// by injecting a text message onto the mesh.
//
// Compiled only for the bleepie board. Registered with one guarded line in
// src/modules/Modules.cpp (bleepieBridgeInit()).

#ifdef BLEEPIE_MESHTASTIC

#include "concurrency/OSThread.h"
#include "mesh/MeshService.h"
#include "mesh/NodeDB.h"
#include "mesh/Router.h"
#include "mesh/SinglePortModule.h"
#include "bleepie_bridge.h"
#include <Arduino.h>
#include <cstring>

// Shared core0<->core1 snapshot (defined here so it exists even when the core1
// hexpansion file is compiled out).
struct BleepieBridge g_bleepieBridge = {0, "----", "", false, ""};

class BleepieBridgeThread : public concurrency::OSThread
{
  public:
    BleepieBridgeThread() : concurrency::OSThread("BleepieBridge") {}

  protected:
    int32_t runOnce() override
    {
        // --- publish status for the badge (read by core1) ---
        if (nodeDB)
            g_bleepieBridge.nodeCount = (uint16_t)nodeDB->getNumMeshNodes();

        // owner.short_name is char[5]; copy safely into our buffer.
        strncpy(g_bleepieBridge.shortName, owner.short_name, sizeof(g_bleepieBridge.shortName) - 1);
        g_bleepieBridge.shortName[sizeof(g_bleepieBridge.shortName) - 1] = '\0';

        // --- consume an outbound send queued by the badge (set on core1) ---
        if (g_bleepieBridge.sendPending) {
            const char *text = g_bleepieBridge.sendText;
            if (router && service && text[0]) {
                meshtastic_MeshPacket *p = router->allocForSending();
                if (p) {
                    p->to = NODENUM_BROADCAST;
                    p->decoded.portnum = meshtastic_PortNum_TEXT_MESSAGE_APP;
                    p->want_ack = false;
                    size_t len = strlen(text);
                    if (len > sizeof(p->decoded.payload.bytes))
                        len = sizeof(p->decoded.payload.bytes);
                    p->decoded.payload.size = len;
                    memcpy(p->decoded.payload.bytes, text, len);
                    service->sendToMesh(p, RX_SRC_LOCAL, true);
                }
            }
            g_bleepieBridge.sendPending = false;
        }

        return 1000; // re-run in 1 s
    }
};

// Taps incoming text messages into the shared snapshot so the badge can show
// the most recent one. Returns CONTINUE so the real TextMessageModule (phone
// notifications, etc.) still processes the packet normally.
class BleepieTextTap : public SinglePortModule
{
  public:
    BleepieTextTap() : SinglePortModule("BleepieTextTap", meshtastic_PortNum_TEXT_MESSAGE_APP) {}

  protected:
    virtual ProcessMessage handleReceived(const meshtastic_MeshPacket &mp) override
    {
        size_t n = mp.decoded.payload.size;
        if (n > 0) {
            if (n > sizeof(g_bleepieBridge.lastMsg) - 1)
                n = sizeof(g_bleepieBridge.lastMsg) - 1;
            memcpy(g_bleepieBridge.lastMsg, mp.decoded.payload.bytes, n);
            g_bleepieBridge.lastMsg[n] = '\0';
        }
        return ProcessMessage::CONTINUE;
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
