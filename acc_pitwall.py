"""
ACC Pit Wall - interfaccia desktop (PySide6) per ACC-TX-UDP.

Installazione:   pip install PySide6
Avvio:           python acc_pitwall.py
(i tre file acc_tx_client.py, pitwall_logic.py, acc_pitwall.py vanno nella stessa cartella)

Threading:
  - thread principale : GUI + QTimer che legge uno snapshot del modello (default 20 Hz)
  - thread "telemetry-rx" (TelemetryClient) : START/ALIVE/STOP, ricezione, parsing
  Nessun thread secondario tocca i widget.

Impostazioni salvate in  %APPDATA%\\ACC-PitWall\\settings.json
"""
from __future__ import annotations

import math
import socket
import sys
import time
from dataclasses import replace

from PySide6.QtCore import QByteArray, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (
    QAction, QBrush, QColor, QKeySequence, QPainter, QPainterPath, QPen,
)
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFormLayout, QFrame, QGraphicsOpacityEffect, QGridLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QProgressBar,
    QPushButton, QSpinBox, QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget,
)

from acc_tx_client import (
    ACCAdapter, CarState, FieldStats, TelemetryClient, TelemetryModel,
)
from pitwall_logic import (
    FLAG_NAMES, LEVEL_COLORS, SESSION_NAMES, STATUS_NAMES, AppSettings, FuelTracker,
    classify_life, classify_window, fmt_clock_ms, fmt_lap, is_live, load_settings,
    save_settings, session_name, status_name, steer_out_of_range, steer_to_degrees,
    thin_samples, gear_name, gear_steps,
)

APP_NAME = "ACC Pit Wall"

# Simulatori supportati: nome -> adapter. Per aggiungerne uno basta un nuovo adapter
# che produca CarState (vedi ACCAdapter in acc_tx_client.py).
SIMS = {"ACC": ACCAdapter}

# sopra questo regime il motore e' acceso anche se il flag isEngineRunning del server e' a 0
ENGINE_ON_RPM = 400

# colori dei grafici: (normale, con intervento attivo)
COL_THROTTLE = ("#2ecc71", "#f5a623")     # verde -> arancio quando interviene il TC
COL_BRAKE = ("#e74c3c", "#3ad0ff")        # rosso -> azzurro quando interviene l'ABS
COL_STEER = ("#aab4c2", "#aab4c2")
COL_GEAR = ("#4aa3ff", "#4aa3ff")

WHEEL_TITLES = ["ANTERIORE SX", "ANTERIORE DX", "POSTERIORE SX", "POSTERIORE DX"]

QSS = """
QMainWindow, QDialog, QWidget { background: #14171c; color: #e6e6e6;
    font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif; font-size: 13px; }
QLabel { background: transparent; }
QFrame#card { background: #1d2229; border: 1px solid #2c333d; border-radius: 8px; }
QFrame#sep { background: #2c333d; border: none; }
QLabel#caption { color: #8b95a3; font-size: 10px; font-weight: 600; }
QLabel#value { font-size: 19px; font-weight: 600; }
QLabel#valueBig { font-size: 32px; font-weight: 700; }
QLabel#title { color: #aab4c2; font-size: 12px; font-weight: 700; }
QLabel#gear { font-size: 104px; font-weight: 800; }
QLabel#flag { font-size: 14px; font-weight: 700; padding: 4px 10px; border-radius: 4px; }
QLabel#hint { color: #8b95a3; }
QMenuBar { background: #0f1115; color: #cfd6df; }
QMenuBar::item { background: transparent; padding: 5px 10px; }
QMenuBar::item:selected { background: #2a313b; }
QMenu { background: #1d2229; color: #e6e6e6; border: 1px solid #2c333d; }
QMenu::item { padding: 5px 28px 5px 24px; }
QMenu::item:selected { background: #2f6fdb; }
QMenu::separator { height: 1px; background: #2c333d; margin: 4px 0; }
QStatusBar { background: #0f1115; color: #8b95a3; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox { background: #0f1115;
    border: 1px solid #2c333d; border-radius: 4px; padding: 3px 6px; }
QGroupBox { border: 1px solid #2c333d; border-radius: 6px; margin-top: 12px; padding-top: 6px; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #8b95a3; }
QPushButton { background: #2a313b; border: 1px solid #3a4350; border-radius: 4px; padding: 5px 16px; }
QPushButton:hover { background: #343c48; }
QTabWidget::pane { border: 1px solid #2c333d; }
QTabBar::tab { background: #1d2229; padding: 7px 16px; }
QTabBar::tab:selected { background: #2a313b; }
QProgressBar { background: #0f1115; border: 1px solid #2c333d; border-radius: 4px; height: 14px; }
QProgressBar::chunk { background: #2ecc71; border-radius: 3px; }
QProgressBar#brk::chunk { background: #e74c3c; }
"""


# ==========================================================================
# Widget di base
# ==========================================================================
class Metric(QWidget):
    """Didascalia piccola + valore colorato per livello. Ridisegna solo se cambia."""

    def __init__(self, caption: str, big: bool = False):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.cap = QLabel(caption)
        self.cap.setObjectName("caption")
        self.val = QLabel("--")
        self.val.setObjectName("valueBig" if big else "value")
        lay.addWidget(self.cap)
        lay.addWidget(self.val)
        self._last: tuple | None = None

    def set(self, text: str, level: str = "na") -> None:
        key = (text, level)
        if key == self._last:
            return
        self._last = key
        self.val.setText(text)
        self.val.setStyleSheet(f"color: {LEVEL_COLORS.get(level, LEVEL_COLORS['na'])};")

    def set_caption(self, text: str) -> None:
        self.cap.setText(text)


class FlagLabel(QLabel):
    def __init__(self):
        super().__init__("")
        self.setObjectName("flag")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumWidth(90)
        self._last: tuple | None = None

    def set_flag(self, text: str, bg: str | None, fg: str | None) -> None:
        key = (text, bg, fg)
        if key == self._last:
            return
        self._last = key
        self.setText(text)
        self.setStyleSheet(f"background: {bg}; color: {fg};" if bg else "background: transparent;")


