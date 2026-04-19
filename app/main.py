"""
Azure VM Python App — example FastAPI application.

This app is deployed automatically by the cloud-init bootstrap script
when the Azure infrastructure is provisioned via Terraform.
"""

import os
import platform
import socket
import subprocess
from datetime import datetime, timezone

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import JSONResponse

load_dotenv()

APP_ENV = os.getenv("APP_ENV", "dev")
APP_PORT = int(os.getenv("APP_PORT", "8000"))
APP_VERSION = "1.0.0"

app = FastAPI(
    title="Azure VM Python App",
    description="A FastAPI application deployed on an Azure Linux VM via Terraform + cloud-init.",
    version=APP_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
)


@app.get("/", summary="Root")
async def root() -> JSONResponse:
    return JSONResponse(
        {
            "app": "azure-vm-python",
            "version": APP_VERSION,
            "environment": APP_ENV,
            "status": "running",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )


@app.get("/health", summary="Health check")
async def health() -> JSONResponse:
    """Liveness probe — returns 200 when the process is up."""
    return JSONResponse({"status": "healthy"})


@app.get("/info", summary="System info")
async def info() -> JSONResponse:
    """Returns basic VM and runtime information."""
    try:
        git_sha = (
            subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=os.path.dirname(__file__),
                stderr=subprocess.DEVNULL,
            )
            .decode()
            .strip()
        )
    except Exception:
        git_sha = "unknown"

    return JSONResponse(
        {
            "hostname": socket.gethostname(),
            "python_version": platform.python_version(),
            "os": f"{platform.system()} {platform.release()}",
            "git_sha": git_sha,
            "environment": APP_ENV,
            "port": APP_PORT,
        }
    )
