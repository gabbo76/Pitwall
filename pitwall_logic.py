"""
Logica del muretto, SENZA dipendenze da Qt (cosi' si puo' testare da sola).

  - AppSettings / load_settings / save_settings : impostazioni su file JSON
  - classify_window / classify_life              : livello (ok/warn/crit/low) di un valore
  - FuelTracker                                  : consumo medio e giri di carburante rimasti
  - tabelle di testo per stato, sessione, bandiere
  - funzioni di formattazione

ATTENZIONE: le tabelle STATUS/SESSION/FLAG vengono dalla memoria dell'SDK Kunos
(shared memory ACC). Da confrontare con i valori reali che arrivano dal server.
"""
from __future__ import annotations

import json
import math
import os
from collections import deque
from dataclasses import asdict, dataclass, fields
from pathlib import Path

# --------------------------------------------------------------------------
# Colori dei livelli
# --------------------------------------------------------------------------
LEVEL_COLORS = {
    "ok": "#2ecc71",      # nella finestra ottimale
    "warn": "#f1c40f",    # vicino ai limiti
    "crit": "#e74c3c",    # fuori limiti / alto
    "low": "#4aa3ff",     # troppo freddo / troppo basso
    "na": "#8b95a3",      # nessun dato / soglie disattivate
    "neutral": "#e6e6e6", # valore informativo senza soglie
}

STATUS_NAMES = {0: "OFF", 1: "REPLAY", 2: "LIVE", 3: "PAUSA"}
SESSION_NAMES = {
    -1: "?", 0: "PROVE", 1: "QUALIFICA", 2: "GARA", 3: "HOTLAP",
    4: "TIME ATTACK", 5: "DRIFT", 6: "DRAG", 7: "HOTSTINT", 8: "HOTLAP SUPERPOLE",
}
# flag -> (testo, sfondo, testo colore)
FLAG_NAMES = {
    0: ("", None, None),
    1: ("BLU", "#2f6fdb", "#ffffff"),
    2: ("GIALLA", "#f1c40f", "#000000"),
    3: ("NERA", "#000000", "#ffffff"),
    4: ("BIANCA", "#f2f2f2", "#000000"),
    5: ("SCACCHI", "#f2f2f2", "#000000"),
    6: ("PENALITA'", "#000000", "#e74c3c"),
    7: ("VERDE", "#27ae60", "#ffffff"),
    8: ("ARANCIO", "#e67e22", "#000000"),
}
NO_TIME = "--:--.---"
INT_MAX = 2147483647                   # ACC lo usa per "nessun tempo"
LIVE_INFER_RPM = 400                   # se status e' 0 ma i giri sono sopra, si sta guidando


# --------------------------------------------------------------------------
# Impostazioni
# --------------------------------------------------------------------------
@dataclass
class AppSettings:
    # connessione
    sim: str = "ACC"
    host: str = "127.0.0.1"
    port: int = 9999
    alive_interval: float = 10.0       # il server scollega a 30 s
    auto_connect: bool = True
    refresh_hz: int = 20
    always_on_top: bool = False
    geometry: str = ""                 # base64 di saveGeometry()

    # volante: unita' del campo steerAngle del server (da verificare con la diagnostica)
    steer_unit: str = "norm"           # "norm" (-1..+1) | "deg" | "rad"
    steer_max_deg: float = 270.0       # rotazione per lato quando |valore| = 1 (solo "norm")
    steer_invert: bool = False

    # grafici
    graph_seconds: int = 20            # ampiezza della finestra scorrevole

    # finestre ottimali (da tarare sulla vostra auto/mescola)
    p_lo: float = 26.8                 # pressione gomme PSI
    p_hi: float = 27.8
    p_margin: float = 1.0
    core_lo: float = 75.0              # temperatura core gomma
    core_hi: float = 95.0
    core_margin: float = 10.0
    surf_lo: float = 80.0              # temperatura superficie I/M/O
    surf_hi: float = 100.0
    surf_margin: float = 10.0

    # freni: 0 = soglia disattivata (nessun colore finche' non la imposti)
    pad_warn: float = 0.0
    pad_crit: float = 0.0
    disc_warn: float = 0.0
    disc_crit: float = 0.0

    # carburante: avvisi in giri rimasti
    fuel_laps_warn: float = 5.0
    fuel_laps_crit: float = 2.0

    def sanitize(self) -> "AppSettings":
        self.host = self.host.strip() or "127.0.0.1"
        self.port = min(max(int(self.port), 1), 65535)
        self.refresh_hz = min(max(int(self.refresh_hz), 5), 60)
        self.alive_interval = min(max(float(self.alive_interval), 2.0), 25.0)
        if self.steer_unit not in ("norm", "deg", "rad"):
            self.steer_unit = "norm"
        self.steer_max_deg = min(max(float(self.steer_max_deg), 30.0), 1080.0)
        self.graph_seconds = min(max(int(self.graph_seconds), 5), 120)
        return self


