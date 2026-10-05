from __future__ import annotations

import os
import shutil
from pathlib import Path


LOCAL_CPP_BIN = Path(__file__).resolve().parent.parent / ".tools" / "msys64" / "ucrt64" / "bin"
_IS_WINDOWS = os.name == "nt"


def resolve_cpp_toolchain() -> tuple[str | None, str | None, dict[str, str]]:
    """Find GNU tools and their child-process environment without changing PATH globally."""
    environment = os.environ.copy()
    inherited_path = environment.get("PATH", "")
    compiler = shutil.which("g++", path=inherited_path)
    debugger = shutil.which("gdb", path=inherited_path)
    if _IS_WINDOWS and (not compiler or not debugger):
        local_path = str(LOCAL_CPP_BIN)
        compiler = compiler or shutil.which("g++", path=local_path)
        debugger = debugger or shutil.which("gdb", path=local_path)

    compiler = str(Path(compiler).resolve()) if compiler else None
    debugger = str(Path(debugger).resolve()) if debugger else None
    # The inferior runs in a temporary directory. Its GNU runtime DLLs, and the
    # compiler/debugger's helper programs, must remain reachable there too.
    tool_directories = list(dict.fromkeys(
        str(Path(tool).parent) for tool in (compiler, debugger) if tool
    ))
    if tool_directories:
        environment["PATH"] = os.pathsep.join([*tool_directories, inherited_path])
    return compiler, debugger, environment
