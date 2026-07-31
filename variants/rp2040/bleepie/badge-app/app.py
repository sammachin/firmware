"""BleepieMeshtastic controller – Tildagon hexpansion UART app.
pin[0]=RX(HS_F<-GPIO28) pin[1]=TX(HS_G->GPIO29)

Menu-driven companion for the Meshtastic firmware running on the RP2040 (core0);
a core1 bridge (bleepie_hexpansion.cpp / bleepie_bridge_thread.cpp) serves this
app over the emulated hexpansion EEPROM and answers a line protocol:

  status            -> ST <myShort> <nodeCount> <rx> <tx>
  nodes             -> ND <hex8> <short> <snr> ... NDE
  chans             -> CH <chIndex> <name> ... CHE
  msgs              -> MG <direct> <ch> <from> <text> ... MGE   (newest first)
  send c<idx> <txt> -> broadcast on a channel
  send n<hex8> <txt>-> direct message to a node

Menus: Messages / Nodes / Send Message / Status. Composing uses the keyboard via
TextDialog.
"""

import app
import asyncio
from app_components import clear_background, TextDialog
from system.eventbus import eventbus
from events.input import Buttons, BUTTON_TYPES, ButtonDownEvent
from system.scheduler.events import RequestForegroundPushEvent
from machine import UART

_TX = 1
_RX = 0
_MENU = ["Messages", "Nodes", "Send Message", "Status"]