def hline() -> QFrame:
    f = QFrame()
    f.setObjectName("sep")
    f.setFixedHeight(1)
    return f


def _fmt_or_dash(v: float, fmt: str) -> str:
    return "--" if v == 0 else fmt.format(v)


# ==========================================================================
# Pannelli
# ==========================================================================
class TyreCard(QFrame):
    """Una ruota: gomma (pressione, core, I/C/E, usura) + freno (pastiglie, disco)."""

    def __init__(self, title: str):
        super().__init__()
        self.setObjectName("card")
        g = QGridLayout(self)
        g.setContentsMargins(14, 10, 14, 12)
        g.setHorizontalSpacing(14)
        g.setVerticalSpacing(8)

        t = QLabel(title)
        t.setObjectName("title")
        self.pressure = Metric("PRESSIONE  PSI", big=True)
        self.core = Metric("CORE  °C", big=True)
        self.surf = Metric("SUPERFICIE  °C")
        self.t_in = Metric("INTERNA")
        self.t_mid = Metric("CENTRO")
        self.t_out = Metric("ESTERNA")
        self.wear = Metric("USURA GOMMA")
        self.pad = Metric("PASTIGLIE  mm")
        self.disc = Metric("DISCO  mm")

        g.addWidget(t, 0, 0, 1, 2)
        g.addWidget(self.surf, 0, 2)
        g.addWidget(self.pressure, 1, 0, 1, 2)
        g.addWidget(self.core, 1, 2)
        g.addWidget(self.t_in, 2, 0)
        g.addWidget(self.t_mid, 2, 1)
        g.addWidget(self.t_out, 2, 2)
        g.addWidget(hline(), 3, 0, 1, 3)
        g.addWidget(self.wear, 4, 0)
        g.addWidget(self.pad, 4, 1)
        g.addWidget(self.disc, 4, 2)

    def refresh_from(self, s: CarState, i: int, cfg: AppSettings, wear_available: bool) -> None:
        p = s.tyre_pressure[i]
        self.pressure.set(f"{p:.1f}", classify_window(p, cfg.p_lo, cfg.p_hi, cfg.p_margin))
        c = s.tyre_core_temp[i]
        self.core.set(f"{c:.0f}", classify_window(c, cfg.core_lo, cfg.core_hi, cfg.core_margin))
        sv = s.tyre_temp_surface[i]
        self.surf.set("n/d" if sv == 0 else f"{sv:.0f}",
                      "na" if sv == 0 else classify_window(sv, cfg.surf_lo, cfg.surf_hi, cfg.surf_margin))
        for metric, arr in ((self.t_in, s.tyre_temp_inner),
                            (self.t_mid, s.tyre_temp_middle),
                            (self.t_out, s.tyre_temp_outer)):
            v = arr[i]
            if v == 0:                       # il sim non fornisce il dato
                metric.set("n/d", "na")
            else:
                metric.set(f"{v:.0f}", classify_window(v, cfg.surf_lo, cfg.surf_hi, cfg.surf_margin))
        self.wear.set(f"{s.tyre_wear[i]:.1f}" if wear_available else "n/d", "na")
        self.pad.set(_fmt_or_dash(s.pad_life[i], "{:.1f}"),
                     classify_life(s.pad_life[i], cfg.pad_warn, cfg.pad_crit))
        self.disc.set(_fmt_or_dash(s.disc_life[i], "{:.1f}"),
                      classify_life(s.disc_life[i], cfg.disc_warn, cfg.disc_crit))


class HeaderPanel(QFrame):
    """Barra in alto: sessione, bandiera, posizione, tempi, carburante."""

    def __init__(self):
        super().__init__()
        self.setObjectName("card")
        h = QHBoxLayout(self)
        h.setContentsMargins(14, 8, 14, 8)
        h.setSpacing(16)
        self.state = Metric("STATO")
        self.session = Metric("SESSIONE")
        self.flag = FlagLabel()
        self.position = Metric("POSIZIONE")
        self.laps = Metric("GIRI")
        self.cur = Metric("ATTUALE")
        self.last = Metric("ULTIMO")
        self.best = Metric("MIGLIORE")
        self.left = Metric("RIMASTO")
        self.fuel = Metric("FUEL  L")
        self.avg = Metric("L / GIRO")
        self.fuel_laps = Metric("GIRI FUEL")
        for w in (self.state, self.session, self.flag, self.position, self.laps, self.cur,
                  self.last, self.best, self.left, self.fuel, self.avg, self.fuel_laps):
            h.addWidget(w)
        h.addStretch(1)

    def show_status(self, text: str, level: str) -> None:
        self.state.set(text, level)
        self.session.set("--", "na")

    def refresh_from(self, s: CarState, connected: bool, fuel: FuelTracker, cfg: AppSettings) -> None:
        if connected:
            if s.status == 0 and is_live(s.status, s.rpm):
                self.state.set("LIVE*", "warn")       # * = dedotto dai giri: status non valorizzato
            else:
                self.state.set(status_name(s.status), "ok" if s.status == 2 else "warn")
            self.session.set(session_name(s.session), "neutral")
        else:
            self.state.set("NO SIGNAL", "crit")
            self.session.set("--", "na")
        name, bg, fg = FLAG_NAMES.get(s.flag, ("", None, None))
        self.flag.set_flag(name, bg, fg)
        self.position.set(f"P{s.position}" if s.position > 0 else "--")
        self.laps.set(str(s.laps_completed))
        self.cur.set(fmt_lap(s.time_current, s.ms_current))
        self.last.set(fmt_lap(s.time_last, s.ms_last))
        self.best.set(fmt_lap(s.time_best, s.ms_best), "ok")
        self.left.set(fmt_clock_ms(s.session_time_left))

        avg = fuel.avg_per_lap
        left = fuel.laps_left(s.fuel)
        lvl = classify_life(left, cfg.fuel_laps_warn, cfg.fuel_laps_crit) if left is not None else "na"
        self.fuel.set(f"{s.fuel:.1f}", lvl)
        self.avg.set(f"{avg:.2f}" if avg else "--")
        self.fuel_laps.set(f"{left:.1f}" if left is not None else "--", lvl)


