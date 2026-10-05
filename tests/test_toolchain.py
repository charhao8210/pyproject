import os
from pathlib import Path

import pytest

from app import toolchain


def _tool(directory: Path, name: str) -> str:
    directory.mkdir(parents=True, exist_ok=True)
    executable = directory / (name + (".exe" if os.name == "nt" else ""))
    executable.write_bytes(b"")
    executable.chmod(0o755)
    return str(executable.resolve())


def test_existing_path_tools_take_priority_over_local_fallback(monkeypatch, tmp_path):
    compiler_bin = tmp_path / "compiler"
    debugger_bin = tmp_path / "debugger"
    inherited_path = os.pathsep.join([str(compiler_bin), str(debugger_bin)])
    local = tmp_path / "local"
    compiler = _tool(compiler_bin, "g++")
    debugger = _tool(debugger_bin, "gdb")
    _tool(local, "g++")
    _tool(local, "gdb")
    monkeypatch.setattr(toolchain, "_IS_WINDOWS", True)
    monkeypatch.setattr(toolchain, "LOCAL_CPP_BIN", local)
    monkeypatch.setenv("PATH", inherited_path)
    monkeypatch.setenv("PVDBG_TEST_ENV", "preserved")

    found_compiler, found_debugger, environment = toolchain.resolve_cpp_toolchain()

    assert (found_compiler, found_debugger) == (compiler, debugger)
    assert environment["PVDBG_TEST_ENV"] == "preserved"
    assert environment["PATH"].split(os.pathsep)[:2] == [str(compiler_bin), str(debugger_bin)]
    assert str(local) not in environment["PATH"].split(os.pathsep)
    assert os.environ["PATH"] == inherited_path
    assert environment is not os.environ


@pytest.mark.parametrize("is_windows", [False, True])
def test_local_fallback_is_windows_only_and_supplies_dll_path(monkeypatch, tmp_path, is_windows):
    inherited = tmp_path / "empty"
    inherited.mkdir()
    local = tmp_path / "local"
    compiler = _tool(local, "g++")
    debugger = _tool(local, "gdb")
    monkeypatch.setattr(toolchain, "_IS_WINDOWS", is_windows)
    monkeypatch.setattr(toolchain, "LOCAL_CPP_BIN", local)
    monkeypatch.setenv("PATH", str(inherited))

    found_compiler, found_debugger, environment = toolchain.resolve_cpp_toolchain()

    assert (found_compiler, found_debugger) == ((compiler, debugger) if is_windows else (None, None))
    expected_path = [str(local), str(inherited)] if is_windows else [str(inherited)]
    assert environment["PATH"].split(os.pathsep) == expected_path
    assert os.environ["PATH"] == str(inherited)


@pytest.mark.parametrize("local_debugger", [False, True])
def test_missing_compiler_is_not_hidden_by_local_debugger(monkeypatch, tmp_path, local_debugger):
    inherited = tmp_path / "empty"
    inherited.mkdir()
    local = tmp_path / "local"
    expected_debugger = _tool(local, "gdb") if local_debugger else None
    monkeypatch.setattr(toolchain, "_IS_WINDOWS", True)
    monkeypatch.setattr(toolchain, "LOCAL_CPP_BIN", local)
    monkeypatch.setenv("PATH", str(inherited))

    compiler, debugger, _ = toolchain.resolve_cpp_toolchain()

    assert compiler is None
    assert debugger == expected_debugger
