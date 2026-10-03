from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .cpp_runner import CppCompilationError, CppToolchainError
from .models import DebugRequest, DebugResponse
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


JS_SAFE_INTEGER = 2**53 - 1


def _mark_large_integers(value: object, seen: set[int] | None = None) -> None:
    """Give every `value` beyond 2^53 an exact `text`: JSON numbers that large reach the
    browser rounded (`500000000000000003` arrived as `500000000000000000`)."""
    seen = set() if seen is None else seen
    if not isinstance(value, (dict, list)) or id(value) in seen:
        return
    seen.add(id(value))
    if isinstance(value, dict):
        number = value.get("value")
        if isinstance(number, int) and not isinstance(number, bool) and abs(number) > JS_SAFE_INTEGER:
            value["text"] = str(number)
        # View models hold bare numbers (`values`, grid `rows`, per-vertex `labels.values`):
        # they get an exact twin, `values_text`, holding every number as text.
        for key, child in list(value.items()):
            if isinstance(child, (list, dict)) and not key.endswith("_text"):
                mirror, large = _exact_text(child)
                if large:
                    value[f"{key}_text"] = mirror
        children = list(value.values())
    else:
        children = value
    for child in children:
        _mark_large_integers(child, seen)


def _exact_text(value: object, depth: int = 0) -> tuple[object, bool]:
    """`[1, 5e17+3]` → `(["1", "500000000000000003"], True)`: bare numbers as exact text, and
    whether any is beyond 2^53. Serialized values (dicts) are left alone: they get `text`."""
    if isinstance(value, bool):
        return None, False
    if isinstance(value, int):
        return str(value), abs(value) > JS_SAFE_INTEGER
    if depth >= 2:
        return None, False
    if isinstance(value, list):
        mirrored = [_exact_text(item, depth + 1) for item in value]
        return [text for text, _ in mirrored], any(large for _, large in mirrored)
    if isinstance(value, dict) and "type" not in value:
        mirrored = {key: _exact_text(item, depth + 1) for key, item in value.items()}
        return {key: text for key, (text, _) in mirrored.items()}, any(large for _, large in mirrored.values())
    return None, False


@app.post("/api/debug", response_model=DebugResponse)
def debug_code(payload: DebugRequest) -> dict:
    try:
        result = run_debugger(
            payload.code,
            stdin_text=payload.stdin,
            language=payload.language,
        )
        _mark_large_integers(result)
        return result
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
