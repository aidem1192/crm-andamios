"""
Respaldo automático de la base de datos local (SQLite).
- Copia data/andamios.db  →  backups/andamios_YYYY-MM-DD_HH-MM.db
- Mantiene los últimos RETENER_BACKUPS archivos (por defecto 14).
- Escribe un log en backups/backup.log

Uso manual:
    python backup.py

Uso programado (Windows Task Scheduler):
    Ejecutar setup_tarea_backup.ps1 una sola vez como administrador.

En producción (Supabase/Railway): Supabase hace backups diarios automáticamente;
este script solo actúa si detecta que la base es SQLite local.
"""

import os
import shutil
import glob
from datetime import datetime
from pathlib import Path

BASE_DIR   = Path(__file__).parent
DB_PATH    = BASE_DIR / "data" / "andamios.db"
BACKUP_DIR = BASE_DIR / "backups"
LOG_FILE   = BACKUP_DIR / "backup.log"
RETENER    = 14   # número de respaldos a conservar

def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")

def main():
    # Si la app apunta a Postgres (variable de entorno), no hacer nada
    db_url = os.environ.get("DATABASE_URL", "")
    if db_url and not db_url.startswith("sqlite"):
        log("Base de datos en Postgres/Supabase — respaldo gestionado por Supabase. Nada que hacer.")
        return

    if not DB_PATH.exists():
        log(f"ADVERTENCIA: No se encontró la base de datos en {DB_PATH}")
        return

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
    destino   = BACKUP_DIR / f"andamios_{timestamp}.db"

    shutil.copy2(DB_PATH, destino)
    size_kb = destino.stat().st_size // 1024
    log(f"Respaldo creado: {destino.name} ({size_kb} KB)")

    # Rotar: eliminar los más viejos si hay más de RETENER
    archivos = sorted(glob.glob(str(BACKUP_DIR / "andamios_*.db")))
    sobrantes = archivos[:-RETENER] if len(archivos) > RETENER else []
    for f in sobrantes:
        Path(f).unlink()
        log(f"Respaldo antiguo eliminado: {Path(f).name}")

    log(f"Respaldos disponibles: {max(len(archivos) - len(sobrantes), 1)}")

if __name__ == "__main__":
    main()
