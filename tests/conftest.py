"""Make the project's local GNU tools available to C++ test collection."""
import os

from app.toolchain import resolve_cpp_toolchain


compiler, debugger, environment = resolve_cpp_toolchain()
if compiler and debugger:
    # Existing skip markers use shutil.which at import time. This only changes
    # the pytest process; application requests keep their own environment copies.
    os.environ["PATH"] = environment["PATH"]
