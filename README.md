# Code Visual Debugger

A clean, local web app for exploring how Python and C++ programs execute. Choose a language, paste a program, provide optional standard input, run it once, and browse immutable execution snapshots with forward/backward controls. Each snapshot includes the current source line, important local variables, object identity, call stack, cumulative stdout, and exception details.

The debugger combines generic execution tracing with heuristic algorithm detection. It can switch between grid, draggable graph, array-bar, recursive-call, and generic execution views.

## Architecture

```text
Browser
  │ POST /api/debug
  ▼
FastAPI ── language dispatcher
  │
  ├── isolated Python subprocess (-I -S, temporary working directory)
  │      │
  │      ├── sys.settrace() for call / line / return / exception
  │      ├── bounded value serialization with object identity
  │      └── JSON snapshots
  │
  ├── C++17 compilation and GDB line tracing (temporary working directory)
  │      ├── lexical declaration analysis + GDB `info scope` (DWARF) checks
  │      ├── vector, vector<bool>, nested-vector, vector-array, and global extraction
  │      └── unbuffered stdout so output lines up with the step that printed it
  │
  ├── heuristic algorithm analysis
  │      ├── grid / matrix renderer
  │      ├── array renderer
  │      ├── graph renderer
  │      └── recursion renderer
  │
  ▼
Vanilla JavaScript renderer
  ├── source line viewer
  ├── variables and data structures
  ├── draggable SVG object-reference graph
  ├── call stack
  └── stdout plus inline RE/TLE status
```

The browser never interprets Python execution semantics. It only renders the JSON trace and algorithm-specific view models returned by the backend. Step backward is snapshot navigation; Python is not reverse-executed.

## Requirements

- Python 3.11 or newer
- `g++` and `gdb` on `PATH` when using C++ mode
- Windows, macOS, or Linux

## Installation

### Windows PowerShell

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

If PowerShell blocks the activation script, either adjust the current user's execution policy or run the virtual-environment executables directly:

```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## Run

From the project root:

```powershell
uvicorn app.main:app --reload
```

Then open <http://127.0.0.1:8000>. The page starts with a reference-sharing example, ready to run.

Without activating the Windows virtual environment:

```powershell
.venv\Scripts\uvicorn.exe app.main:app --reload
```

## Test

```powershell
pytest -q
```

The suite covers basic tracing, function calls, recursion, object identity, circular references, exceptions, partial traces on timeout, step limiting, cumulative stdout, forbidden imports, C++ source analysis and GDB value parsing, C++ STL vectors (including `vector<bool>`, parameters, aliases, and scope boundaries), C++ runtime errors, global adjacency arrays, C++ graph/three-sum visualization, frontend contracts, and the API. C++ tests are skipped automatically when `g++` or `gdb` is not on `PATH`.

## API

`POST /api/debug`

```json
{
  "language": "python",
  "code": "value = int(input())\nprint(value * 2)",
  "stdin": "21\n"
}
```

The `language` field accepts `python` or `cpp`. The response contains the original `source`, `stdin`, language, an ordered `steps` array, execution `status`, detected `algorithm`, and an optional top-level `error`. Each step records its event, source location, current-frame locals, filtered user call stack, stdout so far, exception/return data when applicable, and a backend-generated visualization model.

## Supported Python features

- Assignment, arithmetic, conditionals, `for`, and `while`
- Lists, tuples, dictionaries, sets, and circular/shared references
- Functions and recursion
- `input()` and `sys.stdin.read()` using the Test data field
- `print()` with cumulative stdout snapshots
- Python exceptions, including uncaught-exception visualization
- A practical subset of safe built-ins such as `range`, `len`, `sum`, and `sorted`
- Heuristic detection for grid traversal, DFS/BFS, recursion, binary search, three-sum/two-pointer search, sorting, dynamic-programming tables, and general array/matrix processing
- Specialized grid, draggable graph, array-bar, and recursive-call renderers
- RE, step-limit, and TLE runs preserve the steps collected before execution stopped
- The Variables panel ranks algorithm-relevant state and suppresses common transient implementation details

## Current limitations

- Imports other than the restricted `sys` input shim are rejected.
- Async code, threads, and multiprocessing are not supported.
- File I/O, network access, GUI libraries, NumPy, pandas, and third-party libraries are outside the MVP.
- There are no user breakpoints, watch expressions, variable editing, `pdb` integration, or control-flow graphs.
- The Variables panel shows the current frame's locals plus unshadowed globals (tagged `global`). Other active frames appear only in the Call Stack panel.
- Algorithm detection is heuristic. The confidence and evidence shown in the UI describe the match; unfamiliar or ambiguous programs fall back to the generic execution view.
- Built-in C implementations such as `list.sort()` do not expose their internal comparisons to `sys.settrace()`, so only their before/after states can be displayed.
- Object IDs are used internally to preserve identity, but the UI deliberately displays stable labels such as `List #1` instead of memory addresses.
- A trace can contain at most 5,000 snapshots. Serialized containers are limited to 50 items and four levels of depth. Captured stdout is capped at 100,000 characters.
- C++ mode uses debug symbols from `g++ -g -O0` and GDB. Scalars, `std::string`, native arrays, `std::vector<T>` (including `vector<bool>`, `vector<pair<...>>`, and `vector<string>`), `vector<vector<T>>`, `vector<T> adj[N]` adjacency arrays, namespace-scope variables, `typedef`/`using`/`#define` vector aliases, function calls, standard input, and stdout are supported. Uncaught C++ exceptions and signals such as `SIGSEGV` are reported as runtime errors on the last traced line.
- C++ value extraction depends on libstdc++ internals (`_M_impl._M_start` and the `std::vector<bool>` bit-iterator layout). libc++ or MSVC's STL would need another adapter. `deque`, `queue`, `stack`, `map`, `set`, and similar containers are shown as undecoded "STL container" values.
- C++ vectors and tables are clipped to 50 items; nested vectors and `adj[N]` arrays to 30 rows × 40 columns. Local native arrays larger than GDB's 64 KiB `max-value-size` are hidden, while large global arrays are sliced.
- Each extracted C++ container costs extra GDB commands at every step, so traces with many large containers reach the three-second limit sooner. The partial trace is still returned.

## Security limitations

This project is a teaching tool, **not a secure sandbox**. User code runs in a separate isolated-mode Python subprocess with a three-second timeout, a temporary working directory, a restricted built-in set, a stdin-only `sys` shim, AST checks, and a trace-step limit. These controls reduce accidental damage but are not a hardened security boundary and must not be used to execute untrusted hostile code on a public server.
