import sys
from contextlib import contextmanager
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


@contextmanager
def authed_client(config, username="admin", password="correct-horse-9"):
    """The app under test, logged in as its first (admin) user.

    Production requires a session for every API call (R30), so the tests
    enter through the same door the browser does: register the first
    account, then log in, and keep the cookie for the rest of the session.
    """
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app(config)) as client:
        response = client.post(
            "/api/auth/register",
            json={"username": username, "password": password},
        )
        if response.status_code == 422 and "taken" in response.text:
            # A second app over the same data dir: the account is already
            # there, which is exactly the restart case these tests cover.
            pass
        else:
            assert response.status_code == 201, response.text
        response = client.post(
            "/api/auth/login",
            json={"username": username, "password": password},
        )
        assert response.status_code == 200, response.text
        yield client