def settings_path() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    return Path(base) / "ACC-PitWall" / "settings.json"


def load_settings(path: str | Path | None = None) -> AppSettings:
    path = Path(path) if path else settings_path()
    cfg = AppSettings()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return cfg
    if not isinstance(raw, dict):
        return cfg
    for f in fields(AppSettings):
        if f.name not in raw:
            continue
        default = getattr(cfg, f.name)
        try:
            v = raw[f.name]
            if isinstance(default, bool):
                v = bool(v)
            elif isinstance(default, int):
                v = int(v)
            elif isinstance(default, float):
                v = float(v)
            else:
                v = str(v)
            setattr(cfg, f.name, v)
        except (TypeError, ValueError):
            pass                       # valore corrotto: resta il default
    return cfg.sanitize()


def save_settings(cfg: AppSettings, path: str | Path | None = None) -> bool:
    path = Path(path) if path else settings_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(cfg), indent=2), encoding="utf-8")
        return True
    except OSError:
        return False


# --------------------------------------------------------------------------
# Classificazione dei valori
# --------------------------------------------------------------------------
def classify_window(v: float, lo: float, hi: float, margin: float) -> str:
    """Finestra ottimale [lo, hi]; 'margin' = fascia gialla oltre i limiti."""
    if v < lo - margin:
        return "low"
    if v < lo:
        return "warn"
    if v <= hi:
        return "ok"
    if v <= hi + margin:
        return "warn"
    return "crit"


def classify_life(v: float, warn: float, crit: float) -> str:
    """Per valori che scendono (pastiglie, dischi, giri di carburante)."""
    if warn <= 0 and crit <= 0:
        return "na"                    # soglie disattivate
    if crit > 0 and v <= crit:
        return "crit"
    if warn > 0 and v <= warn:
        return "warn"
    return "ok"


# --------------------------------------------------------------------------
# Carburante: consumo medio calcolato sui giri completati
# --------------------------------------------------------------------------
class FuelTracker:
    """
    Non usa il campo fuelXLap del server (e' un int, quindi troncato): misura da
    solo quanto carburante scende tra un giro completato e il successivo.
    Scarta: il primo giro (si entra a meta'), i giri con rifornimento, i giri saltati.
    """
    MIN_LAP_USE = 0.2                  # litri: sotto questa soglia il giro non e' valido
    REFUEL_JUMP = 0.3                  # litri: un aumento oltre questo = rifornimento

    def __init__(self, window: int = 3):
        self._hist: deque[float] = deque(maxlen=window)
        self.reset()

    def reset(self) -> None:
        self._hist.clear()
        self._laps: int | None = None
        self._start = 0.0
        self._valid = False

    def update(self, laps_completed: int, fuel: float) -> None:
        if self._laps is None or laps_completed < self._laps:
            # primo campione, oppure nuova sessione (il contatore e' tornato indietro)
            self._hist.clear()
            self._laps, self._start, self._valid = laps_completed, fuel, False
            return
        if laps_completed == self._laps and fuel > self._start + self.REFUEL_JUMP:
            self._valid = False        # rifornimento durante il giro
        if laps_completed > self._laps:
            used = self._start - fuel
            if laps_completed == self._laps + 1 and self._valid and used >= self.MIN_LAP_USE:
                self._hist.append(used)
            self._laps, self._start, self._valid = laps_completed, fuel, True

    @property
    def avg_per_lap(self) -> float | None:
        return sum(self._hist) / len(self._hist) if self._hist else None

    def laps_left(self, fuel: float) -> float | None:
        avg = self.avg_per_lap
        return fuel / avg if avg else None


