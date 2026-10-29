"""Pagina Grafici: tracce scorrevoli di acceleratore, freno, sterzo e marcia (TC/ABS colorano i tratti)."""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget,
)

from acc_tx_client import TelemetryModel
from pitwall_logic import AppSettings, ChunkedSeries, gear_name, steer_to_degrees
from pitwall_ui.common import FlagLabel, Metric


# colori dei grafici: (normale, con intervento attivo)
COL_THROTTLE = ("#2ecc71", "#f5a623")
COL_BRAKE = ("#e74c3c", "#3ad0ff")
COL_STEER = ("#aab4c2", "#aab4c2")
COL_GEAR = ("#4aa3ff", "#4aa3ff")



class TraceWidget(QWidget):
    """
    Grafico scorrevole: il campione piu' recente e' a destra.

    I dati stanno in una ChunkedSeries. Qui si disegna soltanto: ogni blocco ha un
    QPainterPath gia' pronto in coordinate DATI (tempo, valore) e una trasformazione del
    painter lo porta sullo schermo. Cosi' a ogni fotogramma non si ricalcola nessun punto:
    si ricostruisce solo il blocco in corso (~1 s) e il resto lo gestisce Qt.
    Il pennello e' "cosmetico": lo spessore resta 2 px anche se la trasformazione scala.
    """
    L, R, T, B = 42, 10, 8, 8              # margini: sinistra (etichette), destra, alto, basso

    def __init__(self, vmin: float, vmax: float, ticks: list, colors: tuple, fill: bool = False,
                 label_fn=None, value_fmt=None, hold: bool = False):
        super().__init__()
        self.vmin, self.vmax, self.ticks = vmin, vmax, list(ticks)
        self.colors = colors                       # (normale, flag attivo)
        self.fill = fill
        self.hold = hold                           # True: valore "a gradini" (marce)
        self.label_fn = label_fn or (lambda v: f"{v:.0f}")
        self.value_fmt = value_fmt or (lambda v: f"{v:.1f}")
        self.series = ChunkedSeries()
        self.hover: float | None = None            # posizione del cursore: 0..1 sull'asse orizzontale
        self.on_hover = None                       # la pagina lo usa per sincronizzare i grafici
        self._now = 0.0
        self._window = 20.0
        self._pens = [self._make_pen(c) for c in colors]
        self._tints = [self._make_tint(c) for c in colors]
        self.setMinimumHeight(70)
        self.setMouseTracking(True)

    @staticmethod
    def _make_pen(color: str) -> QPen:
        pen = QPen(QColor(color))
        pen.setWidthF(2.0)
        pen.setCosmetic(True)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        return pen

    @staticmethod
    def _make_tint(color: str) -> QBrush:
        c = QColor(color)
        c.setAlpha(60)
        return QBrush(c)

    @staticmethod
    def grid_step(window: float) -> float:
        """Distanza tra le linee verticali: piu' fitta quando la finestra e' corta."""
        return 0.5 if window <= 5 else 1.0 if window <= 12 else 5.0 if window <= 35 else 10.0

    def set_range(self, vmin: float, vmax: float, ticks: list) -> None:
        self.vmin, self.vmax, self.ticks = vmin, vmax, list(ticks)

    def set_view(self, now: float, window: float) -> None:
        self._now, self._window = now, max(0.5, window)
        self.update()

    def set_hover(self, frac: float | None) -> None:
        self.hover = frac
        self.update()

    # ---- mouse: cursore con lettura dei valori ----
    def mouseMoveEvent(self, event) -> None:
        pw = self.width() - self.L - self.R
        frac = (event.position().x() - self.L) / pw if pw > 0 else -1.0
        self._hover_changed(frac if 0.0 <= frac <= 1.0 else None)
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover_changed(None)
        super().leaveEvent(event)

    def _hover_changed(self, frac) -> None:
        if self.on_hover:
            self.on_hover(frac)
        else:
            self.set_hover(frac)

    # ---- disegno ----
    def _build(self, ch, t0: float) -> None:
        """Costruisce (o ricostruisce, se e' il blocco in corso) il path di un blocco."""
        pts = ch.pts
        path = QPainterPath()
        path.moveTo(QPointF(pts[0][0] - t0, pts[0][1]))
        for t, v in pts[1:]:
            path.lineTo(QPointF(t - t0, v))
        if self.fill:
            area = QPainterPath(path)
            area.lineTo(QPointF(pts[-1][0] - t0, self.vmin))
            area.lineTo(QPointF(pts[0][0] - t0, self.vmin))
            area.closeSubpath()
            ch.fill = area
        ch.path = path
        ch.dirty = False

    def paintEvent(self, event) -> None:
        w, h = self.width(), self.height()
        pw, ph = w - self.L - self.R, h - self.T - self.B
        if pw <= 10 or ph <= 10:
            return
        now, window = self._now, self._window
        span = (self.vmax - self.vmin) or 1.0
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(QRectF(0.0, 0.0, float(w), float(h)), QBrush(QColor("#0f1115")))

        # griglia verticale (scorre con il tempo) e orizzontale con etichette
        grid = QPen(QColor("#252c36"))
        grid.setWidthF(1.0)
        p.setPen(grid)
        step = self.grid_step(window)
        k = math.floor(now / step) * step
        while True:
            x = self.L + pw * (1.0 - (now - k) / window)
            if x < self.L:
                break
            p.drawLine(QPointF(x, float(self.T)), QPointF(x, float(self.T + ph)))
            k -= step
        for v in self.ticks:
            y = self.T + ph * (1.0 - (v - self.vmin) / span)
            p.setPen(grid)
            p.drawLine(QPointF(float(self.L), y), QPointF(float(self.L + pw), y))
            p.setPen(QColor("#6f7a89"))
            p.drawText(QPointF(4.0, y + 4.0), self.label_fn(v))

        # dati: coordinate (tempo, valore) portate sullo schermo dalla trasformazione
        t0 = self.series.t0
        chunks = self.series.visible(now - window) if t0 is not None else []
        if chunks:
            a, sy = pw / window, ph / span
            p.save()
            p.setClipRect(QRectF(float(self.L), float(self.T), float(pw), float(ph)))
            p.translate(self.L + pw - a * (now - t0), self.T + ph + sy * self.vmin)
            p.scale(a, -sy)
            p.setBrush(Qt.BrushStyle.NoBrush)
            for ch in chunks:
                if ch.dirty:
                    self._build(ch, t0)
                f = 1 if ch.flag else 0
                if self.fill:
                    p.fillPath(ch.fill, self._tints[f])
                p.setPen(self._pens[f])
                p.drawPath(ch.path)
            p.restore()

        # cursore con il valore letto in quel punto
        if self.hover is not None:
            x = self.L + pw * self.hover
            cur = QPen(QColor("#e6e6e6"))
            cur.setWidthF(1.0)
            p.setPen(cur)
            p.drawLine(QPointF(x, float(self.T)), QPointF(x, float(self.T + ph)))
            val = self.series.value_at(now - window * (1.0 - self.hover), self.hold)
            if val is not None:
                tx = x + 6.0 if x < self.L + pw - 70 else x - 66.0
                p.drawText(QPointF(tx, float(self.T + 14)), self.value_fmt(val))
        p.end()