class SteeringWheel(QWidget):
    """Volante disegnato che ruota. Positivo = destra (orario)."""

    def __init__(self):
        super().__init__()
        self._angle = 0.0
        self.setMinimumSize(90, 90)

    def set_angle(self, deg: float) -> None:
        if abs(deg - self._angle) < 0.3:       # niente ridisegni inutili
            return
        self._angle = deg
        self.update()

    def paintEvent(self, event) -> None:
        w, h = self.width(), self.height()
        r = max(10.0, min(w, h) / 2.0 - 8.0)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.translate(w / 2.0, h / 2.0)
        p.rotate(self._angle)

        rim = QPen(QColor("#aab4c2"))
        rim.setWidthF(max(5.0, r * 0.14))
        p.setPen(rim)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(0.0, 0.0), r, r)

        spoke = QPen(QColor("#6f7a89"))        # razze: sinistra, destra, basso
        spoke.setWidthF(max(4.0, r * 0.11))
        p.setPen(spoke)
        p.drawLine(QPointF(-r, 0.0), QPointF(r, 0.0))
        p.drawLine(QPointF(0.0, 0.0), QPointF(0.0, r))
        p.setBrush(QColor("#6f7a89"))
        p.drawEllipse(QPointF(0.0, 0.0), r * 0.17, r * 0.17)

        mark = QPen(QColor("#e74c3c"))         # marcatore alto: si vede la rotazione
        mark.setWidthF(max(5.0, r * 0.14))
        mark.setCapStyle(Qt.PenCapStyle.FlatCap)
        p.setPen(mark)
        p.drawLine(QPointF(0.0, -r * 1.05), QPointF(0.0, -r * 0.72))
        p.end()


class CarPanel(QFrame):
    """Colonna a destra: marcia, velocita', pedali, assetto elettronico."""

    def __init__(self):
        super().__init__()
        self.setObjectName("card")
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 10, 14, 12)
        v.setSpacing(8)
        cap = QLabel("MARCIA")
        cap.setObjectName("caption")
        self.gear = QLabel("N")
        self.gear.setObjectName("gear")
        self.gear.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.speed = Metric("VELOCITA'  km/h", big=True)
        self.rpm = Metric("GIRI MOTORE")

        self.thr = QProgressBar()
        self.thr.setRange(0, 100)
        self.thr.setTextVisible(False)
        self.brk = QProgressBar()
        self.brk.setObjectName("brk")
        self.brk.setRange(0, 100)
        self.brk.setTextVisible(False)
        cap_t, cap_b = QLabel("ACCELERATORE"), QLabel("FRENO")
        cap_t.setObjectName("caption")
        cap_b.setObjectName("caption")

        self.bias = Metric("BRAKE BIAS")
        self.tc = Metric("TC")
        self.abs = Metric("ABS")
        self.water = Metric("ACQUA  °C")
        self.engine = Metric("MOTORE")

        v.addWidget(cap)
        v.addWidget(self.gear)
        v.addWidget(self.speed)
        v.addWidget(self.rpm)
        v.addWidget(hline())
        v.addWidget(cap_t)
        v.addWidget(self.thr)
        v.addWidget(cap_b)
        v.addWidget(self.brk)
        v.addWidget(hline())
        row1, row2 = QHBoxLayout(), QHBoxLayout()
        row1.addWidget(self.bias)
        row1.addWidget(self.water)
        row2.addWidget(self.tc)
        row2.addWidget(self.abs)
        row2.addWidget(self.engine)
        v.addLayout(row1)
        v.addLayout(row2)
        v.addWidget(hline())
        self.steer = SteeringWheel()
        self.steer_val = Metric("STERZO")
        self.steer_raw = Metric("VALORE GREZZO")
        steer_col = QVBoxLayout()
        steer_col.addWidget(self.steer_val)
        steer_col.addWidget(self.steer_raw)
        steer_col.addStretch(1)
        row3 = QHBoxLayout()
        row3.addWidget(self.steer, 1)
        row3.addLayout(steer_col)
        v.addLayout(row3, 1)
        self._gear_last: str | None = None

    def refresh_from(self, s: CarState, cfg: AppSettings) -> None:
        g = s.gear_label
        if g != self._gear_last:
            self._gear_last = g
            self.gear.setText(g)
        self.speed.set(f"{s.speed_kmh:.0f}")
        self.rpm.set(f"{s.rpm}")
        self.thr.setValue(int(max(0.0, min(1.0, s.throttle)) * 100))
        self.brk.setValue(int(max(0.0, min(1.0, s.brake)) * 100))
        # euristica: se il bias e' una frazione (0..1) lo mostro in percentuale
        b = s.brake_bias * 100 if 0 < s.brake_bias <= 1.0 else s.brake_bias
        self.bias.set(f"{b:.1f} %" if b else "--")
        self.water.set(_fmt_or_dash(s.water_temp, "{:.0f}"))
        self.tc.set("ATTIVO" if s.tc_active else "-", "warn" if s.tc_active else "na")
        self.abs.set("ATTIVO" if s.abs_active else "-", "warn" if s.abs_active else "na")
        # il flag isEngineRunning non e' affidabile (a volte non e' valorizzato dal server):
        # se i giri sono sopra il regime di avviamento il motore gira comunque
        if s.engine_running or s.rpm >= ENGINE_ON_RPM:
            self.engine.set("ON", "ok")
        else:
            self.engine.set("OFF", "crit")
        deg = steer_to_degrees(s.steer_angle, cfg.steer_unit, cfg.steer_max_deg, cfg.steer_invert)
        self.steer.set_angle(deg)
        bad = steer_out_of_range(s.steer_angle, cfg.steer_unit)
        self.steer_val.set_caption("STERZO (FUORI SCALA)" if bad else "STERZO")
        self.steer_val.set(f"{deg:+.0f}°" if abs(deg) >= 0.5 else "0°", "warn" if bad else "neutral")
        self.steer_raw.set(f"{s.steer_angle:.3f}", "warn" if bad else "neutral")


