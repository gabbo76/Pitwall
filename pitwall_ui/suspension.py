"""Pagina Sospensioni: quattro sospensioni McPherson stilizzate che si muovono con i dati."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QTimer, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from acc_tx_client import CarState
from pitwall_logic import (
    AppSettings, LEVEL_COLORS, TravelTracker, resolve_susp_unit, travel_to_mm,
)
from pitwall_ui.common import Metric, WHEEL_TITLES


class SuspensionWidget(QWidget):
    """
    Sospensione tipo McPherson in vista frontale: ruota a terra, montante, molla attorno
    all'ammortizzatore, braccio inferiore e scocca. La ruota resta ferma; quando la
    sospensione si comprime scende la scocca: la molla si accorcia, lo stelo rientra
    nel cilindro e il braccio si raddrizza. Il disegno e' in unita' logiche (DW x DH) e
    viene scalato per stare nel widget, quindi le proporzioni non dipendono dalla finestra.
    Le ruote di destra sono specchiate, cosi' la scocca sta sempre verso il centro dell'auto.
    """
    DW, DH = 260.0, 220.0

    def __init__(self, mirror: bool = False):
        super().__init__()
        self.mirror = mirror
        self._target = 0.5                 # 0 = estesa, 1 = compressa
        self._shown = 0.5
        self.setMinimumSize(200, 170)

    def set_target(self, c: float) -> None:
        self._target = min(max(c, 0.0), 1.0)

    def step(self) -> None:
        """Avvicina il valore mostrato a quello reale; chiamato ~30 volte al secondo."""
        d = self._target - self._shown
        if abs(d) < 0.002:
            if self._shown != self._target:
                self._shown = self._target
                self.update()
            return
        self._shown += d * 0.45
        self.update()

    @staticmethod
    def geometry_for(c: float) -> dict:
        """Posizione dei pezzi mobili per compressione c (0..1), in unita' logiche."""
        body_top = 22.0 + c * 34.0                     # la scocca scende di 34 unita'
        slab_bot = body_top + 18.0
        ubj, lbj = (88.0, 122.0), (88.0, 192.0)        # attacco montante e snodo inferiore (fermi)
        lc = 34.0                                      # lunghezza del cilindro
        return dict(ground=205.0, body_top=body_top, slab_bot=slab_bot, ubj=ubj, lbj=lbj,
                    pivot=(196.0, body_top + 122.0), spring_len=ubj[1] - slab_bot,
                    cyl_bot=slab_bot + lc, rod_top=slab_bot + lc - 8.0, sub_bot=body_top + 132.0)

    def paintEvent(self, event) -> None:
        w, h = float(self.width()), float(self.height())
        k = min(w / self.DW, h / self.DH)
        if k <= 0.2:
            return
        c = self._shown
        g = self.geometry_for(c)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.translate((w - self.DW * k) / 2.0, (h - self.DH * k) / 2.0)
        p.scale(k, k)
        if self.mirror:
            p.translate(self.DW, 0.0)
            p.scale(-1.0, 1.0)

        def pen(color: str, width: float, round_cap: bool = True) -> QPen:
            q = QPen(QColor(color))
            q.setWidthF(width)
            q.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            if round_cap:
                q.setCapStyle(Qt.PenCapStyle.RoundCap)
            return q

        ux = g["ubj"][0]
        # terreno
        p.setPen(pen("#6f7a89", 2.0))
        p.drawLine(QPointF(8.0, g["ground"] + 0.5), QPointF(252.0, g["ground"] + 0.5))

        # ruota (ferma) con cerchio
        p.setPen(pen("#6f7a89", 1.5, False))
        p.setBrush(QColor("#2a313b"))
        p.drawRoundedRect(QRectF(22.0, 108.0, 58.0, 97.0), 10.0, 10.0)
        p.setBrush(QColor("#4a5568"))
        p.drawRoundedRect(QRectF(33.0, 119.0, 36.0, 75.0), 5.0, 5.0)

        # mozzo + braccio inferiore (dallo snodo basso al telaio) + montante
        p.setPen(pen("#8b95a3", 6.0))
        p.drawLine(QPointF(51.0, 158.0), QPointF(ux, 158.0))
        p.setPen(pen("#aab4c2", 6.0))
        p.drawLine(QPointF(ux, g["lbj"][1]), QPointF(g["pivot"][0], g["pivot"][1]))
        p.setPen(pen("#8b95a3", 8.0))
        p.drawLine(QPointF(ux, g["ubj"][1]), QPointF(ux, g["lbj"][1]))

        # molla: zig-zag attorno all'ammortizzatore; il colore avvisa vicino al fondo corsa
        level = "ok" if c < 0.75 else "warn" if c < 0.9 else "crit"
        n, amp = 12, 13.0
        spring = QPainterPath()
        spring.moveTo(QPointF(ux, g["slab_bot"]))
        for i in range(1, n):
            spring.lineTo(QPointF(ux + (amp if i % 2 else -amp),
                                  g["slab_bot"] + g["spring_len"] * i / n))
        spring.lineTo(QPointF(ux, g["ubj"][1]))
        p.setPen(pen(LEVEL_COLORS[level], 3.0))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(spring)

        # ammortizzatore: stelo (sulla ruota) che rientra nel cilindro (sulla scocca)
        p.setPen(pen("#cfd6df", 4.0))
        p.drawLine(QPointF(ux, g["ubj"][1]), QPointF(ux, g["rod_top"]))
        p.setPen(pen("#8b95a3", 1.5, False))
        p.setBrush(QColor("#3a4350"))
        p.drawRoundedRect(QRectF(ux - 5.5, g["slab_bot"], 11.0, g["cyl_bot"] - g["slab_bot"]), 3.0, 3.0)

        # scocca: lastra sopra la ruota + blocco del telaio verso il centro dell'auto
        body = QPainterPath()
        body.addRoundedRect(QRectF(14.0, g["body_top"], 236.0, 18.0), 6.0, 6.0)
        body.addRoundedRect(QRectF(196.0, g["body_top"], 54.0, 132.0), 6.0, 6.0)
        p.setPen(pen("#aab4c2", 1.5, False))
        p.setBrush(QColor("#5b6675"))
        p.drawPath(body.simplified())

        # snodi
        p.setPen(pen("#14171c", 1.0, False))
        p.setBrush(QColor("#e6e6e6"))
        for x, y in (g["ubj"], g["lbj"], g["pivot"]):
            p.drawEllipse(QPointF(x, y), 5.0, 5.0)
        p.end()


