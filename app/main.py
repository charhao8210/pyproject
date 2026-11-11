from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .cpp_runner import CppCompilationError, CppToolchainError
from .chooser import slot_candidates
from .models import CandidatesRequest, DebugRequest, DebugResponse
from .runner import ExecutionTimeoutError, WorkerExecutionError, run_debugger
from .validator import SourceValidationError


BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="Code Visual Debugger", version="1.1.0")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


def _asset_version() -> str:
    """Changes whenever a static file changes.

    The page adds it to its CSS/JS URLs, so a browser never pairs a new page with a
    cached old script (an old app.js looking up removed buttons stops at its first line).
    """
    static = BASE_DIR / "static"
    return format(max(path.stat().st_mtime_ns for path in static.iterdir() if path.is_file()), "x")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    response = templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"asset_version": _asset_version()},
    )
    response.headers["Cache-Control"] = "no-cache"
    return response


@app.get("/help", response_class=HTMLResponse)
async def help_page(request: Request) -> HTMLResponse:
    """How to use the debugger, and every term it shows (the list lives in static/terms.js)."""
    response = templates.TemplateResponse(
        request=request,
        name="help.html",
        context={"asset_version": _asset_version()},
    )
    response.headers["Cache-Control"] = "no-cache"
    return response


@app.post("/api/candidates")
def candidates(payload: CandidatesRequest) -> dict:
    """Variables of the code that fit each chooser slot, read before Run (nothing runs)."""
    return {"slots": slot_candidates(payload.code, payload.language)}


@app.post("/api/debug", response_model=DebugResponse)
def debug_code(payload: DebugRequest) -> dict:
    try:
        return run_debugger(
            payload.code,
            stdin_text=payload.stdin,
            language=payload.language,
            extra_views=payload.views,
            choice=payload.choice.model_dump() if payload.choice else None,
        )
    except SourceValidationError as error:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "The code cannot run.",
                "issues": [issue.as_dict() for issue in error.issues],
            },
        ) from error
    except ExecutionTimeoutError as error:
        raise HTTPException(status_code=408, detail=str(error)) from error
    except CppCompilationError as error:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Compilation failed.",
                "issues": error.issues or [{"message": str(error), "line": None, "column": None}],
                "output": str(error),
            },
        ) from error
    except CppToolchainError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except WorkerExecutionError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error
