"""
Client Python per ACC-TX-UDP (https://github.com/gabbo76/ACC-TX-UDP)

Contiene:
  - RawPacket   : mappa 1:1 della struct _packet del server (508 byte)
  - CarState    : modello dati "neutro", immutabile (la GUI parla solo con questo)
  - ACCAdapter  : traduce RawPacket -> CarState (un adapter per ogni sim)
  - TelemetryModel  : ultimo stato + stato connessione, thread-safe
  - TelemetryClient : thread con START / ALIVE / STOP, riconnessione e watchdog

Ordine delle ruote negli array: 0=FL, 1=FR, 2=RL, 3=RR (convenzione ACC).

Uso rapido (test da console):
    python acc_tx_client.py --host 127.0.0.1 --port 9999
"""
from __future__ import annotations

import argparse
import ctypes
import socket
import threading
import time
from collections import deque
from dataclasses import dataclass, field

# --------------------------------------------------------------------------
# 1. Layout binario del pacchetto
# --------------------------------------------------------------------------
F = ctypes.c_float
I = ctypes.c_int32
F3, F4 = F * 3, F * 4
WSTR = ctypes.c_uint16 * 15        # wchar_t[15] su Windows = UTF-16LE (non usare c_char:
                                   # si fermerebbe al primo byte nullo)


class RawPacket(ctypes.Structure):
    _pack_ = 4
    _fields_ = [
        ("gas", F), ("brake", F), ("fuel", F),
        ("gear", I), ("rpm", I),
        ("steerAngle", F), ("speedKmh", F),
        ("accG", F3),
        ("wheelSlip", F4), ("wheelLoad", F4), ("wheelsPressure", F4),
        ("wheelAngularSpeed", F4), ("tyreWear", F4), ("tyreDirtyLevel", F4),
        ("tyreCoreTemperature", F4), ("camberRAD", F4), ("suspensionTravel", F4),
        ("tyreTempI", F4), ("tyreTempM", F4), ("tyreTempO", F4),
        ("brakeBias", F), ("tcinAction", I), ("absInAction", I),
        ("suspensionDamage", F4), ("tyreTemp", F4), ("waterTemp", F),
        ("brakePressure", F4),
        ("frontBrakeCompound", I), ("rearBrakeCompound", I),
        ("padLife", F4), ("discLife", F4),
        ("ignitionOn", I), ("starterEngineOn", I), ("isEngineRunning", I),
        ("status", I), ("session", I),
        ("currentTime", WSTR), ("lastTime", WSTR),
        ("bestTime", WSTR), ("split", WSTR),
        ("completedLaps", I), ("position", I),
        ("iCurrentTime", I), ("iLastTime", I), ("iBestTime", I),
        ("sessionTimeLeft", F), ("flag", I), ("fuelXLap", I),
    ]


PACKET_SIZE = ctypes.sizeof(RawPacket)
# Controllo di sanita': se il server viene ricompilato con un layout diverso
# questo numero deve coincidere con sizeof(_packet) lato C++.
assert PACKET_SIZE == 508, f"layout inatteso: {PACKET_SIZE} byte"


def _wstr(arr) -> str:
    out = []
    for ch in arr:
        if ch == 0:
            break
        out.append(chr(ch))
    return "".join(out)


def flatten_raw(r: "RawPacket") -> dict:
    """Appiattisce il pacchetto in {nome: valore}; gli array diventano nome[i]."""
    out: dict = {}
    for name, ctype in RawPacket._fields_:
        v = getattr(r, name)
        if ctype is WSTR:
            out[name] = _wstr(v)
        elif isinstance(v, ctypes.Array):
            for i, x in enumerate(v):
                out[f"{name}[{i}]"] = x
        else:
            out[name] = v
    return out