# --------------------------------------------------------------------------
# Formattazione
# --------------------------------------------------------------------------
def steer_to_degrees(value: float, unit: str, max_deg: float, invert: bool = False) -> float:
    """Converte steerAngle in gradi (positivo = destra, salvo 'invert')."""
    if unit == "rad":
        deg = math.degrees(value)
    elif unit == "deg":
        deg = value
    else:                                  # normalizzato -1..+1
        deg = max(-1.0, min(1.0, value)) * max_deg
    return -deg if invert else deg


def steer_out_of_range(value: float, unit: str) -> bool:
    """In modalita' normalizzata il valore deve stare in -1..+1: se no, l'unita' e' un'altra."""
    return unit == "norm" and abs(value) > 1.05


def thin_samples(samples: list, max_points: int) -> list:
    """
    Riduce i campioni (t, valore, flag) a circa max_points senza perdere gli eventi:
    i campioni con flag attivo e quelli ai bordi di un cambio di flag restano tutti,
    cosi' un intervento breve di TC/ABS non sparisce dal grafico.
    """
    n = len(samples)
    if max_points <= 0 or n <= max_points:
        return samples
    step = -(-n // max_points)                     # divisione per eccesso
    out = []
    for i, smp in enumerate(samples):
        f = smp[2]
        if (i % step == 0 or i == n - 1 or f
                or f != samples[i - 1][2] or (i + 1 < n and f != samples[i + 1][2])):
            out.append(smp)
    return out


def gear_name(gear: int) -> str:
    """Convenzione del server: -1 = R, 0 = N, 1.. = marce."""
    return "R" if gear < 0 else "N" if gear == 0 else str(gear)


def gear_steps(samples: list) -> list:
    """
    Da [(t, marcia), ...] a punti (t, marcia, 0) per un grafico A GRADINI: a ogni cambio
    si inserisce prima il punto con la marcia vecchia e poi quello con la nuova allo
    stesso istante, cosi' il passaggio e' verticale. Tiene solo i cambi (pochi punti).
    """
    out: list = []
    last = None
    for t, g in samples:
        if last is None:
            out.append((t, g, 0))
        elif g != last:
            out.append((t, last, 0))
            out.append((t, g, 0))
        last = g
    if samples and out[-1][0] != samples[-1][0]:
        out.append((samples[-1][0], last, 0))          # prolunga fino all'ultimo campione
    return out


def fmt_ms(ms: int) -> str:
    m, rem = divmod(int(ms), 60000)
    s, milli = divmod(rem, 1000)
    return f"{m}:{s:02d}.{milli:03d}"


def fmt_lap(text: str, ms: int) -> str:
    """
    Preferisce i millisecondi (interi, affidabili) alla stringa, che il server potrebbe
    non valorizzare. ACC usa 2147483647 ms / '35791:23.647' come 'nessun tempo'.
    """
    if ms == INT_MAX:
        return NO_TIME
    if ms > 0:
        return fmt_ms(ms)
    if text and not text.startswith("35791"):
        return text
    return NO_TIME


def status_name(code: int) -> str:
    return STATUS_NAMES.get(code, f"? ({code})")


def session_name(code: int) -> str:
    return SESSION_NAMES.get(code, f"? ({code})")


def is_live(status: int, rpm: int) -> bool:
    """LIVE, oppure status non valorizzato (0) ma motore in moto: si sta guidando."""
    return status == 2 or (status == 0 and rpm >= LIVE_INFER_RPM)


def fmt_clock_ms(ms: float) -> str:
    """Tempo di sessione rimasto. ATTENZIONE: si assume che arrivi in millisecondi."""
    if ms is None or ms <= 0:
        return "--:--:--"
    total = int(ms // 1000)
    return f"{total // 3600}:{total % 3600 // 60:02d}:{total % 60:02d}"
