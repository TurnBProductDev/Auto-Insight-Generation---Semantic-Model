"""FastAPI backend for the client-onboarding wizard.

Endpoint map:

    GET  /api/schema                    the 200-key catalogue the form renders from
    GET  /api/clients                   every config/<client>/ on disk
    GET  /api/clients/{name}            config + both rulebooks + last probe
    PUT  /api/clients/{name}            write config/<client>/ (three files)
    POST /api/clients/{name}/clone      start a new client from an existing one
    GET  /api/clients/{name}/bundle     the three files as a zip
    DELETE /api/clients/{name}          remove a client directory

    POST /api/resolve-dataset           report id -> dataset id (a report id is not a dataset id)
    POST /api/probe                     start a probe; returns a job id
    GET  /api/jobs/{id}?offset=N        status + the log lines after N
    POST /api/jobs/{id}/cancel

    POST /api/validate                  blocking errors vs warnings
    POST /api/deploy                    upsert the Container Apps Job
    POST /api/deploy/start              run the job now
    GET  /api/deploy/executions         recent executions

Deployment writes are privileged, so :func:`create_app` refuses to expose them
unless ``allow_deploy`` is set - the local tool is single-user and unauthenticated
by design, and shipping an unauthenticated ARM write would be a different thing
entirely.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .. import config_schema
from ..services import clients, jobs, probe as probe_service, validate as validate_service

PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = Path(__file__).resolve().parent / "static"

#: Probe results live for the session. They are what turns the validation from
#: structural into real, so the UI keeps hold of the latest one per client.
PROBE_CACHE: dict[str, dict] = {}


def _record_or_404(name: str) -> clients.ClientRecord:
    try:
        record = clients.load_client(name)
    except clients.ClientError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not record.exists:
        raise HTTPException(status_code=404, detail=f"No client named {name!r}.")
    return record


def _existing_for_collision(exclude: str) -> list[dict]:
    return [
        {"name": record.name, "config": record.config}
        for record in clients.list_clients()
        if record.name != exclude
    ]


def create_app(*, allow_deploy: bool | None = None) -> FastAPI:
    if allow_deploy is None:
        allow_deploy = os.environ.get("CONFIG_UI_ALLOW_DEPLOY", "").strip().lower() in {
            "1", "true", "yes", "on",
        }

    app = FastAPI(
        title="InsightGen client onboarding",
        version="1.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.state.allow_deploy = allow_deploy

    # ---------------------------------------------------------------- schema
    @app.get("/api/schema")
    def get_schema() -> dict:
        return config_schema.to_json()

    @app.get("/api/health")
    def health() -> dict:
        return {
            "status": "ok",
            "allowDeploy": app.state.allow_deploy,
            "projectRoot": str(PROJECT_ROOT),
            "keys": len(config_schema.KEYS),
        }

    # --------------------------------------------------------------- clients
    @app.get("/api/clients")
    def list_clients() -> dict:
        return {
            "clients": [
                {**record.json(include_rules=False), "hasProbe": record.name in PROBE_CACHE}
                for record in clients.list_clients()
            ],
            "templates": {
                key: len(text) for key, text in clients.template_rulebooks().items()
            },
        }

    @app.get("/api/clients/{name}")
    def get_client(name: str) -> dict:
        record = _record_or_404(name)
        return {**record.json(), "probe": PROBE_CACHE.get(name)}

    @app.get("/api/clients/{name}/defaults")
    def client_defaults(name: str) -> dict:
        """A fresh config for a client that does not exist yet."""
        return {
            "name": name,
            "config": clients.new_config(),
            **clients.template_rulebooks(),
        }

    @app.put("/api/clients/{name}")
    def put_client(name: str, payload: dict = Body(...)) -> dict:
        config = payload.get("config")
        if not isinstance(config, dict):
            raise HTTPException(status_code=400, detail="'config' must be an object.")
        coerced, errors = config_schema.coerce_config(config)
        if errors:
            raise HTTPException(status_code=400, detail="; ".join(errors[:5]))
        try:
            record = clients.save_client(
                name,
                coerced,
                business_rules=payload.get("businessRules"),
                summary_business_rules=payload.get("summaryBusinessRules"),
                preserve_order=bool(payload.get("preserveOrder", True)),
            )
        except clients.ClientError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "saved": True,
            "client": record.json(include_rules=False),
            "runCommand": f"python -m src.main --config config/{name}/config.json",
        }

    @app.post("/api/clients/{name}/clone")
    def post_clone(name: str, payload: dict = Body(...)) -> dict:
        target = str(payload.get("target") or "").strip()
        try:
            record = clients.clone_client(name, target, overrides=payload.get("overrides") or {})
        except clients.ClientError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"cloned": True, "client": record.json(include_rules=False)}

    @app.get("/api/clients/{name}/bundle")
    def get_bundle(name: str) -> Response:
        try:
            data = clients.bundle(name)
        except clients.ClientError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return Response(
            content=data,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{name}-config.zip"'},
        )

    @app.delete("/api/clients/{name}")
    def delete_client(name: str) -> dict:
        try:
            removed = clients.delete_client(name)
        except clients.ClientError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        PROBE_CACHE.pop(name, None)
        return {"deleted": removed}

    # ------------------------------------------------------------ connection
    @app.post("/api/resolve-dataset")
    def resolve_dataset(payload: dict = Body(...)) -> dict:
        """Resolve a report id to its semantic model id.

        A report id is not a dataset id, and using one where the other belongs
        fails late and confusingly, so the wizard resolves it up front.
        """
        workspace = str(payload.get("workspaceId") or "").strip()
        report = str(payload.get("reportId") or "").strip()
        # The tenant must come from the form. get_powerbi_token() falls back to
        # the POWERBI_TENANT_ID environment variable, which is a deployment
        # setting and is normally unset locally - so omitting it here reports
        # "tenant is not configured" while the ID sits filled in on screen.
        # metadata_reader passes state["tenant_id"] for exactly this reason.
        tenant = str(payload.get("tenantId") or "").strip()
        if not workspace or not report:
            raise HTTPException(
                status_code=400,
                detail="Fill in the workspace ID, and paste a report ID, before looking it up.",
            )
        if not tenant:
            raise HTTPException(
                status_code=400,
                detail="Fill in the Organisation ID first - the lookup signs in with it.",
            )
        from ..tools.powerbi_executor import get_powerbi_token

        try:
            token = get_powerbi_token(tenant_id=tenant)
        except Exception as exc:  # noqa: BLE001 - reported, not raised through
            raise HTTPException(status_code=401, detail=f"Could not sign in to Power BI: {exc}") from exc
        import requests

        response = requests.get(
            f"https://api.powerbi.com/v1.0/myorg/groups/{workspace}/reports/{report}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        if response.status_code == 401:
            raise HTTPException(
                status_code=401,
                detail="Power BI refused the request. The identity needs read access to the "
                       "workspace, and the tenant's 'Execute Queries' setting must be enabled.",
            )
        if response.status_code == 404:
            raise HTTPException(status_code=404, detail="No such report in that workspace.")
        if not response.ok:
            raise HTTPException(status_code=502, detail=f"Power BI returned {response.status_code}.")
        body = response.json()
        return {
            "datasetId": body.get("datasetId"),
            "reportName": body.get("name"),
            "webUrl": body.get("webUrl"),
        }

    # ------------------------------------------------------------------ probe
    @app.post("/api/probe")
    def post_probe(payload: dict = Body(...)) -> dict:
        config = payload.get("config")
        name = str(payload.get("name") or "").strip()
        if not isinstance(config, dict):
            raise HTTPException(status_code=400, detail="'config' must be an object.")
        missing = [k for k in ("tenant_id", "workspace_id", "dataset_id")
                   if not str(config.get(k) or "").strip()]
        if missing:
            raise HTTPException(status_code=400, detail=f"Cannot probe without: {', '.join(missing)}.")

        config_path = str(PROJECT_ROOT / "config" / name / "config.json") if name else ""

        def work(log, job):
            result = probe_service.run_probe(
                dict(config),
                config_path=config_path,
                on_log=log,
                candidate_pool=payload.get("candidatePool"),
                deep=bool(payload.get("deepScan")),
            )
            data = result.json()
            if name:
                PROBE_CACHE[name] = data
            return data

        job = jobs.RUNNER.submit("probe", work, meta={"client": name})
        return {"jobId": job.id, "status": job.status}

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str, offset: int = Query(0, ge=0)) -> dict:
        job = jobs.RUNNER.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="No such job (it may have aged out).")
        return job.json(log_offset=offset)

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel_job(job_id: str) -> dict:
        return {"cancelled": jobs.RUNNER.cancel(job_id)}

    @app.get("/api/jobs")
    def recent_jobs(kind: str = "", limit: int = Query(20, ge=1, le=50)) -> dict:
        return {
            "jobs": [
                {k: v for k, v in job.json().items() if k not in {"logs", "result"}}
                for job in jobs.RUNNER.recent(kind=kind, limit=limit)
            ]
        }

    # -------------------------------------------------------------- validate
    @app.post("/api/validate")
    def post_validate(payload: dict = Body(...)) -> dict:
        config = payload.get("config") or {}
        name = str(payload.get("name") or "").strip()
        target = str(payload.get("target") or "local")
        probe_data = payload.get("probe") or PROBE_CACHE.get(name)
        report = validate_service.validate(
            config,
            target=target,
            probe=probe_data,
            existing_clients=_existing_for_collision(name),
            containers=payload.get("containers"),
            client_name=name,
            env=payload.get("env"),
        )
        rules = validate_service.validate_rulebooks(
            str(payload.get("businessRules") or ""),
            str(payload.get("summaryBusinessRules") or ""),
        )
        merged = validate_service.merge(report, rules)
        return {
            **merged.json(),
            "effective": validate_service.effective(config, payload.get("env")),
            "hasProbe": bool(probe_data),
        }

    @app.post("/api/storage-plan")
    def post_storage_plan(payload: dict = Body(...)) -> dict:
        """Exactly where the next run will write, worked out from the settings.

        There is not one cloud destination but three, serving different
        audiences, and a column of sixteen storage fields cannot convey that.
        The resolved paths can.
        """
        from ..services import storage

        name = str(payload.get("name") or "").strip()
        return storage.plan(
            payload.get("config") or {},
            other_clients=_existing_for_collision(name),
        )

    @app.get("/api/diff")
    def diff_clients(left: str, right: str) -> dict:
        """Which keys two clients disagree on - the fastest onboarding sanity check."""
        a, b = _record_or_404(left), _record_or_404(right)
        keys = config_schema.schema_order(set(a.config) | set(b.config))
        rows = []
        for key in keys:
            left_value, right_value = a.config.get(key), b.config.get(key)
            if left_value != right_value:
                entry = config_schema.get(key)
                rows.append(
                    {
                        "key": key,
                        "left": left_value,
                        "right": right_value,
                        "perClient": bool(entry and entry.per_client),
                        "help": entry.help if entry else "",
                    }
                )
        return {"left": left, "right": right, "differences": rows, "sharedKeys": len(keys) - len(rows)}

    # ---------------------------------------------------------------- deploy
    def _require_deploy() -> None:
        if not app.state.allow_deploy:
            raise HTTPException(
                status_code=403,
                detail="Deployment is disabled. It needs Contributor on the resource group, so "
                       "it stays off unless CONFIG_UI_ALLOW_DEPLOY=1 and the app is behind "
                       "authentication.",
            )

    def _spec_from(payload: dict):
        from ..services.deploy import JobSpec

        spec = payload.get("job") or {}
        # An empty string is as unusable as a missing key, and it is what an
        # untouched form field actually sends.
        missing = [
            name for name in ("subscriptionId", "resourceGroup", "jobName")
            if not str(spec.get(name) or "").strip()
        ]
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"These job settings are required: {', '.join('job.' + m for m in missing)}.",
            )
        try:
            return JobSpec(
                subscription_id=str(spec["subscriptionId"]),
                resource_group=str(spec["resourceGroup"]),
                job_name=str(spec["jobName"]),
                environment_id=str(spec.get("environmentId") or ""),
                location=str(spec.get("location") or ""),
                image=str(spec.get("image") or ""),
                cron=str(spec.get("cron") or "30 3 * * *"),
                cpu=float(spec.get("cpu") or 1.0),
                memory=str(spec.get("memory") or "2Gi"),
                replica_timeout=int(spec.get("replicaTimeout") or 3600),
                replica_retry_limit=int(spec.get("replicaRetryLimit") or 1),
                identity_resource_id=str(spec.get("identityResourceId") or ""),
                registry_server=str(spec.get("registryServer") or ""),
                registry_identity=str(spec.get("registryIdentity") or ""),
                env=dict(spec.get("env") or {}),
                secrets=dict(spec.get("secrets") or {}),
                secret_env=dict(spec.get("secretEnv") or {}),
            )
        except KeyError as exc:
            raise HTTPException(status_code=400, detail=f"job.{exc.args[0]} is required.") from exc

    @app.post("/api/deploy")
    def post_deploy(payload: dict = Body(...)) -> dict:
        _require_deploy()
        name = str(payload.get("name") or "").strip()
        record = _record_or_404(name)
        spec = _spec_from(payload)

        report = validate_service.validate(
            record.config,
            target="container",
            probe=PROBE_CACHE.get(name),
            existing_clients=_existing_for_collision(name),
            containers=payload.get("containers"),
            client_name=name,
            env=spec.env,
        )
        if not report.ok and not payload.get("force"):
            return JSONResponse(
                status_code=409,
                content={
                    "deployed": False,
                    "reason": "validation_failed",
                    "validation": report.json(),
                },
            )

        config_json = clients.dumps_config(
            record.config, key_order=record.key_order, newline=record.newline
        )

        def work(log, job):
            from ..services.deploy import deploy

            result = deploy(
                spec,
                config_json=config_json,
                business_rules=record.business_rules,
                summary_business_rules=record.summary_business_rules,
                on_log=log,
                allowed_job_names=payload.get("allowedJobNames"),
            )
            return result.json()

        job = jobs.RUNNER.submit("deploy", work, meta={"client": name, "job": spec.job_name})
        return {"jobId": job.id, "status": job.status, "validation": report.json()}

    @app.post("/api/deploy/preview")
    def preview_deploy(payload: dict = Body(...)) -> dict:
        """The exact ARM body, with secret values redacted. No network call."""
        from ..services.deploy import build_job_body, merge_secrets, redact, secret_payload

        name = str(payload.get("name") or "").strip()
        record = _record_or_404(name)
        spec = _spec_from(payload)
        updates = secret_payload(
            clients.dumps_config(record.config, key_order=record.key_order, newline=record.newline),
            record.business_rules,
            record.summary_business_rules,
        )
        secrets, carried = merge_secrets(payload.get("existingSecrets") or [], {**updates, **spec.secrets})
        try:
            body = build_job_body(spec, secrets)
        except Exception as exc:  # noqa: BLE001 - a preview reports its own problem
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "body": redact(body),
            "carriedSecrets": carried,
            "secretSizes": {name: len(value) for name, value in updates.items()},
        }

    @app.post("/api/deploy/start")
    def post_start(payload: dict = Body(...)) -> dict:
        _require_deploy()
        from ..services.deploy import start_job

        try:
            return start_job(_spec_from(payload))
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/api/deploy/executions")
    def post_executions(payload: dict = Body(...)) -> dict:
        _require_deploy()
        from ..services.deploy import list_executions

        try:
            return {"executions": list_executions(_spec_from(payload))}
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    # ------------------------------------------------------------------- UI
    @app.get("/")
    def index() -> Any:
        return FileResponse(STATIC_DIR / "index.html")

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    return app


app = create_app()


def main(argv=None) -> int:
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(description="Client-onboarding UI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8020)
    parser.add_argument("--allow-deploy", action="store_true",
                        help="expose the ARM deployment endpoints (needs Contributor)")
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args(argv)

    try:
        from dotenv import load_dotenv

        load_dotenv(PROJECT_ROOT / ".env")
    except Exception:  # noqa: BLE001 - .env is optional
        pass

    if args.allow_deploy:
        os.environ["CONFIG_UI_ALLOW_DEPLOY"] = "1"
    print(f"Client onboarding UI -> http://{args.host}:{args.port}")
    print(f"  deployment endpoints: {'ENABLED' if args.allow_deploy else 'disabled'}")
    uvicorn.run(
        "src.api.app:app" if args.reload else create_app(allow_deploy=args.allow_deploy),
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