class FieldStats:
    """
    Per ogni campo del pacchetto: ultimo valore, min, max e quante volte e' stato
    diverso da zero. Serve a capire quali campi il server riempie davvero.
    Aggiornata a ogni pacchetto (non a ogni refresh della GUI), cosi' non perde
    eventi brevi come un intervento del TC.
    """

    def __init__(self):
        self._d: dict[str, list] = {}      # nome -> [ultimo, min, max, n_non_zero, n]

    def update(self, flat: dict) -> None:
        for k, v in flat.items():
            if isinstance(v, float) and v != v:        # NaN: ignorato
                continue
            e = self._d.get(k)
            if e is None:
                lim = None if isinstance(v, str) else v
                self._d[k] = [v, lim, lim, 1 if v else 0, 1]
                continue
            e[0] = v
            if e[1] is not None:
                if v < e[1]:
                    e[1] = v
                if v > e[2]:
                    e[2] = v
            if v:
                e[3] += 1
            e[4] += 1

    def snapshot(self) -> dict:
        return {k: tuple(e) for k, e in self._d.items()}

    @staticmethod
    def never_nonzero_groups(snap: dict) -> list:
        """Nomi dei campi (array raggruppati) che non sono MAI stati diversi da zero."""
        seen: dict[str, bool] = {}
        for k, (_last, _mn, _mx, nz, _n) in snap.items():
            g = k.split("[", 1)[0]
            seen[g] = seen.get(g, False) or nz > 0
        return [g for g, any_nz in seen.items() if not any_nz]


# --------------------------------------------------------------------------
# 2. Modello dati neutro (indipendente dal simulatore)
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class CarState:
    rx_time: float                       # time.monotonic() alla ricezione

    # pilota / auto
    speed_kmh: float = 0.0
    gear: int = 0                        # come lo manda il server: -1=R, 0=N, 1=1a ...
    rpm: int = 0
    throttle: float = 0.0
    brake: float = 0.0
    steer_angle: float = 0.0
    g_force: tuple = (0.0, 0.0, 0.0)
    fuel: float = 0.0
    fuel_per_lap: float = 0.0            # ATTENZIONE: int nel server (troncato)
    water_temp: float = 0.0
    engine_running: bool = False
    tc_active: bool = False
    abs_active: bool = False
    brake_bias: float = 0.0

    # gomme [FL, FR, RL, RR]
    tyre_pressure: tuple = (0.0,) * 4
    tyre_core_temp: tuple = (0.0,) * 4
    tyre_temp_inner: tuple = (0.0,) * 4
    tyre_temp_middle: tuple = (0.0,) * 4
    tyre_temp_outer: tuple = (0.0,) * 4
    tyre_temp_surface: tuple = (0.0,) * 4
    tyre_wear: tuple = (0.0,) * 4
    tyre_dirt: tuple = (0.0,) * 4
    tyre_slip: tuple = (0.0,) * 4
    tyre_load: tuple = (0.0,) * 4
    camber_rad: tuple = (0.0,) * 4
    susp_travel: tuple = (0.0,) * 4
    susp_damage: tuple = (0.0,) * 4

    # freni [FL, FR, RL, RR]
    brake_pressure: tuple = (0.0,) * 4
    pad_life: tuple = (0.0,) * 4
    disc_life: tuple = (0.0,) * 4
    front_pad_compound: int = 0
    rear_pad_compound: int = 0

    # sessione
    status: int = 0                      # ACC: 0 OFF, 1 REPLAY, 2 LIVE, 3 PAUSE
    session: int = 0                     # ACC: 0 prove, 1 qualifica, 2 gara...
    flag: int = 0
    laps_completed: int = 0
    position: int = 0
    session_time_left: float = 0.0
    time_current: str = ""
    time_last: str = ""
    time_best: str = ""
    split: str = ""
    ms_current: int = 0
    ms_last: int = 0
    ms_best: int = 0

    @property
    def gear_label(self) -> str:
        return "R" if self.gear < 0 else "N" if self.gear == 0 else str(self.gear)


