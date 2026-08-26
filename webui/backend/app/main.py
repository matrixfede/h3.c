"""FastAPI application: health, capabilities and system inventory.

Binds to 127.0.0.1 by default and has no authentication: see the security note
in the README before exposing it anywhere.
"""

import shutil
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from pydantic import ValidationError

from . import assets, media
from .capabilities import load_schema
from .config import Settings, settings
from .db import Database
from .events import job_events
from .jobspec import EstimateRequest, JobSpec, validate
from .postprocess import registry
from .progress import observed_correction
from .runner import JobRunner
from .system import read_system


def create_app(config: Settings | None = None) -> FastAPI:
    config = config or settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.config = config
        app.state.db = Database(config.data_dir / "h3.sqlite3")
        app.state.runner = JobRunner(app.state.db, config)
        app.state.runner.start()
        yield
        app.state.runner.shutdown()
        app.state.db.close()

    app = FastAPI(title="h3.c Studio", version="0.1.0", lifespan=lifespan)

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "version": app.version}

    @app.get("/api/capabilities")
    def capabilities() -> dict[str, Any]:
        return load_schema(config.schema_path) | {
            "plugins": [plugin.as_dict() for plugin in registry(config)]
        }

    @app.get("/api/system")
    def system() -> dict[str, Any]:
        return read_system(config.binary, config.model_dir, config.info_timeout)

    @app.post("/api/jobs", status_code=201)
    def create_job(spec: JobSpec) -> dict[str, Any]:
        errors, warnings = validate(spec)
        if errors:
            raise HTTPException(status_code=422, detail={"errors": errors})
        job = app.state.runner.submit(spec)
        return job | {"warnings": warnings}

    @app.post("/api/jobs/validate")
    def validate_job(spec: JobSpec) -> dict[str, Any]:
        errors, warnings = validate(spec)
        model = app.state.runner.model
        correction, learned_from = observed_correction(app.state.db, model)
        return {
            "errors": errors,
            "warnings": warnings,
            "frames": spec.resolved_frames(),
            "seconds": round(spec.resolved_frames() / 24, 3),
            "estimate_seconds": round(
                sum(seconds for _, seconds in model.plan(spec)) * correction, 1
            ),
            "learned_from": learned_from,
        }

    @app.post("/api/jobs/estimate")
    def estimate(request: EstimateRequest) -> dict[str, Any]:
        """How long this job would take, and how long each alternative would.

        One request labels every choice on screen, so a card can say what it
        costs before it is picked.
        """
        model = app.state.runner.model
        correction, learned_from = observed_correction(app.state.db, model)

        def total(candidate: JobSpec) -> float:
            plan = model.plan(candidate)
            return round(sum(seconds for _, seconds in plan) * correction, 1)

        spec = request.spec
        answered = []
        for override in request.variants:
            try:
                candidate = JobSpec.model_validate(spec.model_dump() | override)
            except ValidationError as error:
                answered.append({"override": override, "error": error.error_count()})
                continue
            answered.append({"override": override, "seconds": total(candidate)})
        return {
            "seconds": total(spec),
            "variants": answered,
            "learned_from": learned_from,
        }

    @app.get("/api/jobs")
    def list_jobs(limit: int = 100) -> list[dict[str, Any]]:
        return app.state.runner.listing(limit)

    @app.get("/api/jobs/{job_id}")
    def read_job(job_id: int) -> dict[str, Any]:
        job = app.state.runner.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="unknown job")
        return job

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel_job(job_id: int) -> dict[str, Any]:
        job = app.state.runner.cancel(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="unknown job")
        return job

    @app.delete("/api/jobs/{job_id}", status_code=204)
    def delete_job(job_id: int) -> Response:
        try:
            outcome = app.state.runner.delete(job_id)
        except OSError as failure:
            raise HTTPException(
                status_code=500,
                detail=f"the files of this video could not be removed: {failure}",
            ) from failure
        if outcome is None:
            raise HTTPException(status_code=404, detail="unknown job")
        if outcome == "unfinished":
            raise HTTPException(
                status_code=409, detail="stop this video before deleting it"
            )
        return Response(status_code=204)

    @app.get("/api/jobs/{job_id}/events")
    async def job_stream(job_id: int) -> StreamingResponse:
        return StreamingResponse(
            job_events(app.state.runner, job_id),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/jobs/{job_id}/video")
    def job_video(job_id: int) -> FileResponse:
        job = _job_or_404(app, job_id)
        path = Path(job["output_path"] or "")
        if not path.is_file():
            raise HTTPException(status_code=404, detail="this job has no video")
        return FileResponse(path, media_type="video/mp4", filename=f"h3-{job_id}.mp4")

    @app.get("/api/jobs/{job_id}/poster")
    def job_poster(job_id: int) -> FileResponse:
        job = _job_or_404(app, job_id)
        video = Path(job["output_path"] or "")
        if not video.is_file():
            raise HTTPException(status_code=404, detail="this job has no video")
        poster = video.with_name("poster.jpg")
        if not poster.is_file() and not media.extract_poster(video, poster, config):
            raise HTTPException(status_code=404, detail="cannot build a poster")
        return FileResponse(poster, media_type="image/jpeg")

    @app.get("/api/jobs/{job_id}/preview")
    def job_preview(job_id: int) -> FileResponse:
        _job_or_404(app, job_id)
        jpeg = media.preview_jpeg(app.state.runner.preview_dir(job_id), config)
        if jpeg is None:
            raise HTTPException(status_code=404, detail="no preview yet")
        return FileResponse(
            jpeg, media_type="image/jpeg", headers={"Cache-Control": "no-store"}
        )

    @app.get("/api/jobs/{job_id}/log", response_class=PlainTextResponse)
    def job_log(job_id: int) -> str:
        job = _job_or_404(app, job_id)
        path = Path(job["log_path"] or "")
        if not path.is_file():
            raise HTTPException(status_code=404, detail="this job has no log")
        return path.read_text(errors="replace")

    @app.get("/api/assets")
    def list_assets() -> list[dict[str, Any]]:
        return assets.listing(app.state.db)

    @app.post("/api/assets", status_code=201)
    async def upload_asset(file: UploadFile) -> dict[str, Any]:
        filename = Path(file.filename or "").name
        if not filename:
            raise HTTPException(status_code=400, detail="the upload has no file name")
        with tempfile.TemporaryDirectory() as staging:
            staged = Path(staging) / filename
            with staged.open("wb") as handle:
                shutil.copyfileobj(file.file, handle)
            try:
                return assets.store(
                    app.state.db,
                    staged,
                    filename,
                    config.data_dir / "assets",
                    config.max_upload_bytes,
                    config.ffprobe,
                )
            except assets.AssetError as error:
                raise HTTPException(status_code=400, detail=str(error)) from error

    @app.get("/api/assets/{asset_id}/file")
    def asset_file(asset_id: int) -> FileResponse:
        row = app.state.db.query_one(
            "SELECT * FROM assets WHERE id = ?", (asset_id,)
        )
        if row is None:
            raise HTTPException(status_code=404, detail="unknown asset")
        return FileResponse(row["path"], filename=row["filename"])

    return app


def _job_or_404(app: FastAPI, job_id: int) -> dict[str, Any]:
    job = app.state.runner.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="unknown job")
    return job


app = create_app()