class MeshtasticApp(app.App):
    def __init__(self, config=None):
        super().__init__()
        self.config = config
        self.buttons = Buttons(self)
        self._fg = False
        self._active = False

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

        # View state machine
        self.view = "menu"
        self.idx = 0
        self.dialog = None
        self.readmsg = None       # message dict being viewed
        self.send_dest = None     # {"kind":"c"/"n", "id":..., "label":...}
        self.toast = ""
        self.toast_t = 0

        # Live data from the firmware
        self.status = {"name": "----", "nodes": 0, "rx": 0, "tx": 0}
        self.nodes = []           # [{"num","short","snr"}]
        self.chans = []           # [{"idx","name"}]
        self.msgs = []            # [{"direct","ch","from","text"}] newest first
        self._t_nodes = []
        self._t_chans = []
        self._t_msgs = []

        eventbus.on(RequestForegroundPushEvent, self._on_fg, self)
        self.overlays = []

    def _on_fg(self, event):
        pass

    # ---- UART ----
    def _cmd(self, line):
        if self.uart:
            try:
                self.uart.write((line + "\n").encode())
            except Exception:
                pass

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
        if not line:
            return
        p = line.split(" ", 4)
        tag = p[0]
        if tag == "ST" and len(p) >= 5:
            self.status = {"name": p[1], "nodes": self._int(p[2]),
                           "rx": self._int(p[3]), "tx": self._int(p[4])}
        elif tag == "ND" and len(p) >= 4:
            self._t_nodes.append({"num": p[1], "short": p[2], "snr": self._int(p[3])})
        elif tag == "NDE":
            self.nodes = self._t_nodes
            self._t_nodes = []
        elif tag == "CH" and len(p) >= 3:
            self._t_chans.append({"idx": self._int(p[1]), "name": p[2]})
        elif tag == "CHE":
            self.chans = self._t_chans
            self._t_chans = []
        elif tag == "MG" and len(p) >= 4:
            self._t_msgs.append({"direct": self._int(p[1]), "ch": self._int(p[2]),
                                 "from": p[3], "text": p[4] if len(p) >= 5 else ""})
        elif tag == "MGE":
            self.msgs = self._t_msgs
            self._t_msgs = []
        elif tag == "OK":
            self._set_toast("Sent")
        elif tag == "ERR":
            self._set_toast("Send failed")

    @staticmethod
    def _int(s):
        try:
            return int(s)
        except Exception:
            return 0

    def _set_toast(self, t):
        self.toast = t
        self.toast_t = 2.0

    def _chan_name(self, idx):
        for c in self.chans:
            if c["idx"] == idx:
                return c["name"]
        return "ch%d" % idx

    async def background_task(self):
        while True:
            self._cmd("status")
            v = self.view
            if v in ("msgs", "read"):
                self._cmd("msgs")
                self._cmd("chans")
            elif v == "nodes":
                self._cmd("nodes")
            elif v == "send":
                self._cmd("chans")
                self._cmd("nodes")
            await asyncio.sleep(0.3)
            self._read()
            await asyncio.sleep(0.7)

    # ---- input ----
    def _on_btn(self, event):
        if self.dialog:
            return
        b = event.button
        if BUTTON_TYPES["CANCEL"] in b:
            self._back()
        elif BUTTON_TYPES["UP"] in b:
            self._nav(-1)
        elif BUTTON_TYPES["DOWN"] in b:
            self._nav(1)
        elif BUTTON_TYPES["CONFIRM"] in b:
            self._sel()

    def _list_len(self):
        v = self.view
        if v == "menu":
            return len(_MENU)
        if v == "msgs":
            return len(self.msgs)
        if v == "nodes":
            return len(self.nodes)
        if v == "send":
            return len(self.chans) + len(self.nodes)
        return 0

    def _nav(self, d):
        n = self._list_len()
        if n <= 0:
            return
        self.idx = max(0, min(self.idx + d, n - 1))

    def _back(self):
        v = self.view
        if v == "menu":
            eventbus.remove(ButtonDownEvent, self._on_btn, self)
            self._active = False
            self.minimise()
        elif v == "read":
            self.view = "msgs"
        else:
            self.view = "menu"
            self.idx = 0

    def _sel(self):
        v = self.view
        if v == "menu":
            self.view = ["msgs", "nodes", "send", "status"][self.idx]
            self.idx = 0
        elif v == "msgs":
            if 0 <= self.idx < len(self.msgs):
                self.readmsg = self.msgs[self.idx]
                self.view = "read"
        elif v == "nodes":
            if 0 <= self.idx < len(self.nodes):
                nd = self.nodes[self.idx]
                self.send_dest = {"kind": "n", "id": nd["num"], "label": "@" + nd["short"]}
                self._compose()
        elif v == "send":
            nc = len(self.chans)
            if self.idx < nc:
                c = self.chans[self.idx]
                self.send_dest = {"kind": "c", "id": c["idx"], "label": "#" + c["name"]}
            else:
                nd = self.nodes[self.idx - nc]
                self.send_dest = {"kind": "n", "id": nd["num"], "label": "@" + nd["short"]}
            self._compose()

    # ---- compose ----
    def _compose(self):
        self.dialog = TextDialog("To %s:" % self.send_dest["label"], self,
                                 on_complete=self._send_done,
                                 on_cancel=self._send_cancel)

    def _send_done(self):
        text = (self.dialog.text or "").strip()
        self.dialog._cleanup()
        self.dialog = None
        if text and self.send_dest:
            d = self.send_dest
            pfx = ("c%d" % d["id"]) if d["kind"] == "c" else ("n%s" % d["id"])
            self._cmd("send %s %s" % (pfx, text))
            self._set_toast("Sending...")
        self.view = "menu"
        self.idx = 0

    def _send_cancel(self):
        self.dialog._cleanup()
        self.dialog = None

    # ---- lifecycle ----
    def update(self, delta):
        if not self._fg:
            eventbus.emit(RequestForegroundPushEvent(self))
            self._fg = True
        if self.toast_t > 0:
            self.toast_t -= delta

    def draw(self, ctx):
        if not self._active:
            eventbus.on(ButtonDownEvent, self._on_btn, self)
            self._active = True

        ctx.save()
        clear_background(ctx)
        ctx.text_align = ctx.CENTER
        ctx.font_size = 20
        ctx.rgb(0.2, 0.8, 0.9).move_to(0, -88).text("Meshtastic")
        ctx.font_size = 11
        ctx.rgb(0.5, 0.5, 0.5).move_to(0, -70).text(
            "%s  %d nodes" % (self.status["name"], self.status["nodes"]))

        fn = {"menu": self._d_menu, "msgs": self._d_msgs, "read": self._d_read,
              "nodes": self._d_nodes, "send": self._d_send,
              "status": self._d_status}.get(self.view)
        if fn:
            fn(ctx)

        if not self.uart:
            ctx.font_size = 11
            ctx.rgb(1, 0, 0).move_to(0, 92).text("No UART")
        elif self.toast_t > 0 and self.toast:
            ctx.font_size = 12
            ctx.rgb(0, 1, 0.3).move_to(0, 92).text(self.toast[:32])

        if self.dialog:
            self.dialog.draw(ctx)
        ctx.restore()

    # ---- list helper ----
    def _draw_list(self, ctx, labels, empty="(empty)"):
        n = len(labels)
        if n == 0:
            ctx.font_size = 14
            ctx.rgb(0.5, 0.5, 0.5).move_to(0, 0).text(empty)
            return
        self.idx = min(self.idx, n - 1)
        start = max(0, self.idx - 2)
        ctx.font_size = 15
        ctx.text_align = ctx.LEFT
        y = -45
        for i in range(start, min(n, start + 6)):
            sel = (i == self.idx)
            ctx.rgb(1, 1, 0) if sel else ctx.rgb(0.65, 0.65, 0.65)
            ctx.move_to(-95, y).text((("> " if sel else "  ") + labels[i])[:22])
            y += 20
        ctx.text_align = ctx.CENTER

    # ---- views ----
    def _d_menu(self, ctx):
        self.idx = min(self.idx, len(_MENU) - 1)
        ctx.font_size = 18
        for i, label in enumerate(_MENU):
            y = -40 + i * 26
            if i == self.idx:
                ctx.rgb(1, 1, 0).move_to(0, y).text("> " + label)
            else:
                ctx.rgb(0.65, 0.65, 0.65).move_to(0, y).text(label)

    def _d_msgs(self, ctx):
        labels = []
        for m in self.msgs:
            tag = "DM" if m["direct"] else self._chan_name(m["ch"])
            labels.append("%s[%s] %s" % (m["from"], tag, m["text"]))
        self._draw_list(ctx, labels, "No messages")
        ctx.font_size = 10
        ctx.rgb(0.35, 0.35, 0.35).move_to(0, 78).text("[OK] read  [BACK] menu")

    def _d_read(self, ctx):
        m = self.readmsg or {}
        tag = "DM" if m.get("direct") else self._chan_name(m.get("ch", 0))
        ctx.font_size = 14
        ctx.rgb(0.2, 0.8, 1.0).move_to(0, -45).text("%s  [%s]" % (m.get("from", "?"), tag))
        ctx.font_size = 15
        ctx.rgb(1, 1, 1)
        # wrap the text across lines
        text = m.get("text", "")
        y = -18
        line = ""
        for word in text.split(" "):
            if len(line) + len(word) + 1 > 22:
                ctx.move_to(0, y).text(line)
                y += 20
                line = word
            else:
                line = (line + " " + word) if line else word
        if line:
            ctx.move_to(0, y).text(line)

    def _d_nodes(self, ctx):
        labels = ["%-5s %ddB" % (nd["short"], nd["snr"]) for nd in self.nodes]
        self._draw_list(ctx, labels, "No nodes")
        ctx.font_size = 10
        ctx.rgb(0.35, 0.35, 0.35).move_to(0, 78).text("[OK] message node")

    def _d_send(self, ctx):
        labels = ["#" + c["name"] for c in self.chans] + ["@" + nd["short"] for nd in self.nodes]
        self._draw_list(ctx, labels, "No destinations")
        ctx.font_size = 10
        ctx.rgb(0.35, 0.35, 0.35).move_to(0, 78).text("[OK] compose")

    def _d_status(self, ctx):
        s = self.status
        ctx.font_size = 16
        ctx.rgb(1, 1, 1)
        ctx.move_to(0, -30).text("node: %s" % s["name"])
        ctx.move_to(0, -6).text("nodes seen: %d" % s["nodes"])
        ctx.move_to(0, 18).text("rx %d   tx %d" % (s["rx"], s["tx"]))
        ctx.font_size = 11
        pc = self.chans[0]["name"] if self.chans else "?"
        ctx.rgb(0.5, 0.5, 0.5).move_to(0, 45).text("primary: %s" % pc)


__app_export__ = MeshtasticApp
