import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

DB_PATH = os.environ.get("NEWTONITE_DB_PATH", str(DATA_DIR / "ops_coordinator.db"))
PORT = int(os.environ.get("PORT", "8000"))
HOST = os.environ.get("HOST", "127.0.0.1")
ASYNC_WORKER_INTERVAL_SEC = float(os.environ.get("ASYNC_WORKER_INTERVAL_SEC", "1.5"))
