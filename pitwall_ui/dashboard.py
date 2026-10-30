"""Pagina Muretto: riquadri ruota (gomma + freno), intestazione di sessione, volante e pannello auto."""
from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QProgressBar, QVBoxLayout, QWidget,
)

from acc_tx_client import CarState
from pitwall_logic import (
    AppSettings, BrakeTracker, FLAG_NAMES, FuelTracker, classify_life, classify_window,
    fmt_clock_ms, fmt_lap, is_live, session_name, status_name, steer_out_of_range,
    steer_to_degrees,
)
from pitwall_ui.common import ENGINE_ON_RPM, FlagLabel, Metric, WHEEL_TITLES, fmt_or_dash, hline


class TyreCard(QFrame):
    """Una ruota: gomma (pressione, temperature, usura) e freno (pastiglie, disco, pressione)."""

    def __init__(self, title: str):
        super().__init__()
        self.setObjectName("card")
        g = QGridLayout(self)
        g.setContentsMargins(12, 8, 12, 10)
        g.setHorizontalSpacing(12)
        g.setVerticalSpacing(6)

        t = QLabel(title)
        t.setObjectName("title")
        # gomma
        self.surf = Metric("SUPERFICIE  °C")
        self.pressure = Metric("PRESSIONE  PSI", big=True)
        self.core = Metric("CORE  °C", big=True)
        self.t_in = Metric("INTERNA")
        self.t_mid = Metric("CENTRO")
        self.t_out = Metric("ESTERNA")
        self.wear = Metric("USURA GOMMA")
        # freno
        self.pad = Metric("PASTIGLIE  mm")
        self.disc = Metric("DISCO  mm")
        self.compound = Metric("MESCOLA PAST.")
        self.brake_press = Metric("PRESS. FRENO")
        self.pad_used = Metric("USURA PAST.  mm")
        self.disc_used = Metric("USURA DISCO  mm")
        self.press_bar = QProgressBar()
        self.press_bar.setObjectName("brk")
        self.press_bar.setRange(0, 100)
        self.press_bar.setTextVisible(False)
        self.press_bar.setFixedHeight(10)

        g.addWidget(t, 0, 0, 1, 3)
        g.addWidget(self.surf, 0, 3)
        g.addWidget(self.pressure, 1, 0, 1, 2)
        g.addWidget(self.core, 1, 2, 1, 2)
        g.addWidget(self.t_in, 2, 0)
        g.addWidget(self.t_mid, 2, 1)
        g.addWidget(self.t_out, 2, 2)
        g.addWidget(self.wear, 2, 3)
        g.addWidget(hline(), 3, 0, 1, 4)
        g.addWidget(self.pad, 4, 0)
        g.addWidget(self.disc, 4, 1)
        g.addWidget(self.compound, 4, 2)
        g.addWidget(self.brake_press, 4, 3)
        g.addWidget(self.pad_used, 5, 0)
        g.addWidget(self.disc_used, 5, 1)
        g.addWidget(self.press_bar, 5, 2, 1, 2)

    def refresh_from(self, s: CarState, i: int, cfg: AppSettings, wear_available: bool,
                     brakes: BrakeTracker) -> None:
        # --- gomma ---
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

        # --- freno ---
        pad, disc = s.pad_life[i], s.disc_life[i]
        self.pad.set(fmt_or_dash(pad, "{:.1f}"), classify_life(pad, cfg.pad_warn, cfg.pad_crit))
        self.disc.set(fmt_or_dash(disc, "{:.1f}"), classify_life(disc, cfg.disc_warn, cfg.disc_crit))
        comp = s.front_pad_compound if i < 2 else s.rear_pad_compound      # valore grezzo del server
        self.compound.set(str(comp), "neutral")
        bp = s.brake_pressure[i]
        self.brake_press.set(f"{bp:.1f}", "neutral")
        self.press_bar.setValue(int(brakes.press_norm(bp) * 100))
        pu, du = brakes.pad_used(i, pad), brakes.disc_used(i, disc)
        self.pad_used.set("--" if pu is None else f"{pu:.2f}", "na" if pu is None else "neutral")
        self.disc_used.set("--" if du is None else f"{du:.2f}", "na" if du is None else "neutral")


class HeaderPanel(QFrame):
    """Barra in alto: sessione, bandiera, posizione, tempi, carburante."""

    def __init__(self):
        super().__init__()
        self.setObjectName("card")
        h = QHBoxLayout(self)
        h.setContentsMargins(14, 8, 14, 8)
        h.setSpacing(16)
        # ogni voce riserva la larghezza del suo testo piu' largo previsto (sample) e i valori
        # numerici usano un font a larghezza fissa (mono): nulla si sposta al cambiare delle cifre
        self.state = Metric("STATO", sample="REPLAY")
        self.session = Metric("SESSIONE", sample="QUALIFICA")
        self.flag = FlagLabel()
        self.position = Metric("POSIZIONE", sample="P99", mono=True)
        self.laps = Metric("GIRI", sample="999", mono=True)
        self.cur = Metric("ATTUALE", sample="--:--.---", mono=True)
        self.last = Metric("ULTIMO", sample="--:--.---", mono=True)
        self.best = Metric("MIGLIORE", sample="--:--.---", mono=True)
        self.left = Metric("RIMASTO", sample="--:--:--", mono=True)
        self.fuel = Metric("FUEL  L", sample="100.0", mono=True)
        self.avg = Metric("L / GIRO", sample="00.00", mono=True)
        self.fuel_laps = Metric("GIRI FUEL", sample="000.0", mono=True)
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
        self.water.set(fmt_or_dash(s.water_temp, "{:.0f}"))
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


class DashboardPage(QWidget):
    """Prima schermata (Muretto): i quattro riquadri ruota con gomma e freno, e il pannello auto."""

    def __init__(self):
        super().__init__()
        self.brakes = BrakeTracker()
        self.cards = [TyreCard(t) for t in WHEEL_TITLES]       # FL FR RL RR
        self.car = CarPanel()
        grid = QGridLayout()
        grid.setSpacing(10)
        for i, card in enumerate(self.cards):
            grid.addWidget(card, i // 2, i % 2)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        lay.addLayout(grid, 3)
        lay.addWidget(self.car, 1)

    def reset(self) -> None:
        self.brakes.reset()

    def refresh(self, s: CarState, cfg: AppSettings) -> None:
        self.brakes.update(s.pad_life, s.disc_life, s.brake_pressure)
        wear_ok = any(s.tyre_wear)          # tutto a zero = il sim non lo fornisce
        for i, card in enumerate(self.cards):
            card.refresh_from(s, i, cfg, wear_ok, self.brakes)
        self.car.refresh_from(s, cfg)
