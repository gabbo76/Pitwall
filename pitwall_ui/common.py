"""Elementi condivisi dalle pagine: costanti, stile (QSS) e widget di base (Metric, FlagLabel)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from acc_tx_client import ACCAdapter
from pitwall_logic import LEVEL_COLORS


APP_NAME = "ACC Pit Wall"

# Simulatori supportati: nome -> adapter. Per aggiungerne uno basta un adapter che produca CarState.
SIMS = {"ACC": ACCAdapter}

# sopra questo regime il motore e' acceso anche se il flag isEngineRunning del server e' a 0
ENGINE_ON_RPM = 400

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


def fmt_or_dash(v: float, fmt: str) -> str:
    return "--" if v == 0 else fmt.format(v)
