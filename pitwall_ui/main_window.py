"""Finestra principale: menu, schede, barra di stato, timer di aggiornamento e collegamento al server."""
from __future__ import annotations

import socket
import sys

from PySide6.QtCore import QByteArray, QTimer, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QGraphicsOpacityEffect, QLabel, QMainWindow, QMessageBox, QTabWidget,
    QVBoxLayout, QWidget,
)

from acc_tx_client import ACCAdapter, TelemetryClient, TelemetryModel
from pitwall_logic import FuelTracker, is_live, load_settings, save_settings, settings_path
from pitwall_ui.common import APP_NAME, QSS, SIMS
from pitwall_ui.dashboard import DashboardPage, HeaderPanel
from pitwall_ui.dialogs import DiagnosticsDialog, SettingsDialog
from pitwall_ui.graphs import GraphPage
from pitwall_ui.suspension import SuspensionPage


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

        self.dashboard = DashboardPage()

        self.graphs = GraphPage(self._set_graph_window)
        self.graphs.set_window(self.cfg.graph_seconds)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.dashboard, "Muretto")
        self.susp = SuspensionPage()
        self.tabs.addTab(self.graphs, "Grafici")
        self.tabs.addTab(self.susp, "Sospensioni")
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
        act_page3 = QAction("&Sospensioni", self)
        act_page3.setShortcut(QKeySequence("Ctrl+3"))
        act_page3.triggered.connect(lambda: self.tabs.setCurrentIndex(2))
        m_view.addAction(act_page2)
        m_view.addAction(act_page3)
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
        self.susp.reset_range()
        self.dashboard.reset()
        self.graphs.reset()
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
        self.graphs.on_settings_changed()
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
        self.dashboard.refresh(s, self.cfg)
        # i grafici si aggiornano solo se la scheda e' visibile e non in pausa;
        # senza segnale restano fermi, cosi' si possono guardare gli ultimi secondi
        if connected and self.tabs.currentIndex() == 1 and not self.graphs.paused():
            self.graphs.refresh(self.model, self.cfg)
        if self.tabs.currentIndex() == 2:
            self.susp.refresh(s, self.cfg)

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
    return str(settings_path())


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyleSheet(QSS)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
