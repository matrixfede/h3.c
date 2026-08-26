"""The post-processing extension point: declared, disabled, and inert."""

import stat
import time

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.postprocess import PluginError, registry, run_stage

JOB = {"prompt": "a fox", "width": 256, "height": 256, "frames": 22, "steps": 2}

MAKES_VIDEO = r"""#!/bin/sh
out=""
while [ $# -gt 0 ]; do
  case "$1" in -o) out="$2"; shift;; esac
  shift
done
[ -n "$out" ] && printf 'raw video' > "$out"
exit 0
"""

# A stand-in plugin: reads --input, writes --output. No model, no runtime.
SWAPPER = r"""#!/bin/sh
input=""; output=""
while [ $# -gt 0 ]; do
  case "$1" in
    --input) input="$2"; shift;;
    --output) output="$2"; shift;;
  esac
  shift
done
printf 'swapped(%s)' "$(cat "$input")" > "$output"
exit 0
"""

BROKEN = "#!/bin/sh\nprintf 'faceswap: no model installed\\n' >&2\nexit 3\n"


def _executable(path, script):
    path.write_text(script)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


def _client(tmp_path, faceswap_cmd=""):
    config = Settings(
        binary=_executable(tmp_path / "h3", MAKES_VIDEO),
        model_dir=tmp_path,
        data_dir=tmp_path / "data",
        faceswap_cmd=faceswap_cmd,
    )
    return TestClient(create_app(config))


def _wait(client, job_id, timeout=20.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["state"] in {"completed", "failed", "cancelled"}:
            return job
        time.sleep(0.05)
    pytest.fail("job never finished")


def test_the_repository_ships_no_model_and_the_plugin_is_unavailable(tmp_path):
    plugins = registry(Settings(faceswap_cmd=""))
    assert [plugin.name for plugin in plugins] == ["faceswap"]
    faceswap = plugins[0]
    assert faceswap.available is False
    assert "no model and no runtime installed" in faceswap.reason
    assert "non-commercial/research" in faceswap.notice


def test_capabilities_shows_the_plugin_as_unavailable_with_a_reason(tmp_path):
    with _client(tmp_path) as client:
        plugin = client.get("/api/capabilities").json()["plugins"][0]
    assert plugin["available"] is False
    assert plugin["env_var"] == "H3_FACESWAP_CMD"
    assert "set H3_FACESWAP_CMD" in plugin["reason"]


def test_without_plugins_the_pipeline_is_exactly_what_it_was(tmp_path):
    with _client(tmp_path) as client:
        job = _wait(client, client.post("/api/jobs", json=JOB).json()["id"])
    assert job["state"] == "completed"
    assert (tmp_path / "data/jobs/1/out.mp4").read_text() == "raw video"


def test_an_unavailable_plugin_cannot_be_requested(tmp_path):
    with _client(tmp_path) as client:
        job_id = client.post(
            "/api/jobs", json={**JOB, "postprocess": ["faceswap"]}
        ).json()["id"]
        job = _wait(client, job_id)
    assert job["state"] == "failed"
    assert "unavailable" in job["error"]
    # The generated video is kept: generation itself succeeded.
    assert (tmp_path / "data/jobs/1/out.mp4").read_text() == "raw video"


def test_an_installed_plugin_replaces_the_video(tmp_path):
    command = _executable(tmp_path / "swapper", SWAPPER)
    with _client(tmp_path, faceswap_cmd=str(command)) as client:
        assert client.get("/api/capabilities").json()["plugins"][0]["available"] is True
        job_id = client.post(
            "/api/jobs", json={**JOB, "postprocess": ["faceswap"]}
        ).json()["id"]
        job = _wait(client, job_id)
    assert job["state"] == "completed"
    assert (tmp_path / "data/jobs/1/out.mp4").read_text() == "swapped(raw video)"


def test_a_failing_plugin_fails_the_job_and_keeps_the_raw_video(tmp_path):
    command = _executable(tmp_path / "swapper", BROKEN)
    with _client(tmp_path, faceswap_cmd=str(command)) as client:
        job_id = client.post(
            "/api/jobs", json={**JOB, "postprocess": ["faceswap"]}
        ).json()["id"]
        job = _wait(client, job_id)
    assert job["state"] == "failed"
    assert job["error"] == (
        "post-processing faceswap failed: faceswap: no model installed"
    )
    assert (tmp_path / "data/jobs/1/out.mp4").read_text() == "raw video"


def test_an_unknown_plugin_name_is_refused(tmp_path):
    with pytest.raises(PluginError, match="unknown post-processing plugin"):
        run_stage(Settings(), tmp_path / "video.mp4", ["upscale"])