# ==========================================================================
# Pagina grafici
# ==========================================================================
class TraceWidget(QWidget):
    """
    Grafico scorrevole: il campione piu' recente e' a destra. Ogni campione e'
    (tempo, valore, flag): i tratti con flag attivo sono disegnati con il secondo colore.
    """
    L, R, T, B = 42, 10, 8, 8              # margini: sinistra (etichette), destra, alto, basso

    def __init__(self, vmin: float, vmax: float, ticks: list, colors: tuple, fill: bool = False,
                 label_fn=None):
        super().__init__()
        self.label_fn = label_fn or (lambda v: f"{v:.0f}")
        self.vmin, self.vmax, self.ticks = vmin, vmax, list(ticks)
        self.colors = colors
        self.fill = fill
        self._samples: list = []
        self._now = 0.0
        self._window = 20.0
        self.setMinimumHeight(70)

    def set_range(self, vmin: float, vmax: float, ticks: list) -> None:
        self.vmin, self.vmax, self.ticks = vmin, vmax, list(ticks)

    def set_data(self, samples: list, now: float, window: float) -> None:
        self._samples, self._now, self._window = samples, now, max(1.0, window)
        self.update()

    def _y(self, v: float, ph: float) -> float:
        span = (self.vmax - self.vmin) or 1.0
        v = min(max(v, self.vmin), self.vmax)
        return self.T + ph * (1.0 - (v - self.vmin) / span)

    def build_runs(self, pw: float, ph: float) -> list:
        """[(flag, [(x, y), ...]), ...]: tratti consecutivi con lo stesso flag."""
        pts = thin_samples(self._samples, max(2, int(pw * 2)))
        runs: list = []
        prev = None
        for t, v, f in pts:
            x = self.L + pw * (1.0 - (self._now - t) / self._window)
            if x < self.L - 1:
                continue                                  # uscito a sinistra
            pt = (x, self._y(v, ph))
            if not runs or runs[-1][0] != f:
                runs.append((f, [prev] if prev is not None else []))   # raccordo col tratto prima
            runs[-1][1].append(pt)
            prev = pt
        return runs

    def paintEvent(self, event) -> None:
        w, h = self.width(), self.height()
        pw, ph = w - self.L - self.R, h - self.T - self.B
        if pw <= 10 or ph <= 10:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(QRectF(0.0, 0.0, float(w), float(h)), QBrush(QColor("#0f1115")))

        grid = QPen(QColor("#252c36"))
        grid.setWidthF(1.0)
        # linee verticali ogni 5 s: scorrono con il tempo
        k = math.floor(self._now / 5.0) * 5.0
        while True:
            x = self.L + pw * (1.0 - (self._now - k) / self._window)
            if x < self.L:
                break
            p.setPen(grid)
            p.drawLine(QPointF(x, float(self.T)), QPointF(x, float(self.T + ph)))
            k -= 5.0
        # linee orizzontali con etichette
        for v in self.ticks:
            y = self._y(v, ph)
            p.setPen(grid)
            p.drawLine(QPointF(float(self.L), y), QPointF(float(self.L + pw), y))
            p.setPen(QColor("#6f7a89"))
            p.drawText(QPointF(4.0, y + 4.0), self.label_fn(v))

        for flag, pts in self.build_runs(pw, ph):
            if len(pts) < 2:
                continue
            color = QColor(self.colors[1] if flag else self.colors[0])
            path = QPainterPath()
            path.moveTo(QPointF(pts[0][0], pts[0][1]))
            for x, y in pts[1:]:
                path.lineTo(QPointF(x, y))
            if self.fill:
                base = self._y(self.vmin, ph)
                area = QPainterPath(path)
                area.lineTo(QPointF(pts[-1][0], base))
                area.lineTo(QPointF(pts[0][0], base))
                area.closeSubpath()
                tint = QColor(color)
                tint.setAlpha(60)
                p.fillPath(area, QBrush(tint))
            pen = QPen(color)
            pen.setWidthF(2.0)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)
        p.end()


class GraphPanel(QFrame):
    """Una riga: a sinistra valore attuale e indicatore (TC/ABS), a destra il grafico."""

    def __init__(self, title: str, chart: TraceWidget, flag_text: str | None = None,
                 flag_bg: str | None = None):
        super().__init__()
        self.setObjectName("card")
        self.chart = chart
        self._flag_text, self._flag_bg = flag_text, flag_bg
        self.metric = Metric(title, big=True)
        self.metric.setFixedWidth(150)
        self.badge = FlagLabel()
        left = QVBoxLayout()
        left.addWidget(self.metric)
        left.addWidget(self.badge)
        left.addStretch(1)
        h = QHBoxLayout(self)
        h.setContentsMargins(12, 8, 12, 8)
        h.setSpacing(12)
        h.addLayout(left)
        h.addWidget(chart, 1)

    def set_live(self, text: str, flag_on: bool) -> None:
        self.metric.set(text, "neutral")
        if flag_on and self._flag_text:
            self.badge.set_flag(self._flag_text, self._flag_bg, "#000000")
        else:
            self.badge.set_flag("", None, None)


