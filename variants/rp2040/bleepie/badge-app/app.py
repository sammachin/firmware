"""BleepieMeshtastic controller – Tildagon hexpansion UART app.
pin[0]=RX(HS_F<-GPIO28) pin[1]=TX(HS_G->GPIO29)

Minimal companion for the Meshtastic firmware running on the RP2040. Meshtastic
owns core0; a core1 bridge (bleepie_hexpansion.cpp) serves this app over the
emulated hexpansion EEPROM and answers a terse UART protocol:

  badge -> fw : "status\n"            request a status line
  badge -> fw : "send <text>\n"       queue a mesh text message
  fw -> badge : "MT <nodes> <short>\n" node count + our short name
  fw -> badge : "LASTMSG <text>\n"     most recent received text
"""

import app
import asyncio
from app_components import clear_background
from system.eventbus import eventbus
from events.input import Buttons, BUTTON_TYPES
from system.scheduler.events import RequestForegroundPushEvent
from machine import UART

_TX = 1
_RX = 0


class MeshtasticApp(app.App):
    def __init__(self, config=None):
        super().__init__()
        self.config = config
        self.buttons = Buttons(self)

        if config:
            try:
                from system.hexpansion.events import HexpansionAppLauncherAddEvent
                eventbus.emit(HexpansionAppLauncherAddEvent(config.port, "Meshtastic"))
            except Exception:
                pass

        self.uart = None
        self._buf = ""
        if config:
            try:
                tx_pin = config.pin[_TX]
                rx_pin = config.pin[_RX]
                tx_id = int(str(tx_pin).split("(")[1].split(")")[0].split(",")[0])
                rx_id = int(str(rx_pin).split("(")[1].split(")")[0].split(",")[0])
                for uid in (2, 1):
                    try:
                        self.uart = UART(uid, 115200, tx=tx_id, rx=rx_id)
                        break
                    except Exception:
                        self.uart = None
            except Exception:
                self.uart = None

        self.nodes = 0
        self.shortname = "----"
        self.lastmsg = ""

        eventbus.on(RequestForegroundPushEvent, self._on_fg, self)
        self.overlays = []

    def _on_fg(self, event):
        pass

    def _send(self, line):
        if self.uart:
            try:
                self.uart.write((line + "\n").encode())
            except Exception:
                pass

    async def background_task(self):
        while True:
            self._send("status")
            self._read()
            await asyncio.sleep(1.0)

    def _read(self):
        if not self.uart:
            return
        try:
            n = self.uart.any()
            if n:
                self._buf += self.uart.read(n).decode("utf-8", "ignore")
        except Exception:
            return
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            self._parse(line.strip())

    def _parse(self, line):
        parts = line.split()
        if not parts:
            return
        if parts[0] == "MT" and len(parts) >= 3:
            try:
                self.nodes = int(parts[1])
            except ValueError:
                pass
            self.shortname = parts[2]
        elif parts[0] == "LASTMSG":
            self.lastmsg = line[8:].strip()

    def update(self, delta):
        if self.buttons.get(BUTTON_TYPES["CANCEL"]):
            self.minimise()
        elif self.buttons.get(BUTTON_TYPES["CONFIRM"]):
            self._send("send hello from badge")
            self.buttons.clear()

    def draw(self, ctx):
        clear_background(ctx)
        ctx.save()
        ctx.text_align = ctx.CENTER
        ctx.font_size = 24
        ctx.rgb(0.2, 0.8, 0.9).move_to(0, -70).text("Meshtastic")
        ctx.font_size = 16
        ctx.rgb(1, 1, 1)
        ctx.move_to(0, -38).text("node %s" % self.shortname)
        ctx.move_to(0, -15).text("%d nodes" % self.nodes)
        ctx.font_size = 13
        msg = self.lastmsg if self.lastmsg else "(no messages)"
        if len(msg) > 22:
            msg = msg[:21] + "…"
        ctx.rgb(0.8, 0.8, 0.8).move_to(0, 10).text(msg)
        ctx.rgb(0.6, 0.6, 0.6)
        ctx.move_to(0, 45).text("CONFIRM: send hello")
        ctx.move_to(0, 62).text("CANCEL: exit")
        ctx.restore()


__app_export__ = MeshtasticApp
