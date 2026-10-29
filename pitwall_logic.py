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
from bisect import bisect_right
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
    settings_version: int = 2          # per migrare i file salvati da versioni precedenti

    # volante: unita' del campo steerAngle del server (da verificare con la diagnostica)
    steer_unit: str = "norm"           # "norm" (-1..+1) | "deg" | "rad"
    steer_max_deg: float = 270.0       # rotazione per lato quando |valore| = 1 (solo "norm")
    steer_invert: bool = False

    # grafici
    graph_seconds: int = 20            # ampiezza della finestra scorrevole

    # sospensioni: unita' del campo suspensionTravel (da verificare con la diagnostica)
    susp_unit: str = "auto"            # "auto" | "m" | "cm" | "mm"
    susp_range_mm: float = 0.0         # corsa totale: 0 = automatica (min/max osservati)
    susp_invert: bool = False          # se nel sim il valore cresce quando la sospensione si estende

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
        self.graph_seconds = min(max(int(self.graph_seconds), 2), 120)
        if self.susp_unit not in ("auto", "m", "cm", "mm"):
            self.susp_unit = "auto"
        self.susp_range_mm = min(max(float(self.susp_range_mm), 0.0), 500.0)
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
    try:
        file_version = int(raw.get("settings_version", 1))
    except (TypeError, ValueError):
        file_version = 1
    if file_version < 2:                   # prima l'unita' delle sospensioni non era mai stata scelta
        cfg.susp_unit = "auto"
    cfg.settings_version = 2
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


def travel_to_mm(value: float, unit: str) -> float:
    return value * {"m": 1000.0, "cm": 10.0, "mm": 1.0}.get(unit, 1000.0)


def resolve_susp_unit(unit: str, raw: list, seen_big: bool) -> tuple:
    """
    'auto': se qualche valore grezzo e' >= 1 non possono essere metri (una sospensione non
    ha 1 m di corsa), quindi sono millimetri; altrimenti si assumono metri (valori ~0.05).
    Una volta visto un valore grande si resta su millimetri.
    """
    if unit != "auto":
        return unit, seen_big
    if not seen_big and any(abs(v) >= 1.0 for v in raw):
        seen_big = True
    return ("mm" if seen_big else "m"), seen_big


class TravelTracker:
    """
    Posizione normalizzata delle 4 sospensioni: 0 = estesa, 1 = compressa a fondo corsa.
    Con corsa totale nota (fixed_range_mm > 0) si usa quella; altrimenti il minimo e il
    massimo osservati dal momento dell'azzeramento (la scala si adatta guidando).
    """
    MIN_SPAN_MM = 5.0

    def __init__(self, n: int = 4):
        self.n = n
        self.reset()

    def reset(self) -> None:
        self.lo: list = [None] * self.n
        self.hi: list = [None] * self.n

    def update(self, mm: list) -> None:
        for i, v in enumerate(mm):
            if self.lo[i] is None:
                self.lo[i] = self.hi[i] = v
            else:
                self.lo[i] = min(self.lo[i], v)
                self.hi[i] = max(self.hi[i], v)

    def norm(self, i: int, mm: float, fixed_range_mm: float = 0.0, invert: bool = False) -> float:
        if fixed_range_mm > 0:
            c = mm / fixed_range_mm
        else:
            lo, hi = self.lo[i], self.hi[i]
            if lo is None or hi - lo < 0.5:        # ancora nessuna escursione: posizione centrale
                return 0.5
            c = (mm - lo) / max(hi - lo, self.MIN_SPAN_MM)
        c = min(max(c, 0.0), 1.0)
        return 1.0 - c if invert else c


class Chunk:
    """Blocco di punti consecutivi con lo stesso flag. 'path' e 'fill' li riempie la grafica."""
    __slots__ = ("flag", "pts", "t1", "path", "fill", "dirty")

    def __init__(self, flag: int):
        self.flag = flag
        self.pts: list = []
        self.t1 = 0.0
        self.path = None
        self.fill = None
        self.dirty = True


