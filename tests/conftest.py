import os
import tempfile
import pytest
from fastapi.testclient import TestClient

# Set temporary test database before importing app
temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
temp_db.close()
os.environ["NEWTONITE_DB_PATH"] = temp_db.name

from app.database import init_db
from app.seed import seed_database
from app.main import app

@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    init_db()
    seed_database(reset=True)
    yield
    try:
        os.remove(temp_db.name)
    except Exception:
        pass

@pytest.fixture
def client():
    # Fresh seed for predictable test isolation
    seed_database(reset=True)
    with TestClient(app) as test_client:
        yield test_client
