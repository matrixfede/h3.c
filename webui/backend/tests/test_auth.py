"""T121 (R30): the auth endpoints and the door they guard.

What is covered, end to end through the HTTP surface:

- the first account registers itself and becomes the admin;
- every account after that exists only through an invite;
- login sets the cookie, logout kills the session, `me` names the user;
- everything under `/api/*` — lists, SSE streams and media included —
  answers 401 without a valid session;
- five wrong passwords buy a pause, not a lockout forever.
"""

import sqlite3

from conftest import authed_client

from app.config import Settings

PASSWORD = "correct-horse-9"


def _config(tmp_path):
    return Settings(
        binary=tmp_path / "absent", model_dir=tmp_path, data_dir=tmp_path / "data"
    )


def _register(client, username="someone", password=PASSWORD, invite=None):
    payload = {"username": username, "password": password}
    if invite is not None:
        payload["invite"] = invite
    return client.post("/api/auth/register", json=payload)


def _login(client, username="someone", password=PASSWORD):
    return client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )


def test_the_first_account_is_the_admin(tmp_path):
    with authed_client(_config(tmp_path)) as client:
        response = client.get("/api/auth/me")
        assert response.status_code == 200
        assert response.json() == {"username": "admin", "role": "admin"}


def test_a_second_account_needs_an_invite(tmp_path):
    with authed_client(_config(tmp_path)) as client:
        assert _register(client).status_code == 400
        assert _register(client, invite="not-a-real-code").status_code == 400

        code = client.app.state.db.query_one(
            "SELECT id FROM users WHERE username = 'admin'"
        )["id"]
        from app import auth

        invite = auth.create_invite(client.app.state.db, code)

        response = _register(client, invite=invite)
        assert response.status_code == 201
        assert response.json() == {"username": "someone", "role": "user"}
        # An invite is single-use.
        assert _register(client, username="third", invite=invite).status_code == 400


def test_register_rejects_bad_input(tmp_path):
    with authed_client(_config(tmp_path)) as client:
        response = _register(client, username="has spaces")
        assert response.status_code == 422
        assert "errors" in response.json()["detail"]

        response = _register(client, password="short")
        assert response.status_code == 422

        response = _register(client, username="admin")
        assert response.status_code == 422
        assert "taken" in response.text


def test_login_and_logout_lifecycle(tmp_path):
    from fastapi.testclient import TestClient

    from app.main import create_app

    config = _config(tmp_path)
    with TestClient(create_app(config)) as client:
        assert _register(client, username="solo").status_code == 201

        response = _login(client, username="solo", password="the wrong one")
        assert response.status_code == 401

        response = _login(client, username="solo")
        assert response.status_code == 200
        assert client.cookies.get("h3_session")

        me = client.get("/api/auth/me")
        assert me.status_code == 200
        assert me.json()["username"] == "solo"

        assert client.post("/api/auth/logout").status_code == 204
        # The session row is gone: the same cookie buys nothing now.
        assert client.get("/api/auth/me").status_code == 401


def test_the_whole_api_is_behind_the_door(tmp_path):
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app(_config(tmp_path))) as anonymous:
        assert anonymous.get("/api/jobs").status_code == 401
        assert anonymous.get("/api/assets").status_code == 401
        assert anonymous.get("/api/system").status_code == 401
        assert anonymous.get("/api/jobs/1/events").status_code == 401
        assert anonymous.get("/api/jobs/1/video").status_code == 401
        assert anonymous.get("/api/jobs/1/poster").status_code == 401
        assert anonymous.get("/api/jobs/1/log").status_code == 401
        assert anonymous.post("/api/jobs", json={}).status_code == 401
        # Health stays open: monitoring must not need an account.
        assert anonymous.get("/api/health").status_code == 200


def test_five_wrong_passwords_buy_a_pause(tmp_path):
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app(_config(tmp_path))) as client:
        assert _register(client, username="solo").status_code == 201
        for _ in range(5):
            assert _login(client, password="wrong one").status_code == 401
        # Even the right password now has to wait out the window.
        assert _login(client).status_code == 429


def test_a_successful_login_clears_the_counter(tmp_path):
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app(_config(tmp_path))) as client:
        assert _register(client, username="solo").status_code == 201
        for _ in range(4):
            bad = _login(client, username="solo", password="wrong one")
            assert bad.status_code == 401
        assert _login(client, username="solo").status_code == 200
        # The slate is clean: four more misses are allowed, not one.
        for _ in range(4):
            bad = _login(client, username="solo", password="wrong one")
            assert bad.status_code == 401
        assert _login(client, username="solo").status_code == 200


def test_what_existed_before_accounts_goes_to_the_first_admin(tmp_path):
    config = _config(tmp_path)
    config.data_dir.mkdir(parents=True, exist_ok=True)
    database = config.data_dir / "h3.sqlite3"
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        CREATE TABLE jobs (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            state         TEXT NOT NULL DEFAULT 'queued',
            prompt        TEXT NOT NULL DEFAULT '',
            params        TEXT NOT NULL,
            argv          TEXT,
            phase         TEXT,
            completed     INTEGER NOT NULL DEFAULT 0,
            total         INTEGER NOT NULL DEFAULT 0,
            progress      REAL NOT NULL DEFAULT 0.0,
            error         TEXT,
            output_path   TEXT,
            log_path      TEXT,
            created_at    TEXT NOT NULL DEFAULT (datetime('now')),
            started_at    TEXT,
            finished_at   TEXT
        );
        CREATE TABLE assets (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            sha256        TEXT NOT NULL UNIQUE,
            kind          TEXT NOT NULL,
            filename      TEXT NOT NULL,
            path          TEXT NOT NULL,
            bytes         INTEGER NOT NULL,
            metadata      TEXT,
            created_at    TEXT NOT NULL DEFAULT (datetime('now'))
        );
        INSERT INTO jobs (state, prompt, params) VALUES ('completed', 'x', '{}');
        """
    )
    connection.commit()
    connection.close()

    with authed_client(config) as client:
        rows = client.app.state.db.query_all("SELECT owner FROM jobs")
        assert len(rows) == 1
        assert rows[0]["owner"] is not None
        admin = client.app.state.db.query_one(
            "SELECT id FROM users WHERE username = 'admin'"
        )
        assert rows[0]["owner"] == admin["id"]
