"""Queue and runner, driven by a stand-in for the h3 binary.

The fake reproduces what matters about h3: progress written to stderr with a
carriage return, an mp4 written where -o points, and h3-prefixed error lines.
No GPU and no checkpoint are involved.
"""

import stat
import time

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

JOB = {"prompt": "a fox", "width": 512, "height": 512, "frames": 22, "steps": 2}

SUCCESS = r"""#!/bin/sh
out=""
while [ $# -gt 0 ]; do
  case "$1" in -o) out="$2"; shift;; esac
  shift
done
printf 'h3: starting\n' >&2
printf '\rtext encoder                 %d/50   ' 50 >&2
printf '\rdenoise                       1/2    ' >&2
printf '\rdenoise                       2/2    ' >&2
printf '\n' >&2
[ -n "$out" ] && printf 'fake mp4' > "$out"
exit 0
"""

FAILURE = r"""#!/bin/sh
printf 'h3: canvas exceeds the released 768*1344 pixel limit\n' >&2
exit 1
"""

SLOW = r"""#!/bin/sh
trap 'exit 143' TERM
printf '\rdenoise                       1/900  ' >&2
sleep 30 &
wait $!
"""


def _binary(tmp_path, script):
    path = tmp_path / "h3"
    path.write_text(script)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


def _client(tmp_path, script):
    config = Settings(
        binary=_binary(tmp_path, script),
        model_dir=tmp_path,
        data_dir=tmp_path / "data",
    )
    return TestClient(create_app(config))