class GraphPanel(QFrame):
    """Una riga: a sinistra valore attuale e indicatore (TC/ABS), a destra il grafico."""

    def __init__(self, title: str, chart: TraceWidget, flag_text: str | None = None,
                 flag_bg: str | None = None):
        super().__init__()
        self.setObjectName("card")
        self.chart = chart
        self._flag_text, self._flag_bg = flag_text, flag_bg
        self.live = Metric(title, big=True)          # NON chiamarlo 'metric': e' un metodo di QFrame
        self.live.setFixedWidth(150)
        self.badge = FlagLabel()
        left = QVBoxLayout()
        left.addWidget(self.live)
        left.addWidget(self.badge)
        left.addStretch(1)
        h = QHBoxLayout(self)
        h.setContentsMargins(12, 8, 12, 8)
        h.setSpacing(12)
        h.addLayout(left)
        h.addWidget(chart, 1)

    def set_live(self, text: str, flag_on: bool) -> None:
        self.live.set(text, "neutral")
        if flag_on and self._flag_text:
            self.badge.set_flag(self._flag_text, self._flag_bg, "#000000")
        else:
            self.badge.set_flag("", None, None)


class GraphPage(QWidget):
    """Seconda schermata: acceleratore, freno, sterzo e marcia che scorrono nel tempo."""
    WINDOWS = [3, 5, 10, 20, 30, 60]       # secondi mostrati
    KEEP_S = 65.0                          # secondi conservati nelle serie (>= finestra massima)

    def __init__(self, on_window_changed):
        super().__init__()
        self._on_window = on_window_changed
        self._model = None
        self._last_t: float | None = None          # ultimo campione gia' inserito nelle serie
        self._last_gear: int | None = None
        self._last_vals = None

        self.window_box = QComboBox()
        self.window_box.addItems([f"{w} s" for w in self.WINDOWS])
        self.window_box.setCurrentIndex(3)
        self.window_box.currentIndexChanged.connect(lambda i: self._changed(i))
        self.pause_box = QCheckBox("Pausa grafici")
        legend = QLabel(
            f"<span style='color:{COL_THROTTLE[0]}'>■</span> acceleratore &nbsp; "
            f"<span style='color:{COL_THROTTLE[1]}'>■</span> TC attivo &nbsp;&nbsp; "
            f"<span style='color:{COL_BRAKE[0]}'>■</span> freno &nbsp; "
            f"<span style='color:{COL_BRAKE[1]}'>■</span> ABS attivo")
        hint = QLabel("passa il mouse sui grafici per leggere i valori")
        hint.setObjectName("hint")
        top = QHBoxLayout()
        top.addWidget(legend)
        top.addSpacing(16)
        top.addWidget(hint)
        top.addStretch(1)
        top.addWidget(QLabel("Finestra"))
        top.addWidget(self.window_box)
        top.addWidget(self.pause_box)

        pedals = [0, 50, 100]
        self.p_thr = GraphPanel("ACCELERATORE", TraceWidget(
            0, 100, pedals, COL_THROTTLE, fill=True, value_fmt=lambda v: f"{v:.0f} %"), "TC", COL_THROTTLE[1])
        self.p_brk = GraphPanel("FRENO", TraceWidget(
            0, 100, pedals, COL_BRAKE, fill=True, value_fmt=lambda v: f"{v:.0f} %"), "ABS", COL_BRAKE[1])
        self.p_str = GraphPanel("STERZO", TraceWidget(
            -270, 270, [-270, 0, 270], COL_STEER, value_fmt=lambda v: f"{v:+.0f}°"))
        self.p_gear = GraphPanel("MARCIA", TraceWidget(
            -1.5, 6.5, list(range(-1, 7)), COL_GEAR, hold=True,
            label_fn=lambda v: gear_name(int(round(v))), value_fmt=lambda v: gear_name(int(round(v)))))
        self.panels = [self.p_thr, self.p_brk, self.p_str, self.p_gear]
        self.charts = [p.chart for p in self.panels]
        for chart in self.charts:
            chart.on_hover = self._set_hover               # il cursore si muove su tutti insieme

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 6, 0, 0)
        lay.setSpacing(8)
        lay.addLayout(top)
        for panel in self.panels:
            lay.addWidget(panel, 1)

    def _changed(self, index: int) -> None:
        self._on_window(self.WINDOWS[index])

    def _set_hover(self, frac) -> None:
        for chart in self.charts:
            chart.set_hover(frac)

    def set_window(self, seconds: int) -> None:
        best = min(range(len(self.WINDOWS)), key=lambda i: abs(self.WINDOWS[i] - seconds))
        self.window_box.setCurrentIndex(best)

    def paused(self) -> bool:
        return self.pause_box.isChecked()

    def reset(self) -> None:
        for chart in self.charts:
            chart.series.clear()
        self._last_t = None
        self._last_gear = None
        self._last_vals = None

    def on_settings_changed(self) -> None:
        """Le serie contengono valori gia' convertiti (gradi sterzo): si rifanno dallo storico."""
        self._model = None

    def refresh(self, model: TelemetryModel, cfg: AppSettings) -> None:
        if model is not self._model:               # nuova connessione o impostazioni cambiate
            self._model = model
            self.reset()
        # solo i campioni arrivati dall'ultima volta (la prima volta, tutto lo storico)
        samples = (model.history(self.KEEP_S) if self._last_t is None
                   else model.history_since(self._last_t))
        m = cfg.steer_max_deg
        self.p_str.chart.set_range(-m, m, [-m, 0, m])
        thr, brk, steer, gear = (c.series for c in self.charts)
        for t, th, br, st, tc, ab, g in samples:   # campione = (t, gas, freno, sterzo, tc, abs, marcia)
            thr.add(t, min(max(th, 0.0), 1.0) * 100.0, 1 if tc else 0)
            brk.add(t, min(max(br, 0.0), 1.0) * 100.0, 1 if ab else 0)
            steer.add(t, steer_to_degrees(st, cfg.steer_unit, m, cfg.steer_invert))
            if self._last_gear is not None and g != self._last_gear:
                gear.add(t, self._last_gear)       # gradino: prima la marcia vecchia, poi la nuova
            gear.add(t, g)                         # allo stesso istante
            self._last_gear = g
        if samples:
            self._last_t = samples[-1][0]
            self._last_vals = samples[-1]

        now, window = time.monotonic(), float(cfg.graph_seconds)
        for chart in self.charts:
            chart.set_view(now, window)
        if self._last_vals is not None:
            _, th, br, st, tc, ab, g = self._last_vals
            self.p_thr.set_live(f"{min(max(th, 0.0), 1.0) * 100:.0f} %", bool(tc))
            self.p_brk.set_live(f"{min(max(br, 0.0), 1.0) * 100:.0f} %", bool(ab))
            self.p_str.set_live(f"{steer_to_degrees(st, cfg.steer_unit, m, cfg.steer_invert):+.0f}°", False)
            self.p_gear.set_live(gear_name(g), False)
