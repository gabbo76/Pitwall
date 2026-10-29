"""
ACC Pit Wall - punto di avvio.

    py -m pip install PySide6-Essentials
    py acc_pitwall.py

Struttura: questo file avvia soltanto l'app. Il resto sta in
  acc_tx_client.py   rete (START/ALIVE/STOP), parsing del pacchetto, modello dati
  pitwall_logic.py   logica senza grafica (soglie, carburante, impostazioni, serie dei grafici)
  pitwall_ui/        interfaccia: una pagina per file (vedi README)
"""
import sys


def _run() -> None:
    try:
        from pitwall_ui.main_window import main
    except ModuleNotFoundError as e:
        if e.name and e.name.split(".")[0] == "PySide6":
            sys.exit("Manca PySide6. Installalo con lo STESSO Python con cui avvii l'app:\n"
                     "    py -m pip install PySide6-Essentials\n"
                     "(per vedere quali Python hai: py -0p)")
        if e.name and e.name.split(".")[0] in ("pitwall_ui", "acc_tx_client", "pitwall_logic"):
            sys.exit(f"Manca il modulo '{e.name}': copia TUTTI i file del progetto nella stessa cartella,\n"
                     "compresa la cartella pitwall_ui.")
        raise
    except ImportError as e:
        sys.exit(f"I file del progetto non sono tutti della stessa versione ({e}).\n"
                 "Sostituisci insieme acc_pitwall.py, acc_tx_client.py, pitwall_logic.py e la cartella pitwall_ui.")
    main()


if __name__ == "__main__":
    _run()
