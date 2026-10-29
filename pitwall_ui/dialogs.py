"""Finestre di dialogo: Impostazioni (connessione, soglie, volante, sospensioni) e Diagnostica pacchetto."""
from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QTimer
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QSpinBox, QTabWidget, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from acc_tx_client import FieldStats
from pitwall_logic import AppSettings
from pitwall_ui.common import SIMS


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
        tabs.addTab(self._build_susp_tab(), "Sospensioni")

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

    SUSP_UNITS = [("auto", "Automatico"), ("m", "Metri"), ("cm", "Centimetri"), ("mm", "Millimetri")]

    def _build_susp_tab(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        self.susp_unit = QComboBox()
        self.susp_unit.addItems([label for _, label in self.SUSP_UNITS])
        self.susp_range = QDoubleSpinBox()
        self.susp_range.setRange(0, 500)
        self.susp_range.setSingleStep(5)
        self.susp_range.setDecimals(0)
        self.susp_range.setSuffix(" mm")
        self.susp_invert = QCheckBox("Inverti (il valore cresce quando la sospensione si estende)")
        hint = QLabel("Unita' di suspensionTravel: 'Automatico' distingue metri (valori ~0.05) da "
                      "millimetri (valori ~25); in dubbio guarda i valori in Aiuto > Diagnostica pacchetto.\n"
                      "Corsa totale 0 = automatica: la scala si adatta a minimo e massimo osservati. "
                      "Se conosci la corsa dell'auto, impostala per avere posizioni reali.\n"
                      "Se la scocca sale invece di scendere quando frenando affonda l'avantreno, usa 'Inverti'.")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        f.addRow("Unita' di suspensionTravel", self.susp_unit)
        f.addRow("Corsa totale (0 = automatica)", self.susp_range)
        f.addRow("", self.susp_invert)
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
        skeys = [k for k, _ in self.SUSP_UNITS]
        self.susp_unit.setCurrentIndex(skeys.index(cfg.susp_unit) if cfg.susp_unit in skeys else 0)
        self.susp_range.setValue(cfg.susp_range_mm)
        self.susp_invert.setChecked(cfg.susp_invert)

    def values(self) -> AppSettings:
        vals = {attr: sp.value() for attr, sp in self._spins.items()}
        return replace(
            self._base, sim=self.sim.currentText(), host=self.host.text(),
            port=self.port.value(), alive_interval=float(self.alive.value()),
            refresh_hz=self.refresh_hz.value(), auto_connect=self.auto.isChecked(),
            steer_unit=self.STEER_UNITS[self.steer_unit.currentIndex()][0],
            steer_max_deg=self.steer_max.value(), steer_invert=self.steer_invert.isChecked(),
            susp_unit=self.SUSP_UNITS[self.susp_unit.currentIndex()][0],
            susp_range_mm=self.susp_range.value(), susp_invert=self.susp_invert.isChecked(),
            **vals).sanitize()

    def accept(self) -> None:
        host = self.host.text().strip()
        if not host or " " in host:
            QMessageBox.warning(self, "Impostazioni", "Inserisci un indirizzo valido (IP o nome host).")
            return
        super().accept()


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
