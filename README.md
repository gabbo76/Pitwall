# 🏁 ACC Pit Wall — Desktop Telemetry & Strategy Suite

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)
![PySide6](https://img.shields.io/badge/GUI-PySide6_(Qt6)-41CD52?style=for-the-badge&logo=qt&logoColor=white)
![Protocol](https://img.shields.io/badge/Protocol-ACC--TX--UDP-E10600?style=for-the-badge)
![License](https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge)

**ACC Pit Wall** è un'applicazione desktop per il muretto box sviluppata in Python e basata su **PySide6 (Qt)**[cite: 1], progettata per ricevere, analizzare e visualizzare in tempo reale i flussi telemetrici provenienti dal server **[ACC-TX-UDP](https://github.com/gabbo76/ACC-TX-UDP)** per *Assetto Corsa Competizione*[cite: 1, 2].

L'architettura separa nettamente il livello di rete/parsing binario, la logica matematica/strategica e il rendering grafico, garantendo un'interfaccia ad alto contrasto fluida (20–60 Hz), thread-safe e pronta sia per l'uso su monitor secondario che da postazione remota (Ingegnere di Pista via LAN/WAN)[cite: 1, 2, 3].

---

## 📋 Indice
1. [Guida all'Applicazione (Le 3 Schermate e gli Strumenti)](#-guida-allapplicazione-le-3-schermate-e-gli-strumenti)
2. [Architettura del Codice](#-architettura-del-codice)
3. [Installazione e Avvio](#-installazione-e-avvio)
4. [Scorciatoie da Tastiera](#-scorciatoie-da-tastiera)

---

## 🖥️ Guida all'Applicazione (Le 3 Schermate e gli Strumenti)

L'interfaccia (in tema scuro nativo QSS ad alta leggibilità) presenta una **Header Bar** fissa in alto e un corpo centrale diviso in **3 schede principali**, più due finestre di dialogo dedicate a configurazione e diagnostica[cite: 1]. Quando il segnale cade o si è disconnessi, il pannello centrale riduce automaticamente l'opacità (`35%`) per segnalare visivamente che i dati a schermo sono *stale* (congelati)[cite: 1].

### 📊 Barra Superiore (Header Panel)
Sempre visibile in ogni scheda, riassume lo stato vitale della sessione[cite: 1]:
* **Stato & Sessione:** Indica se il simulatore è `LIVE`, `OFF`, `REPLAY`, `PAUSA` (con deduzione automatica `LIVE*` se il flag del server resta a `0` ma i giri motore superano i `400 RPM`) e il tipo di sessione (`PROVE`, `QUALIFICA`, `GARA`, `HOTLAP`, ecc.)[cite: 1, 3].
* **Bandiere (Flag Badge):** Indicatore dinamico colorato per le bandiere in pista (`VERDE`, `GIALLA`, `BLU`, `BIANCA`, `NERA`, `SCACCHI`, `PENALITÀ`, `ARANCIO`)[cite: 1, 3].
* **Timing & Posizione:** Posizione attuale (`P1`, `P2`...), giri completati, tempo giro **Attuale**, **Ultimo**, **Migliore** e conto alla rovescia del tempo di sessione rimasto (`HH:MM:SS`)[cite: 1, 3].
* **Strategia Carburante:** Litri nel serbatoio (`FUEL L`), consumo medio reale calcolato sugli ultimi giri puliti (`L / GIRO`) e autonomia residua stimata (`GIRI FUEL`), con colorazione dinamica di avviso/emergenza[cite: 1, 3].

---

### 1️⃣ Scheda "Muretto" (`Ctrl+1`)
La vista principale per pilota e ingegnere di pista, divisa in due sezioni[cite: 1]:
* **Griglia Ruote (4x `TyreCard` — Ant. SX/DX, Post. SX/DX)[cite: 1]:**
  * **Pressione (PSI) e Temperatura Core (°C):** Valori ad alta visibilità colorati dinamicamente in base alla finestra ottimale impostata: **Blu** (`low`, troppo freddo/sgonfio), **Verde** (`ok`, in finestra), **Giallo** (`warn`, nel margine di tolleranza), **Rosso** (`crit`, fuori limite massimo)[cite: 1, 3].
  * **Temperature Superficie e Battistrada (I / C / E):** Lettura di superficie e ripartizione Interna, Centrale ed Esterna (mostra `n/d` se il server non valorizza il campo)[cite: 1].
  * **Usura e Freni:** Stato usura gomma e spessore residuo in millimetri di **Pastiglie (`pad_life`)** e **Dischi (`disc_life`)**, con soglie di allarme giallo/rosso personalizzabili[cite: 1, 3].
* **Colonna Vettura (`CarPanel`)[cite: 1]:**
  * Indicatore gigante della **Marcia** (`R`, `N`, `1`..`6+`), **Velocità (km/h)** e **RPM**[cite: 1, 2].
  * Barre progressive per **Acceleratore** (verde) e **Freno** (rosso)[cite: 1].
  * Valori di **Brake Bias (%)**, **Temperatura Acqua (°C)**, spie di intervento in tempo reale per **TC** e **ABS**, e stato **Motore (`ON`/`OFF`)**[cite: 1].
  * **Volante Vettoriale (`SteeringWheel`):** Disegno custom in `QPainter` che ruota in tempo reale seguendo l'angolo di sterzo, affiancato dal valore in gradi (`+`/`-`), dal valore grezzo ricevuto e da un avviso automatico `STERZO (FUORI SCALA)` se l'unità configurata non coincide con quella inviata dal server[cite: 1, 3].

---

### 2️⃣ Scheda "Grafici" (`Ctrl+2`)
Telemetria scorrevole nel tempo (`TraceWidget`) per l'analisi della guida in tempo reale[cite: 1]:
* **4 Tracce Sincronizzate[cite: 1]:**
  1. **Acceleratore (0–100%):** Traccia con area riempita; **cambia colore da Verde ad Arancione** esattamente nei tratti in cui interviene il **TC** (Traction Control)[cite: 1].
  2. **Freno (0–100%):** Traccia con area riempita; **cambia colore da Rosso ad Azzurro** nei tratti in cui entra in funzione l'**ABS**[cite: 1].
  3. **Sterzo (°):** Grafico dell'angolo volante con scala adattiva rispetto ai gradi massimi impostati[cite: 1].
  4. **Marcia (`R`, `N`, `1`..):** Grafico **a gradini verticali** (`gear_steps`) che adatta automaticamente il fondo scala se l'auto utilizza la 7ª marcia[cite: 1, 3].
* **Controlli Live:** Selettore della finestra temporale (`10 s`, `20 s`, `30 s`, `60 s`) e casella **Pausa grafici** per congelare le tracce ed esaminare una staccata o una percorrenza curva[cite: 1].

---

### 3️⃣ Scheda "Sospensioni" (`Ctrl+3`)
Visualizzazione meccanica ed escursione delle 4 sospensioni (`SuspensionPage`)[cite: 1]:
* **Animazione Cinematica McPherson (`SuspensionWidget`):** Ogni angolo dell'auto mostra una sospensione disegnata in grafica vettoriale (ruota, mozzo, montante, braccio oscillante inferiore, ammortizzatore con stelo/cilindro, molla a zig-zag e scocca)[cite: 1].
  * Quando la sospensione si comprime, la scocca scende, il braccio inferiore si raddrizza, lo stelo entra nel cilindro e la molla si schiaccia cambiando colore (**Verde** -> **Giallo** oltre il 75% -> **Rosso** oltre il 90% vicino al fondo corsa / bumpstop)[cite: 1].
  * Le ruote destre sono specchiate automaticamente affinché il blocco telaio sia sempre rivolto verso il centro della vettura[cite: 1].
* **Rilevamento Unità e Auto-Scaling:** Rileva in automatico se il server invia `suspensionTravel` in metri o millimetri, calcola la corsa in `mm` e mostra la percentuale di eventuale **Danno Sospensione (`OK` / `%`)**[cite: 1, 3]. Include il pulsante **Azzera range** per ricalibrare i minimi e massimi osservati[cite: 1].

---

### 🔍 Finestra "Diagnostica Pacchetto" (`Ctrl+D`)
Uno strumento di ispezione non modale (può restare aperto mentre si guida) che analizza i **508 byte** ricevuti a livello di singolo campo[cite: 1, 2]:
* Mostra una tabella con tutti i campi della struct (espandendo gli array `nome[0..3]`), indicando **Valore Attuale**, **Minimo**, **Massimo** e **Percentuale di campioni `≠ 0`**[cite: 1, 2].
* Evidenzia in giallo ambra i campi che non sono **mai stati diversi da zero** dall'inizio della connessione (per capire subito quali dati la memoria condivisa/server non sta popolando)[cite: 1, 2].
* Offre un filtro rapido *"Mostra solo i campi mai diversi da zero"*, il reset delle statistiche e il tasto **Copia report** per esportare il report negli appunti[cite: 1].

---

### ⚙️ Finestra "Impostazioni" (`Ctrl+,`)
Organizzata in 4 tab con salvataggio automatico in `%APPDATA%\ACC-PitWall\settings.json` (o `~/.config/ACC-PitWall/settings.json` su Linux)[cite: 1, 3]:
1. **Connessione:** Scelta simulatore, IP/Hostname del server `ACC-TX-UDP`, porta UDP (default `9999`), intervallo pacchetti `ALIVE` (2–25 s), frequenza di aggiornamento GUI (5–60 Hz) e connessione automatica all'avvio[cite: 1, 3].
2. **Soglie e Colori:** Personalizzazione completa di minimi, massimi e margini gialli per Pressioni gomme (PSI), Temperatura Core (°C), Temperatura Superficie I/C/E (°C), spessore Pastiglie e Dischi (mm) e giri di Carburante residui[cite: 1, 3].
3. **Volante:** Unità di `steerAngle` (`Normalizzato -1..+1`, `Gradi`, `Radianti`), gradi di rotazione per lato (es. `270°`) e inversione senso di rotazione[cite: 1, 3].
4. **Sospensioni:** Unità di `suspensionTravel` (`Automatico`, `m`, `cm`, `mm`), corsa totale fissa o auto-adattiva (`0 mm` = auto) e inversione del verso di compressione[cite: 1, 3].

---

## 🛠️ Architettura del Codice

Il progetto è suddiviso in **3 moduli Python** con responsabilità rigorosamente isolate[cite: 1, 2, 3]:

| Modulo | Ruolo Principale | Componenti Chiave |
| :--- | :--- | :--- |
| **`acc_tx_client.py`** | Rete UDP, Parsing Binario (508 B) e Modello Thread-Safe[cite: 2] | `RawPacket`, `CarState`, `ACCAdapter`, `FieldStats`, `TelemetryModel`, `TelemetryClient`[cite: 2] |
| **`pitwall_logic.py`** | Logica di Dominio, Calcoli Strategici e Persistenza (Zero Qt)[cite: 3] | `AppSettings`, `FuelTracker`, `TravelTracker`, `classify_window`, `thin_samples`, `gear_steps`[cite: 3] |
| **`acc_pitwall.py`** | Interfaccia Utente PySide6 (Qt6) e Rendering Vettoriale[cite: 1] | `MainWindow`, `HeaderPanel`, `TyreCard`, `CarPanel`, `GraphPage`, `SuspensionPage`, `DiagnosticsDialog`[cite: 1] |

### 1. `acc_tx_client.py` — Rete, Protocollo Binario e Modello Thread-Safe
Gestisce la comunicazione socket UDP e la deserializzazione a basso livello[cite: 2]. Può anche essere eseguito da solo in modalità console per testare la ricezione (`python acc_tx_client.py --host 127.0.0.1 --port 9999`)[cite: 2].
* **`RawPacket` (`ctypes.Structure`):** Mappa 1:1 la struct C++ `_packet` del server `ACC-TX-UDP` con allineamento `_pack_ = 4` e una dimensione verificata tramite `assert` di esattamente **508 byte**[cite: 2]. Gestisce nativamente float, int32, vettori 3D/4D e stringhe wide Windows `wchar_t[15]` (`UTF-16LE`)[cite: 2].
* **`CarState` (`@dataclass(frozen=True)`):** Modello dati immutabile e indipendente dal simulatore[cite: 2]. La GUI legge solo oggetti `CarState`, rendendo immediata l'aggiunta di futuri simulatori tramite nuovi Adapter[cite: 1, 2].
* **`ACCAdapter`:** Converte i 508 byte di `RawPacket` in `CarState` e fornisce il metodo `flatten()` per la diagnostica[cite: 2].
* **`FieldStats`:** Aggiornato a ogni singolo pacchetto di rete (non al frame rate della GUI) per catturare anche eventi brevissimi di pochi millisecondi (es. micro-attivazioni di TC/ABS) e tracciare min, max e occorrenze non-zero[cite: 2].
* **`TelemetryModel`:** Punto di scambio protetto da `threading.Lock`[cite: 2]. Mantiene l'ultimo `CarState`, il calcolo del packet rate reale (`rate_hz`), il contatore dei pacchetti malformati (`bad_packets`), una `deque` circolare fino a `15.000` campioni per i grafici e genera `Snapshot` atomici per la GUI[cite: 2].
* **`TelemetryClient` (`threading.Thread`):** Thread demone `"telemetry-rx"` su singolo socket UDP[cite: 2]:
  * Invia `b"START"` all'avvio per registrarsi sul server[cite: 2].
  * Invia `b"ALIVE"` a intervalli regolari (default `10 s`) per evitare il timeout del server (fissato a `30 s`)[cite: 2].
  * **Auto-Reconnect Watchdog:** Se non riceve dati per più di `5 s` (es. riavvio del server o del simulatore), ritrasmette automaticamente `b"START"` ogni `2 s` e gestisce silenziosamente gli errori Windows ICMP `ConnectionResetError (10054)`[cite: 2].
  * Invia `b"STOP"` alla chiusura pulita della connessione[cite: 2].

### 2. `pitwall_logic.py` — Logica di Dominio e Calcoli (Zero Dipendenze Qt)
Modulo puro Python, completamente slegato da `PySide6` per garantire testabilità immediata[cite: 3]:
* **`AppSettings`, `load_settings`, `save_settings`:** Gestione della configurazione su JSON con validazione dei range (`sanitize()`) e sistema di migrazione versione (`settings_version`) con fallback sicuro in caso di valori corrotti[cite: 3].
* **`FuelTracker`:** Poiché il campo `fuelXLap` del server è un intero (e quindi troncato senza decimali), `FuelTracker` calcola autonomamente il consumo medio misurando la differenza di carburante al traguardo tra un giro e il successivo su una finestra mobile (default `3` giri)[cite: 3]. Scarta automaticamente[cite: 3]:
  * Il giro di ingresso in pista (incompleto)[cite: 3].
  * I giri in cui rileva un rifornimento (`REFUEL_JUMP > 0.3 L`)[cite: 3].
  * I giri anomali o saltati (`MIN_LAP_USE < 0.2 L` o salto del contatore giri)[cite: 3].
* **`TravelTracker` & `resolve_susp_unit`:** Deduzione automatica dell'unità di misura delle sospensioni (distinguendo valori `< 1.0` in metri da valori `>= 1.0` in millimetri) e normalizzazione della corsa in `[0.0 .. 1.0]` sia su scala fissa che su scala dinamica auto-apprendente[cite: 3].
* **Funzioni di Classificazione e Formattazione[cite: 3]:**
  * `classify_window()` e `classify_life()`: Restituiscono lo stato semantico (`ok`, `warn`, `crit`, `low`, `na`) associato alla palette colori `LEVEL_COLORS`[cite: 3].
  * `thin_samples()`: Algoritmo di decimazione per i grafici che riduce il numero di punti da disegnare in base alla larghezza in pixel del widget, ma **forza la conservazione di tutti i campioni con flag attivo (TC/ABS) e dei punti di transizione**, evitando che interventi rapidissimi spariscano visivamente dal grafico[cite: 1, 3].
  * `fmt_lap()`: Usa in priorità i millisecondi interi (`iCurrentTime`, `iLastTime`, `iBestTime`) rispetto alle stringhe e filtra il valore sentinella `INT_MAX` (`2147483647` / `"35791:23.647"`) usato da ACC quando non c'è ancora un tempo valido[cite: 2, 3].

### 3. `acc_pitwall.py` — Interfaccia Utente e Rendering Vettoriale (`PySide6`)
* **Architettura Single-UI-Thread:** Nessun thread secondario tocca mai i widget[cite: 1]. Un `QTimer` sul thread principale interroga `TelemetryModel.snapshot()` alla frequenza configurata (`refresh_hz`, default `20 Hz`) e aggiorna la vista[cite: 1, 3].
* **Ottimizzazione dei Redraw (`Metric`, `FlagLabel`, `SteeringWheel`, `SuspensionPage`):** Ogni widget custom memorizza l'ultimo stato renderizzato (`_last`) e invoca `setText()`, `setStyleSheet()` o `update()` **solo se il valore o il livello colore è effettivamente cambiato**, riducendo al minimo l'uso della CPU[cite: 1]. Inoltre, il timer di animazione a `30 FPS` (`33 ms`) delle sospensioni viene avviato solo in `showEvent` (quando il tab Sospensioni è visibile) e fermato in `hideEvent`[cite: 1].

---

## 🚀 Installazione e Avvio

### Prerequisiti
1. **Python 3.10** o superiore.
2. Il server **[ACC-TX-UDP](https://github.com/gabbo76/ACC-TX-UDP)** in esecuzione sul PC dove gira *Assetto Corsa Competizione*[cite: 1, 2].

### 1. Clona il repository e installa PySide6

    git clone [https://github.com/gabbo76/Pitwall.git](https://github.com/gabbo76/Pitwall.git)
    cd Pitwall
    pip install PySide6

### 2. Avvia l'interfaccia grafica (Pit Wall)
Assicurati che i tre file (`acc_pitwall.py`, `acc_tx_client.py`, `pitwall_logic.py`) si trovino nella stessa cartella ed esegui[cite: 1]:

    python acc_pitwall.py

### 3. (Opzionale) Test rapido del client da terminale
Se vuoi verificare la ricezione dei pacchetti UDP dal server senza aprire la GUI[cite: 2]:

    python acc_tx_client.py --host 127.0.0.1 --port 9999

---

## ⌨️ Scorciatoie da Tastiera

| Scorciatoia | Azione |
| :--- | :--- |
| **`Ctrl + K`** | Connetti al server UDP[cite: 1] |
| **`Ctrl + Q`** | Chiudi l'applicazione (salva geometria finestra e impostazioni)[cite: 1] |
| **`Ctrl + ,`** | Apri la finestra **Impostazioni** (Connessione, Soglie, Volante, Sospensioni)[cite: 1] |
| **`Ctrl + 1`** | Passa alla scheda **Muretto**[cite: 1] |
| **`Ctrl + 2`** | Passa alla scheda **Grafici**[cite: 1] |
| **`Ctrl + 3`** | Passa alla scheda **Sospensioni**[cite: 1] |
| **`Ctrl + D`** | Apri la finestra **Diagnostica pacchetto** (ispezione live dei 508 byte)[cite: 1, 2] |
| **`F11`** | Attiva / Disattiva modalità **Schermo intero**[cite: 1] |

---

## 👤 Autore
Sviluppato da **[gabbo76](https://github.com/gabbo76)** — Parte dell'ecosistema telemetrico **[ACC-TX-UDP](https://github.com/gabbo76/ACC-TX-UDP)**[cite: 2].