class GraphPage(QWidget):
    """Seconda schermata: acceleratore, freno e sterzo che scorrono nel tempo."""
    WINDOWS = [10, 20, 30, 60]

    def __init__(self, on_window_changed):
        super().__init__()
        self._on_window = on_window_changed

        self.window_box = QComboBox()
        self.window_box.addItems([f"{w} s" for w in self.WINDOWS])
        self.window_box.setCurrentIndex(1)
        self.window_box.currentIndexChanged.connect(lambda i: self._changed(i))
        self.pause_box = QCheckBox("Pausa grafici")
        legend = QLabel(
            f"<span style='color:{COL_THROTTLE[0]}'>■</span> acceleratore &nbsp; "
            f"<span style='color:{COL_THROTTLE[1]}'>■</span> TC attivo &nbsp;&nbsp; "
            f"<span style='color:{COL_BRAKE[0]}'>■</span> freno &nbsp; "
            f"<span style='color:{COL_BRAKE[1]}'>■</span> ABS attivo")
        top = QHBoxLayout()
        top.addWidget(legend)
        top.addStretch(1)
        top.addWidget(QLabel("Finestra"))
        top.addWidget(self.window_box)
        top.addWidget(self.pause_box)

        pedals = [0, 50, 100]
        self.p_thr = GraphPanel("ACCELERATORE", TraceWidget(0, 100, pedals, COL_THROTTLE, fill=True),
                                "TC", COL_THROTTLE[1])
        self.p_brk = GraphPanel("FRENO", TraceWidget(0, 100, pedals, COL_BRAKE, fill=True),
                                "ABS", COL_BRAKE[1])
        self.p_str = GraphPanel("STERZO", TraceWidget(-270, 270, [-270, 0, 270], COL_STEER))
        self.p_gear = GraphPanel("MARCIA", TraceWidget(
            -1.5, 6.5, list(range(-1, 7)), COL_GEAR, label_fn=lambda v: gear_name(int(round(v)))))

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 6, 0, 0)
        lay.setSpacing(8)
        lay.addLayout(top)
        for panel in (self.p_thr, self.p_brk, self.p_str, self.p_gear):
            lay.addWidget(panel, 1)

    def _changed(self, index: int) -> None:
        self._on_window(self.WINDOWS[index])

    def set_window(self, seconds: int) -> None:
        best = min(range(len(self.WINDOWS)), key=lambda i: abs(self.WINDOWS[i] - seconds))
        self.window_box.setCurrentIndex(best)

    def paused(self) -> bool:
        return self.pause_box.isChecked()

    def refresh(self, model: TelemetryModel, cfg: AppSettings) -> None:
        window = float(cfg.graph_seconds)
        samples = model.history(window)
        now = time.monotonic()
        clamp = lambda v: min(max(v, 0.0), 1.0) * 100.0
        # campione = (t, gas, freno, sterzo, tc, abs, marcia)
        thr = [(x[0], clamp(x[1]), 1 if x[4] else 0) for x in samples]
        brk = [(x[0], clamp(x[2]), 1 if x[5] else 0) for x in samples]
        steer = [(x[0], steer_to_degrees(x[3], cfg.steer_unit, cfg.steer_max_deg, cfg.steer_invert), 0)
                 for x in samples]
        gears = [(x[0], x[6]) for x in samples]
        gmax = max([6] + [g for _, g in gears])          # la scala cresce se compare la 7a
        self.p_gear.chart.set_range(-1.5, gmax + 0.5, list(range(-1, gmax + 1)))
        self.p_gear.chart.set_data(gear_steps(gears), now, window)
        m = cfg.steer_max_deg
        self.p_str.chart.set_range(-m, m, [-m, 0, m])
        self.p_thr.chart.set_data(thr, now, window)
        self.p_brk.chart.set_data(brk, now, window)
        self.p_str.chart.set_data(steer, now, window)
        if samples:
            last = samples[-1]
            self.p_thr.set_live(f"{thr[-1][1]:.0f} %", bool(last[4]))
            self.p_brk.set_live(f"{brk[-1][1]:.0f} %", bool(last[5]))
            self.p_str.set_live(f"{steer[-1][1]:+.0f}°", False)
            self.p_gear.set_live(gear_name(gears[-1][1]), False)