# --------------------------------------------------------------------------
# 3. Adapter: un adapter per simulatore. Gli altri sim ne avranno uno loro.
# --------------------------------------------------------------------------
class ACCAdapter:
    sim_name = "ACC"

    @staticmethod
    def parse(data: bytes) -> CarState:
        if len(data) != PACKET_SIZE:
            raise ValueError(f"pacchetto di {len(data)} byte, attesi {PACKET_SIZE}")
        r = RawPacket.from_buffer_copy(data)
        t = tuple
        return CarState(
            rx_time=time.monotonic(),
            speed_kmh=r.speedKmh, gear=r.gear, rpm=r.rpm,
            throttle=r.gas, brake=r.brake, steer_angle=r.steerAngle,
            g_force=t(r.accG), fuel=r.fuel, fuel_per_lap=float(r.fuelXLap),
            water_temp=r.waterTemp, engine_running=bool(r.isEngineRunning),
            tc_active=bool(r.tcinAction), abs_active=bool(r.absInAction),
            brake_bias=r.brakeBias,
            tyre_pressure=t(r.wheelsPressure), tyre_core_temp=t(r.tyreCoreTemperature),
            tyre_temp_inner=t(r.tyreTempI), tyre_temp_middle=t(r.tyreTempM),
            tyre_temp_outer=t(r.tyreTempO), tyre_temp_surface=t(r.tyreTemp),
            tyre_wear=t(r.tyreWear), tyre_dirt=t(r.tyreDirtyLevel),
            tyre_slip=t(r.wheelSlip), tyre_load=t(r.wheelLoad),
            camber_rad=t(r.camberRAD), susp_travel=t(r.suspensionTravel),
            susp_damage=t(r.suspensionDamage),
            brake_pressure=t(r.brakePressure), pad_life=t(r.padLife),
            disc_life=t(r.discLife),
            front_pad_compound=r.frontBrakeCompound, rear_pad_compound=r.rearBrakeCompound,
            status=r.status, session=r.session, flag=r.flag,
            laps_completed=r.completedLaps, position=r.position,
            session_time_left=r.sessionTimeLeft,
            time_current=_wstr(r.currentTime), time_last=_wstr(r.lastTime),
            time_best=_wstr(r.bestTime), split=_wstr(r.split),
            ms_current=r.iCurrentTime, ms_last=r.iLastTime, ms_best=r.iBestTime,
        )

    @staticmethod
    def flatten(data: bytes) -> dict:
        return flatten_raw(RawPacket.from_buffer_copy(data))


# --------------------------------------------------------------------------
# 4. Modello condiviso tra thread di rete e GUI
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Snapshot:
    state: CarState | None
    connected: bool
    age: float            # secondi dall'ultimo pacchetto valido (inf se mai)
    rate_hz: float        # pacchetti/s misurati
    bad_packets: int


class TelemetryModel:
    """Scrive solo il thread di rete, legge la GUI tramite snapshot()."""

    def __init__(self, silence_timeout: float = 3.0):
        self._lock = threading.Lock()
        self._state: CarState | None = None
        self._bad = 0
        self._count = 0
        self._rate = 0.0
        self._rate_t0 = time.monotonic()
        self.silence_timeout = silence_timeout
        self._stats = FieldStats()
        # cronologia per i grafici: (t, gas, freno, sterzo, tc, abs, marcia), a ogni pacchetto
        self._hist: deque = deque(maxlen=15000)

    def push(self, state: CarState) -> None:
        with self._lock:
            self._state = state          # CarState e' immutabile: niente copie
            self._hist.append((state.rx_time, state.throttle, state.brake, state.steer_angle,
                               state.tc_active, state.abs_active, state.gear))
            self._count += 1
            now = state.rx_time
            if now - self._rate_t0 >= 1.0:
                self._rate = self._count / (now - self._rate_t0)
                self._count, self._rate_t0 = 0, now

    def history(self, seconds: float) -> list:
        """Campioni degli ultimi 'seconds' secondi, dal piu' vecchio al piu' recente."""
        t0 = time.monotonic() - seconds
        out = []
        with self._lock:
            for item in reversed(self._hist):
                if item[0] < t0:
                    break
                out.append(item)
        out.reverse()
        return out

    def record(self, flat: dict) -> None:
        with self._lock:
            self._stats.update(flat)

    def stats_snapshot(self) -> dict:
        with self._lock:
            return self._stats.snapshot()

    def stats_reset(self) -> None:
        with self._lock:
            self._stats = FieldStats()

    def push_bad(self) -> None:
        with self._lock:
            self._bad += 1

    def snapshot(self) -> Snapshot:
        with self._lock:
            s, bad, rate = self._state, self._bad, self._rate
        age = time.monotonic() - s.rx_time if s else float("inf")
        return Snapshot(s, age < self.silence_timeout, age,
                        rate if age < self.silence_timeout else 0.0, bad)