class ChunkedSeries:
    """
    Serie temporale per i grafici scorrevoli, a blocchi di ~1 s.

    Perche': ridisegnare un grafico ricostruendo tutti i punti a ogni scatto costa molto.
    Qui si aggiungono solo i campioni nuovi; i blocchi gia' chiusi non cambiano piu' e la
    grafica li conserva (path gia' pronto), si ricostruisce solo il blocco in corso.
    Un blocco ha un solo 'flag' (es. TC attivo): cambiando flag ne parte uno nuovo, che
    inizia dall'ultimo punto del precedente cosi' la linea non ha buchi.
    I tratti piatti (valore invariato) vengono compressi: si allunga l'ultimo punto.
    """

    def __init__(self, chunk_s: float = 1.0, keep_s: float = 65.0):
        self.chunk_s = chunk_s
        self.keep_s = keep_s
        self.chunks: deque = deque()
        self.t0: float | None = None           # origine dei tempi: tiene piccoli i numeri nei path
        self.last_t: float | None = None

    def clear(self) -> None:
        self.chunks.clear()
        self.t0 = None
        self.last_t = None

    def add(self, t: float, v: float, flag: int = 0) -> None:
        if self.t0 is None:
            self.t0 = t
        ch = self.chunks[-1] if self.chunks else None
        if ch is None or ch.flag != flag or t - ch.pts[0][0] >= self.chunk_s:
            new = Chunk(flag)
            if ch is not None:
                new.pts.append(ch.pts[-1])             # raccordo col blocco precedente
            self.chunks.append(new)
            ch = new
        pts = ch.pts
        if len(pts) >= 2 and pts[-1][1] == v and pts[-2][1] == v:
            pts[-1] = (t, v)                           # tratto piatto: allungo l'ultimo punto
        else:
            pts.append((t, v))
        ch.t1 = t
        ch.dirty = True
        self.last_t = t
        t_min = t - self.keep_s
        while len(self.chunks) > 1 and self.chunks[0].t1 < t_min:
            self.chunks.popleft()

    def visible(self, t_min: float) -> list:
        return [c for c in self.chunks if c.t1 >= t_min]

    def value_at(self, t: float, hold: bool = False) -> float | None:
        """Valore all'istante t (interpolato, oppure l'ultimo noto se hold=True: per le marce)."""
        if self.last_t is None or t > self.last_t + 0.25:
            return None
        for ch in reversed(self.chunks):
            pts = ch.pts
            if pts[0][0] <= t:
                i = bisect_right([p[0] for p in pts], t) - 1
                if i < 0:
                    continue
                if hold or i == len(pts) - 1:
                    return pts[i][1]
                (ta, va), (tb, vb) = pts[i], pts[i + 1]
                return vb if tb == ta else va + (vb - va) * (t - ta) / (tb - ta)
        return None


class BrakeTracker:
    """Usura di pastiglie e dischi dall'inizio della sessione + scala per la pressione freno."""

    def __init__(self, n: int = 4):
        self.n = n
        self.reset()

    def reset(self) -> None:
        self.pad0: list = [None] * self.n          # spessore al primo campione valido
        self.disc0: list = [None] * self.n
        self.press_max = 0.0

    def update(self, pads: list, discs: list, press: list) -> None:
        for i in range(self.n):
            if self.pad0[i] is None and pads[i] > 0:
                self.pad0[i] = pads[i]
            if self.disc0[i] is None and discs[i] > 0:
                self.disc0[i] = discs[i]
        self.press_max = max(self.press_max, max(press))

    def pad_used(self, i: int, now: float) -> float | None:
        return None if self.pad0[i] is None else max(0.0, self.pad0[i] - now)

    def disc_used(self, i: int, now: float) -> float | None:
        return None if self.disc0[i] is None else max(0.0, self.disc0[i] - now)

    def press_norm(self, v: float) -> float:
        return min(max(v / self.press_max, 0.0), 1.0) if self.press_max > 0 else 0.0


def gear_name(gear: int) -> str:
    """Convenzione del server: -1 = R, 0 = N, 1.. = marce."""
    return "R" if gear < 0 else "N" if gear == 0 else str(gear)


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