# ==========================================================================
# Dialogo impostazioni
# ==========================================================================
class SettingsDialog(QDialog):
    # (attributo, etichetta, minimo, massimo, passo, decimali)
    GROUPS = [
        ("Pressione gomme (PSI)", [
            ("p_lo", "Minimo ottimale", 15, 40, 0.1, 1),
            ("p_hi", "Massimo ottimale", 15, 40, 0.1, 1),
            ("p_margin", "Margine giallo", 0, 10, 0.1, 1)]),
        ("Temperatura core gomma (°C)", [
            ("core_lo", "Minimo ottimale", 0, 200, 1, 0),
            ("core_hi", "Massimo ottimale", 0, 200, 1, 0),
            ("core_margin", "Margine giallo", 0, 100, 1, 0)]),
        ("Temperatura superficie I/C/E (°C)", [
            ("surf_lo", "Minimo ottimale", 0, 250, 1, 0),
            ("surf_hi", "Massimo ottimale", 0, 250, 1, 0),
            ("surf_margin", "Margine giallo", 0, 100, 1, 0)]),
        ("Pastiglie (mm, 0 = disattivato)", [
            ("pad_warn", "Giallo sotto", 0, 100, 0.5, 1),
            ("pad_crit", "Rosso sotto", 0, 100, 0.5, 1)]),
        ("Dischi (mm, 0 = disattivato)", [
            ("disc_warn", "Giallo sotto", 0, 100, 0.5, 1),
            ("disc_crit", "Rosso sotto", 0, 100, 0.5, 1)]),
        ("Carburante (giri rimasti)", [
            ("fuel_laps_warn", "Giallo sotto", 0, 100, 0.5, 1),
            ("fuel_laps_crit", "Rosso sotto", 0, 100, 0.5, 1)]),
    ]

    def __init__(self, cfg: AppSettings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Impostazioni")
        self.setMinimumWidth(640)
        self._base = cfg
        self._spins: dict[str, QDoubleSpinBox] = {}

        tabs = QTabWidget()
        tabs.addTab(self._build_connection_tab(), "Connessione")
        tabs.addTab(self._build_thresholds_tab(), "Soglie e colori")
        tabs.addTab(self._build_steering_tab(), "Volante")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.RestoreDefaults)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults).clicked.connect(
            lambda: self._load(AppSettings()))

        lay = QVBoxLayout(self)
        lay.addWidget(tabs)
        lay.addWidget(buttons)
        self._load(cfg)

    # ---- costruzione ----
    def _build_connection_tab(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        self.sim = QComboBox()
        self.sim.addItems(list(SIMS))
        self.host = QLineEdit()
        self.host.setPlaceholderText("es. 192.168.1.20  oppure  nome-pc")
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.alive = QSpinBox()
        self.alive.setRange(2, 25)
        self.alive.setSuffix(" s")
        self.refresh_hz = QSpinBox()
        self.refresh_hz.setRange(5, 60)
        self.refresh_hz.setSuffix(" Hz")
        self.auto = QCheckBox("Connetti automaticamente all'avvio")
        hint = QLabel("L'IP e' quello del PC dove gira il server ACC-TX-UDP (127.0.0.1 se e' lo "
                      "stesso PC).\nIl server scollega i client dopo 30 s senza ALIVE: "
                      "tieni l'intervallo ben sotto.")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        f.addRow("Simulatore", self.sim)
        f.addRow("Indirizzo server", self.host)
        f.addRow("Porta UDP", self.port)
        f.addRow("Intervallo ALIVE", self.alive)
        f.addRow("Aggiornamento schermo", self.refresh_hz)
        f.addRow("", self.auto)
        f.addRow(hint)
        return w

    STEER_UNITS = [("norm", "Normalizzato (-1 ... +1)"), ("deg", "Gradi"), ("rad", "Radianti")]

    def _build_steering_tab(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        self.steer_unit = QComboBox()
        self.steer_unit.addItems([label for _, label in self.STEER_UNITS])
        self.steer_max = QDoubleSpinBox()
        self.steer_max.setRange(30, 1080)
        self.steer_max.setSingleStep(10)
        self.steer_max.setDecimals(0)
        self.steer_max.setSuffix(" °")
        self.steer_invert = QCheckBox("Inverti il senso di rotazione")
        hint = QLabel("Unita' del campo steerAngle: per scoprirla apri Aiuto > Diagnostica pacchetto, "
                      "gira il volante a fondo corsa e guarda min/max di steerAngle. Se restano tra "
                      "-1 e +1 e' normalizzato: in quel caso imposta qui la rotazione per lato "
                      "(meta' dell'escursione totale dell'auto, tipicamente 250-330 gradi per le GT3).\n"
                      "Se il volante grafico gira dalla parte opposta, usa 'Inverti'.")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        f.addRow("Unita' di steerAngle", self.steer_unit)
        f.addRow("Rotazione per lato (solo normalizzato)", self.steer_max)
        f.addRow("", self.steer_invert)
        f.addRow(hint)
        return w

    def _build_thresholds_tab(self) -> QWidget:
        w = QWidget()
        grid = QGridLayout(w)
        for n, (title, rows) in enumerate(self.GROUPS):
            box = QGroupBox(title)
            form = QFormLayout(box)
            for attr, label, lo, hi, step, dec in rows:
                sp = QDoubleSpinBox()
                sp.setRange(lo, hi)
                sp.setSingleStep(step)
                sp.setDecimals(dec)
                self._spins[attr] = sp
                form.addRow(label, sp)
            grid.addWidget(box, n // 2, n % 2)
        return w

    # ---- valori <-> widget ----
    def _load(self, cfg: AppSettings) -> None:
        self.sim.setCurrentText(cfg.sim)
        self.host.setText(cfg.host)
        self.port.setValue(cfg.port)
        self.alive.setValue(int(cfg.alive_interval))
        self.refresh_hz.setValue(cfg.refresh_hz)
        self.auto.setChecked(cfg.auto_connect)
        for attr, sp in self._spins.items():
            sp.setValue(getattr(cfg, attr))
        keys = [k for k, _ in self.STEER_UNITS]
        self.steer_unit.setCurrentIndex(keys.index(cfg.steer_unit) if cfg.steer_unit in keys else 0)
        self.steer_max.setValue(cfg.steer_max_deg)
        self.steer_invert.setChecked(cfg.steer_invert)

    def values(self) -> AppSettings:
        vals = {attr: sp.value() for attr, sp in self._spins.items()}
        return replace(
            self._base, sim=self.sim.currentText(), host=self.host.text(),
            port=self.port.value(), alive_interval=float(self.alive.value()),
            refresh_hz=self.refresh_hz.value(), auto_connect=self.auto.isChecked(),
            steer_unit=self.STEER_UNITS[self.steer_unit.currentIndex()][0],
            steer_max_deg=self.steer_max.value(), steer_invert=self.steer_invert.isChecked(),
            **vals).sanitize()

    def accept(self) -> None:
        host = self.host.text().strip()
        if not host or " " in host:
            QMessageBox.warning(self, "Impostazioni", "Inserisci un indirizzo valido (IP o nome host).")
            return
        super().accept()


# ==========================================================================
# Diagnostica del pacchetto
# ==========================================================================
class DiagnosticsDialog(QDialog):
    """
    Campo per campo: cosa arriva davvero dal server. Non modale: lasciala aperta
    mentre guidi, poi guarda quali campi non sono MAI stati diversi da zero.
    """
    COLS = ["Campo", "Attuale", "Min", "Max", "Valori ≠ 0"]

    def __init__(self, provider, resetter, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Diagnostica pacchetto")
        self.resize(680, 700)
        self._provider, self._resetter = provider, resetter
        self._names: list[str] = []
        self._items: list[list] = []
        self._nz: list[int] = []
        self._flag: list[bool | None] = []

        self.summary = QLabel("In attesa di dati...")
        self.summary.setWordWrap(True)
        self.only_zero = QCheckBox("Mostra solo i campi mai diversi da zero")
        self.only_zero.toggled.connect(lambda _=None: self._apply_filter())

        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setColumnWidth(0, 200)

        btn_reset = QPushButton("Azzera statistiche")
        btn_reset.clicked.connect(lambda: self._reset())
        btn_copy = QPushButton("Copia report")
        btn_copy.clicked.connect(lambda: self._copy())
        row = QHBoxLayout()
        row.addWidget(self.only_zero)
        row.addStretch(1)
        row.addWidget(btn_reset)
        row.addWidget(btn_copy)

        lay = QVBoxLayout(self)
        lay.addWidget(self.summary)
        lay.addLayout(row)
        lay.addWidget(self.table, 1)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(500)

    @staticmethod
    def _fmt(v) -> str:
        if v is None:
            return ""
        if isinstance(v, float):
            return f"{v:.3f}"
        return str(v)

    def _rebuild(self, names: list) -> None:
        self._names = names
        self.table.setRowCount(len(names))
        self._items = []
        for r, name in enumerate(names):
            cells = []
            for c in range(len(self.COLS)):
                it = QTableWidgetItem(name if c == 0 else "")
                self.table.setItem(r, c, it)
                cells.append(it)
            self._items.append(cells)
        self._nz = [0] * len(names)
        self._flag = [None] * len(names)

    def refresh(self) -> None:
        snap = self._provider()
        if not snap:
            self.summary.setText("Nessun dato: non sei connesso o il server non sta inviando.")
            return
        if len(snap) != len(self._names):
            self._rebuild(list(snap))
        amber = QBrush(QColor("#f1c40f"))
        normal = QBrush(QColor("#e6e6e6"))
        for r, name in enumerate(self._names):
            last, mn, mx, nz, n = snap[name]
            cells = self._items[r]
            cells[1].setText(self._fmt(last))
            cells[2].setText(self._fmt(mn))
            cells[3].setText(self._fmt(mx))
            cells[4].setText(f"{100.0 * nz / n:.0f} %" if n else "")
            self._nz[r] = nz
            never = nz == 0
            if never != self._flag[r]:               # cambia colore solo se cambia lo stato
                self._flag[r] = never
                cells[4].setForeground(amber if never else normal)
        zero = FieldStats.never_nonzero_groups(snap)
        if zero:
            self.summary.setText(
                f"{len(zero)} campi non sono MAI stati diversi da zero da quando sei connesso "
                f"(guida un po' e tieni aperta questa finestra):\n" + ", ".join(zero))
        else:
            self.summary.setText("Tutti i campi hanno avuto almeno un valore diverso da zero.")
        self._apply_filter()

    def _apply_filter(self) -> None:
        only = self.only_zero.isChecked()
        for r, nz in enumerate(self._nz):
            self.table.setRowHidden(r, bool(only and nz > 0))

    def _reset(self) -> None:
        self._resetter()
        self._names = []
        self.table.setRowCount(0)

    def _copy(self) -> None:
        snap = self._provider() or {}
        lines = ["campo | attuale | min | max | non-zero/totale"]
        for name, (last, mn, mx, nz, n) in snap.items():
            lines.append(f"{name} | {self._fmt(last)} | {self._fmt(mn)} | {self._fmt(mx)} | {nz}/{n}")
        lines.append("")
        lines.append("MAI diversi da zero: " + ", ".join(FieldStats.never_nonzero_groups(snap)))
        QApplication.clipboard().setText("\n".join(lines))
        self.summary.setText(self.summary.text() + "\n(report copiato negli appunti)")


# ==========================================================================
# Finestra principale
# ==========================================================================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.cfg = load_settings()
        self.model: TelemetryModel | None = None
        self.client: TelemetryClient | None = None
        self.fuel = FuelTracker()
        self._last_rx: float | None = None
        self._stale: bool | None = None
        self.diag: DiagnosticsDialog | None = None

        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(1100, 680)
        self.resize(1320, 780)
        self._restore_geometry()
        if self.cfg.always_on_top:
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)

        self._build_ui()
        self._build_menu()
        self._build_statusbar()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(int(1000 / self.cfg.refresh_hz))

        if self.cfg.auto_connect:
            self.connect_server()
        self._update_actions()

    # ---- costruzione UI ----
    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        self.header = HeaderPanel()
        root.addWidget(self.header)

        self.body = QWidget()
        body = QHBoxLayout(self.body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(10)

        tyres = QGridLayout()
        tyres.setSpacing(10)
        self.cards = [TyreCard(t) for t in WHEEL_TITLES]   # FL FR RL RR
        for i, card in enumerate(self.cards):
            tyres.addWidget(card, i // 2, i % 2)
        self.car = CarPanel()
        body.addLayout(tyres, 3)
        body.addWidget(self.car, 1)

        self.graphs = GraphPage(self._set_graph_window)
        self.graphs.set_window(self.cfg.graph_seconds)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.body, "Muretto")
        self.tabs.addTab(self.graphs, "Grafici")
        root.addWidget(self.tabs, 1)

        self._opacity = QGraphicsOpacityEffect(self.tabs)
        self._opacity.setOpacity(1.0)
        self.tabs.setGraphicsEffect(self._opacity)
        self.setCentralWidget(central)

    def _build_menu(self) -> None:
        mb = self.menuBar()

        m_file = mb.addMenu("&File")
        self.act_connect = QAction("&Connetti", self)
        self.act_connect.setShortcut(QKeySequence("Ctrl+K"))
        self.act_connect.triggered.connect(lambda: self.connect_server())
        self.act_disconnect = QAction("&Disconnetti", self)
        self.act_disconnect.triggered.connect(lambda: self.disconnect_server())
        act_quit = QAction("&Esci", self)
        act_quit.setShortcut(QKeySequence("Ctrl+Q"))
        act_quit.triggered.connect(lambda: self.close())
        m_file.addAction(self.act_connect)
        m_file.addAction(self.act_disconnect)
        m_file.addSeparator()
        m_file.addAction(act_quit)

        m_set = mb.addMenu("&Impostazioni")
        act_set = QAction("Connessione e &soglie...", self)
        act_set.setShortcut(QKeySequence("Ctrl+,"))
        act_set.triggered.connect(lambda: self.open_settings())
        m_set.addAction(act_set)

        m_view = mb.addMenu("&Visualizza")
        act_page1 = QAction("&Muretto", self)
        act_page1.setShortcut(QKeySequence("Ctrl+1"))
        act_page1.triggered.connect(lambda: self.tabs.setCurrentIndex(0))
        act_page2 = QAction("&Grafici", self)
        act_page2.setShortcut(QKeySequence("Ctrl+2"))
        act_page2.triggered.connect(lambda: self.tabs.setCurrentIndex(1))
        m_view.addAction(act_page1)
        m_view.addAction(act_page2)
        m_view.addSeparator()
        self.act_full = QAction("&Schermo intero", self)
        self.act_full.setCheckable(True)
        self.act_full.setShortcut(QKeySequence("F11"))
        self.act_full.toggled.connect(self._toggle_fullscreen)
        self.act_top = QAction("Sempre in &primo piano", self)
        self.act_top.setCheckable(True)
        self.act_top.setChecked(self.cfg.always_on_top)
        self.act_top.toggled.connect(self._toggle_on_top)
        m_view.addAction(self.act_full)
        m_view.addAction(self.act_top)

        m_help = mb.addMenu("&Aiuto")
        act_about = QAction("&Informazioni", self)
        act_about.triggered.connect(lambda: self.show_about())
        act_diag = QAction("&Diagnostica pacchetto...", self)
        act_diag.setShortcut(QKeySequence("Ctrl+D"))
        act_diag.triggered.connect(lambda: self.open_diagnostics())
        m_help.addAction(act_diag)
        m_help.addAction(act_about)

    def _build_statusbar(self) -> None:
        sb = self.statusBar()
        self.lbl_conn = QLabel("")
        self.lbl_rate = QLabel("")
        self.lbl_bad = QLabel("")
        for lab in (self.lbl_conn, self.lbl_rate, self.lbl_bad):
            sb.addPermanentWidget(lab)
        sb.showMessage("Pronto")

    # ---- azioni ----
    def _update_actions(self) -> None:
        running = self.client is not None
        self.act_connect.setEnabled(not running)
        self.act_disconnect.setEnabled(running)

    def connect_server(self) -> None:
        self.disconnect_server()
        host, port = self.cfg.host, self.cfg.port
        try:
            socket.getaddrinfo(host, port, type=socket.SOCK_DGRAM)
        except OSError as e:
            QMessageBox.warning(self, "Connessione", f"Indirizzo non valido: {host}\n{e}")
            return
        self.fuel = FuelTracker()
        self._last_rx = None
        self.model = TelemetryModel()
        self.client = TelemetryClient(
            host, port, self.model, adapter=SIMS.get(self.cfg.sim, ACCAdapter),
            alive_interval=self.cfg.alive_interval)
        self.client.start()
        self.statusBar().showMessage(f"Connessione a {host}:{port} ...")
        self._update_actions()

    def disconnect_server(self) -> None:
        if self.client is not None:
            self.client.stop()
            self.client.join(timeout=1.5)
        self.client = None
        self.model = None
        self._update_actions()

    def open_settings(self) -> None:
        dlg = SettingsDialog(self.cfg, self)
        if not dlg.exec():                  # 0 = annullato, 1 = OK
            return
        old, new = self.cfg, dlg.values()
        conn_changed = ((old.sim, old.host, old.port, old.alive_interval)
                        != (new.sim, new.host, new.port, new.alive_interval))
        self.cfg = new
        save_settings(self.cfg)
        self.timer.setInterval(int(1000 / self.cfg.refresh_hz))
        if conn_changed and self.client is not None:
            self.connect_server()

    def _set_graph_window(self, seconds: int) -> None:
        self.cfg.graph_seconds = seconds

    def _toggle_fullscreen(self, on: bool) -> None:
        if on:
            self.showFullScreen()
        else:
            self.showNormal()

    def _toggle_on_top(self, on: bool) -> None:
        self.cfg.always_on_top = on
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, on)
        self.show()                       # serve per applicare il flag

    def open_diagnostics(self) -> None:
        if self.diag is None:
            self.diag = DiagnosticsDialog(
                lambda: self.model.stats_snapshot() if self.model else None,
                lambda: self.model.stats_reset() if self.model else None,
                self)
        self.diag.show()
        self.diag.raise_()
        self.diag.activateWindow()

    def show_about(self) -> None:
        QMessageBox.about(
            self, "Informazioni",
            f"{APP_NAME}\nMuretto per sim racing basato su ACC-TX-UDP.\n\n"
            f"Server: {self.cfg.host}:{self.cfg.port}  ({self.cfg.sim})\n"
            f"Impostazioni: {save_path_hint()}")

    # ---- aggiornamento periodico ----
    def _set_stale(self, stale: bool) -> None:
        if stale != self._stale:
            self._stale = stale
            self._opacity.setOpacity(0.35 if stale else 1.0)

    def refresh(self) -> None:
        snap = self.model.snapshot() if self.model else None
        connected = bool(snap and snap.connected)
        self._set_stale(not connected)
        self._update_statusbar(snap)

        if snap is None:
            self.header.show_status("DISCONNESSO", "na")
            return
        if snap.state is None:
            self.header.show_status("IN ATTESA DEL SERVER...", "warn")
            return

        s = snap.state
        if connected and s.rx_time != self._last_rx and is_live(s.status, s.rpm):   # solo in pista
            self.fuel.update(s.laps_completed, s.fuel)
        self._last_rx = s.rx_time

        self.header.refresh_from(s, connected, self.fuel, self.cfg)
        wear_ok = any(s.tyre_wear)          # tutto a zero = il sim non lo fornisce
        for i, card in enumerate(self.cards):
            card.refresh_from(s, i, self.cfg, wear_ok)
        self.car.refresh_from(s, self.cfg)
        # i grafici si aggiornano solo se la scheda e' visibile e non in pausa;
        # senza segnale restano fermi, cosi' si possono guardare gli ultimi secondi
        if connected and self.tabs.currentIndex() == 1 and not self.graphs.paused():
            self.graphs.refresh(self.model, self.cfg)

    def _update_statusbar(self, snap) -> None:
        if snap is None:
            self.lbl_conn.setText("Disconnesso   ")
            self.lbl_rate.setText("")
            self.lbl_bad.setText("")
            return
        self.lbl_conn.setText(
            f"{'Connesso' if snap.connected else 'Nessun segnale'}  "
            f"{self.cfg.host}:{self.cfg.port}   ")
        self.lbl_rate.setText(f"{snap.rate_hz:.0f} pacchetti/s   ")
        self.lbl_bad.setText(f"scartati: {snap.bad_packets}   " if snap.bad_packets else "")

    # ---- geometria e chiusura ----
    def _restore_geometry(self) -> None:
        if self.cfg.geometry:
            try:
                self.restoreGeometry(QByteArray.fromBase64(self.cfg.geometry.encode("ascii")))
            except Exception:
                pass

    def closeEvent(self, event) -> None:
        try:
            if not self.isFullScreen():
                self.cfg.geometry = bytes(self.saveGeometry().toBase64().data()).decode("ascii")
        except Exception:
            pass
        save_settings(self.cfg)
        self.timer.stop()
        self.disconnect_server()
        super().closeEvent(event)


def save_path_hint() -> str:
    from pitwall_logic import settings_path
    return str(settings_path())


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyleSheet(QSS)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