class SuspensionCard(QFrame):
    """Una ruota: sospensione animata, corsa in mm e stato del danno."""

    def __init__(self, title: str, mirror: bool = False):
        super().__init__()
        self.setObjectName("card")
        t = QLabel(title)
        t.setObjectName("title")
        self.view = SuspensionWidget(mirror)
        self.travel = Metric("CORSA  mm", big=True)
        self.damage = Metric("DANNO")
        row = QHBoxLayout()
        row.addWidget(self.travel)
        row.addStretch(1)
        row.addWidget(self.damage)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 12)
        lay.addWidget(t)
        lay.addWidget(self.view, 1)
        lay.addLayout(row)

    def refresh_from(self, mm: float, c: float, damage: float, has_data: bool) -> None:
        self.view.set_target(c)
        self.travel.set(f"{mm:.1f}" if has_data else "n/d", "neutral" if has_data else "na")
        if damage <= 0.001:
            self.damage.set("OK", "ok")
        else:
            pct = min(damage, 1.0) * 100.0          # si assume una scala 0..1
            self.damage.set(f"{pct:.0f} %", "crit" if pct >= 30 else "warn")


class SuspensionPage(QWidget):
    """Terza schermata: le quattro sospensioni stilizzate che si muovono."""

    def __init__(self):
        super().__init__()
        self.tracker = TravelTracker()
        self.cards = [SuspensionCard(t, mirror=(i % 2 == 1))          # FL FR RL RR; destra specchiata
                      for i, t in enumerate(WHEEL_TITLES)]
        self._seen_big = False
        self.mode = QLabel("")
        self.mode.setObjectName("hint")
        btn = QPushButton("Azzera range")
        btn.clicked.connect(lambda: self.reset_range())
        top = QHBoxLayout()
        top.addWidget(self.mode)
        top.addStretch(1)
        top.addWidget(btn)
        grid = QGridLayout()
        grid.setSpacing(10)
        for i, card in enumerate(self.cards):
            grid.addWidget(card, i // 2, i % 2)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 6, 0, 0)
        lay.addLayout(top)
        lay.addLayout(grid, 1)
        # l'animazione gira solo quando la pagina e' visibile
        self.anim = QTimer(self)
        self.anim.setInterval(33)
        self.anim.timeout.connect(self._tick)

    def showEvent(self, event) -> None:
        self.anim.start()
        super().showEvent(event)

    def hideEvent(self, event) -> None:
        self.anim.stop()
        super().hideEvent(event)

    def _tick(self) -> None:
        for card in self.cards:
            card.view.step()

    def reset_range(self) -> None:
        self.tracker.reset()
        self._seen_big = False

    def refresh(self, s: CarState, cfg: AppSettings) -> None:
        unit, self._seen_big = resolve_susp_unit(cfg.susp_unit, s.susp_travel, self._seen_big)
        mm = [travel_to_mm(v, unit) for v in s.susp_travel]
        has_data = any(s.susp_travel)
        if has_data:
            self.tracker.update(mm)
        for i, card in enumerate(self.cards):
            c = self.tracker.norm(i, mm[i], cfg.susp_range_mm, cfg.susp_invert) if has_data else 0.5
            card.refresh_from(mm[i], c, s.susp_damage[i], has_data)
        scale = (f"corsa totale fissa {cfg.susp_range_mm:.0f} mm" if cfg.susp_range_mm > 0
                 else "scala automatica (minimo e massimo osservati)")
        self.mode.setText(f"Unita': {unit}{' (rilevata)' if cfg.susp_unit == 'auto' else ''}  |  {scale}")