def _wait(client, job_id, states, timeout=20.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["state"] in states:
            return job
        time.sleep(0.05)
    pytest.fail(f"job stayed in {job['state']}")


def test_a_job_runs_to_completion_and_keeps_its_artifacts(tmp_path):
    with _client(tmp_path, SUCCESS) as client:
        created = client.post("/api/jobs", json=JOB)
        assert created.status_code == 201
        job = _wait(client, created.json()["id"], {"completed", "failed"})
    assert job["state"] == "completed"
    assert job["progress"] == 1.0
    assert (tmp_path / "data/jobs/1/out.mp4").read_text() == "fake mp4"
    assert "h3: starting" in (tmp_path / "data/jobs/1/job.log").read_text()


def test_progress_is_parsed_from_carriage_return_updates(tmp_path):
    seen = []
    with _client(tmp_path, SUCCESS) as client:
        client.app.state.runner.add_listener(
            lambda job: seen.append((job["phase"], job["completed"], job["total"]))
        )
        created = client.post("/api/jobs", json=JOB)
        _wait(client, created.json()["id"], {"completed", "failed"})
    assert ("text encoder", 50, 50) in seen
    assert ("denoise", 1, 2) in seen
    assert ("denoise", 2, 2) in seen


def test_a_failing_run_keeps_the_h3_error_line(tmp_path):
    with _client(tmp_path, FAILURE) as client:
        created = client.post("/api/jobs", json=JOB)
        job = _wait(client, created.json()["id"], {"completed", "failed"})
    assert job["state"] == "failed"
    assert job["error"] == "h3: canvas exceeds the released 768*1344 pixel limit"


def test_a_running_job_can_be_cancelled(tmp_path):
    with _client(tmp_path, SLOW) as client:
        created = client.post("/api/jobs", json=JOB)
        job_id = created.json()["id"]
        _wait(client, job_id, {"running"})
        cancelled = client.post(f"/api/jobs/{job_id}/cancel").json()
        assert cancelled["state"] in {"cancelled", "running"}
        job = _wait(client, job_id, {"cancelled", "failed", "completed"})
    assert job["state"] == "cancelled"


def test_a_queued_job_can_be_cancelled_before_it_starts(tmp_path):
    with _client(tmp_path, SLOW) as client:
        first = client.post("/api/jobs", json=JOB).json()["id"]
        second = client.post("/api/jobs", json=JOB).json()["id"]
        _wait(client, first, {"running"})
        assert client.get(f"/api/jobs/{second}").json()["state"] == "queued"
        cancelled = client.post(f"/api/jobs/{second}/cancel").json()
        assert cancelled["state"] == "cancelled"
        client.post(f"/api/jobs/{first}/cancel")
        _wait(client, first, {"cancelled", "failed", "completed"})


def test_jobs_run_one_at_a_time(tmp_path):
    with _client(tmp_path, SLOW) as client:
        ids = [client.post("/api/jobs", json=JOB).json()["id"] for _ in range(3)]
        _wait(client, ids[0], {"running"})
        states = [client.get(f"/api/jobs/{i}").json()["state"] for i in ids]
        assert states.count("running") == 1
        assert states.count("queued") == 2
        for job_id in ids:
            client.post(f"/api/jobs/{job_id}/cancel")
        for job_id in ids:
            _wait(client, job_id, {"cancelled", "failed", "completed"})


def test_an_invalid_job_is_refused_before_it_is_queued(tmp_path):
    with _client(tmp_path, SUCCESS) as client:
        response = client.post("/api/jobs", json={**JOB, "width": 500})
        assert response.status_code == 422
        assert (
            "width and height must be multiples of 32 and at least 32"
            in response.json()["detail"]["errors"]
        )
        assert client.get("/api/jobs").json() == []


def test_validate_endpoint_reports_the_resolved_duration(tmp_path):
    with _client(tmp_path, SUCCESS) as client:
        body = client.post(
            "/api/jobs/validate", json={**JOB, "frames": None, "seconds": 10.0}
        ).json()
    assert body["errors"] == []
    assert body["frames"] == 243
    assert body["seconds"] == 10.125


def test_the_recorded_argv_is_the_command_that_ran(tmp_path):
    with _client(tmp_path, SUCCESS) as client:
        created = client.post("/api/jobs", json=JOB)
        job = _wait(client, created.json()["id"], {"completed", "failed"})
    assert job["argv"][1:3] == ["-d", str(tmp_path)]
    assert job["argv"][job["argv"].index("--frames") + 1] == "22"


def test_missing_binary_fails_the_job_with_a_reason(tmp_path):
    config = Settings(
        binary=tmp_path / "absent", model_dir=tmp_path, data_dir=tmp_path / "data"
    )
    with TestClient(create_app(config)) as client:
        created = client.post("/api/jobs", json=JOB)
        job = _wait(client, created.json()["id"], {"failed", "completed"})
    assert job["state"] == "failed"
    assert "cannot start h3" in job["error"]


def test_unknown_job_is_a_404(tmp_path):
    with _client(tmp_path, SUCCESS) as client:
        assert client.get("/api/jobs/404").status_code == 404


def test_a_job_interrupted_by_a_restart_is_marked_failed(tmp_path):
    config = Settings(
        binary=_binary(tmp_path, SUCCESS),
        model_dir=tmp_path,
        data_dir=tmp_path / "data",
    )
    with TestClient(create_app(config)) as client:
        created = client.post("/api/jobs", json=JOB)
        _wait(client, created.json()["id"], {"completed", "failed"})
        # Simulate a backend killed while a job was running.
        client.app.state.db.run("UPDATE jobs SET state='running' WHERE id=1")
    with TestClient(create_app(config)) as client:
        job = client.get("/api/jobs/1").json()
    assert job["state"] == "failed"
    assert job["error"] == "interrupted by a backend restart"


def test_shutdown_cancels_the_running_job_instead_of_failing_it(tmp_path):
    config = Settings(
        binary=_binary(tmp_path, SLOW),
        model_dir=tmp_path,
        data_dir=tmp_path / "data",
    )
    with TestClient(create_app(config)) as client:
        job_id = client.post("/api/jobs", json=JOB).json()["id"]
        _wait(client, job_id, {"running"})
    with TestClient(create_app(config)) as client:
        job = client.get(f"/api/jobs/{job_id}").json()
    assert job["state"] == "cancelled"
