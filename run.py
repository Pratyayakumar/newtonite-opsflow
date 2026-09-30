import sys
import uvicorn
from app.config import HOST, PORT
from app.seed import seed_database
from app.database import init_db

if __name__ == "__main__":
    print("=" * 60)
    print("Newtonite Operations Coordinator System")
    print("Initializing SQLite database & verifying seed dataset...")
    seed_database(reset=False)
    print(f"Server starting on http://{HOST}:{PORT}")
    print("=" * 60)
    uvicorn.run("app.main:app", host=HOST, port=PORT, log_level="info")