# --------------------------------------------------------------------------
# 5. Client UDP: START / ALIVE / STOP su UN SOLO socket
# --------------------------------------------------------------------------
class TelemetryClient(threading.Thread):
    def __init__(self, host: str, port: int, model: TelemetryModel,
                 adapter=ACCAdapter, alive_interval: float = 10.0,
                 restart_after: float = 5.0, on_sample=None):
        super().__init__(daemon=True, name="telemetry-rx")
        self.server = (host, port)
        self.model = model
        self.adapter = adapter
        self.alive_interval = alive_interval     # il server scollega a 30 s
        self.restart_after = restart_after       # silenzio dopo cui rimanda START
        self.on_sample = on_sample               # es. logger.queue.put
        self._stop_evt = threading.Event()

    def stop(self) -> None:
        self._stop_evt.set()

    def _send(self, sock: socket.socket, msg: bytes) -> None:
        try:
            sock.sendto(msg, self.server)
        except OSError:
            pass

    def run(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(0.25)
        self._send(sock, b"START")
        now = time.monotonic()
        last_alive = last_rx = last_start = now

        while not self._stop_evt.is_set():
            now = time.monotonic()
            if now - last_alive >= self.alive_interval:
                self._send(sock, b"ALIVE")
                last_alive = now
            # server riavviato / sim chiuso: ci ha dimenticati, ri-registrati
            if now - last_rx >= self.restart_after and now - last_start >= 2.0:
                self._send(sock, b"START")
                last_start = now

            try:
                data, _ = sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                # Windows: ICMP "port unreachable" -> ConnectionResetError (10054)
                time.sleep(0.2)
                continue

            try:
                state = self.adapter.parse(data)
            except ValueError:
                self.model.push_bad()
                continue
            last_rx = time.monotonic()
            self.model.push(state)
            flatten = getattr(self.adapter, "flatten", None)
            if flatten:
                self.model.record(flatten(data))
            if self.on_sample:
                self.on_sample(state)

        self._send(sock, b"STOP")
        sock.close()


# --------------------------------------------------------------------------
# 6. Demo da console
# --------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=9999)
    args = ap.parse_args()

    model = TelemetryModel()
    client = TelemetryClient(args.host, args.port, model)
    client.start()
    try:
        while True:                      # qui in futuro ci sara' il timer della GUI
            snap = model.snapshot()
            if not snap.connected:
                print("NO SIGNAL (in attesa del server...)")
            else:
                s = snap.state
                print(f"{snap.rate_hz:4.0f} Hz | {s.speed_kmh:5.1f} km/h | "
                      f"marcia {s.gear_label} | fuel {s.fuel:5.1f} | "
                      f"P gomme {[round(p, 1) for p in s.tyre_pressure]} | "
                      f"pad {[round(p, 1) for p in s.pad_life]} | "
                      f"giro {s.time_current} ultimo {s.time_last}")
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        client.stop()
        client.join(timeout=2)


if __name__ == "__main__":
    main()
