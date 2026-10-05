from __future__ import annotations

import json
import sys
from pathlib import Path

from .tracer import DEFAULT_MAX_STEPS, MAX_RECURSION_DEPTH, trace_code
from .validator import SourceValidationError, validate_source


def main() -> None:
    # The tracer reports RecursionError itself at MAX_RECURSION_DEPTH user calls; Python's own
    # limit must sit above that plus the frames of the worker and tracer.
    sys.setrecursionlimit(MAX_RECURSION_DEPTH + 400)
    payload = json.load(sys.stdin)
    source = payload.get("code", "")
    stdin_text = payload.get("stdin", "")
    max_steps = int(payload.get("max_steps", DEFAULT_MAX_STEPS))
    trace_file = payload.get("trace_file")

    checkpoint = None
    on_step = None
    if trace_file:
        checkpoint = Path(trace_file).open("w", encoding="utf-8", buffering=1)

        def write_checkpoint(step: dict) -> None:
            assert checkpoint is not None
            checkpoint.write(json.dumps(step, ensure_ascii=False, allow_nan=False) + "\n")
            checkpoint.flush()

        on_step = write_checkpoint

    try:
        validate_source(source)
        result = trace_code(
            source,
            stdin_text=stdin_text,
            max_steps=max_steps,
            on_step=on_step,
            capture_items=int(payload.get("capture_items", 50)),
            capture_depth=int(payload.get("capture_depth", 4)),
        )
    except SourceValidationError as error:
        result = {
            "source": source,
            "stdin": stdin_text,
            "steps": [],
            "status": "validation_error",
            "error": {
                "type": "SourceValidationError",
                "message": str(error),
            },
        }

    if checkpoint is not None:
        checkpoint.close()
    json.dump(result, sys.stdout, ensure_ascii=False, allow_nan=False)


if __name__ == "__main__":
    main()
