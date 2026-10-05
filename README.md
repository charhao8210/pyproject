# Code Visual Debugger

English | [繁體中文](README.zh-TW.md)

[Changelog and next improvements](CHANGELOG.md)

A clean, local web app for exploring how Python and C++ programs execute. Choose a language, paste a program, provide optional standard input, run it once, and browse immutable execution snapshots with forward/backward controls. Each snapshot includes the current source line, important local variables, object identity, call stack, cumulative stdout, and exception details.

The debugger combines execution tracing with heuristic algorithm detection. Focused views keep the current operation readable; completed DFS branches fold into summaries that can be expanded. Available views include grids/DP, graphs, arrays/sorting, recursion, union-find, segment trees, and six additional algorithm lenses: heap, sliding window, monotonic stack/deque, Fenwick tree, string matching/KMP, and trie.

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
  │      ├── native arrays, STL sequence/ordered containers, and global extraction
  │      └── unbuffered stdout so output lines up with the step that printed it
  │
  ├── heuristic algorithm analysis
  │      ├── data-structure views plus algorithm-specific lenses
  │      ├── explicit variable-role pairing
  │      └── recorded operation and navigation indexes
  │
  ▼
Vanilla JavaScript renderer
  ├── source line viewer
  ├── variables and data structures
  ├── focused graph / recursion / tree views
  ├── line, event, call, return, and change navigation
  └── stdout plus inline RE/TLE status
```

The browser never interprets Python execution semantics. It only renders the JSON trace and algorithm-specific view models returned by the backend. Step backward is snapshot navigation; Python is not reverse-executed.

## Using the debugger

1. Choose Python or C++ in the language selector, paste code and optional **輸入** (Input), then press **執行** (Run). **選擇範例** (Choose example) loads a local example and its input into the editor.
2. Use the **自動** (Auto) view selector and its variable selector to choose a captured structure. The default **聚焦** (Focus) emphasizes the current operation. DFS/recursion shows the current call path and folds completed branches; expand a branch or select a call to inspect its recorded entry/last step. **呼叫鏈** (Call chain) provides the active calls alone.
3. **跟隨** (Follow) keeps the current node, cell, or captured-value page visible. Turn it off to inspect a fixed position. Turn Focus off for the full available structure.
4. The timeline's **逐行** (Line) visits adjacent snapshots. **重要事件** (Important events), **函式呼叫** (Calls), **函式返回** (Returns), and **資料變更** (Data changes) jump between matching recorded events. **跳過呼叫** (Skip call) jumps to the current call's recorded ending when one exists. These controls also affect playback; the slider still accesses individual snapshots.
5. Open **⚙ 顯示設定** (Display settings) when detection or variable names are ambiguous. Select an **演算法模式**, pair variables with their roles, and press **套用** (Apply). This reruns the current program and input. Roles are variable names, not watch expressions: examples include primary data, left/right bounds, queue, distance/indegree, parent, lazy tags, text, pattern, and prefix table. Leave a role on **自動** for automatic detection. Escape closes settings and returns focus to the gear button.

The chart header shows the structure, variable and size; a single operation line shows the current read or change. Expand it for complete formulas, candidates and dependencies. Detection details and the shared bar scale are inside settings. **▾/▸** collapses or expands panels. Missing captures, off-page markers and carried states remain visible.

Focus highlights recorded reads/writes and keeps unrelated state subdued. DP grids add coordinates and dependencies; graphs show relevant neighbors and queue entries; sorting retains a consistent scale; union-find shows parent chains; segment trees show query coverage and captured lazy tags when available. A returned call is labelled returned, not automatically called a pruned branch or a found solution.

### Additional algorithm modes and examples

| Mode | What the view shows | Local example |
| --- | --- | --- |
| Heap / Priority queue | Indexed storage and parent/child tree, synchronized selection, captured top | [sample8_heap.py](samples/sample8_heap.py) |
| Sliding window | Boundary indices, active interval, captured aggregate | [sample9_sliding_window.py](samples/sample9_sliding_window.py) |
| Monotonic stack / deque | Container order, source indices when available, changes between captures | [sample10_monotonic_stack.py](samples/sample10_monotonic_stack.py) |
| Fenwick / BIT | Indexed aggregates, covered ranges, accessed indices | [sample11_fenwick.py](samples/sample11_fenwick.py) |
| String matching / KMP | Text/pattern alignment, actual comparison, captured prefix/failure table | [sample12_kmp.py](samples/sample12_kmp.py) |
| Trie | Prefix hierarchy, edge letters, captured terminal markers, foldable branches | [sample13_trie.py](samples/sample13_trie.py) |

The heap example implements its operations in Python so its user-code steps can be traced. Real `heapq` calls are also supported, but library-internal sifts and built-in sort comparisons are not reconstructed. Heap storage order is not sorted output order.

### Capture limits

Display settings offer **50 / 100 / 200 / 500** captured items per container (default 50) and Python nesting depths **2 / 3 / 4 / 6 / 8** (default 4). The API accepts `capture_items` from 10–500 and Python `capture_depth` from 2–8. Increasing a limit and applying settings reruns the program; it does not recover values from an old trace. C++ sequence capture uses the item limit; C++ table extraction remains capped at **30 rows × 40 columns** and does not use Python's depth setting.

Python's default time budget is three seconds. Larger capture settings receive a proportional budget, capped at fifteen seconds, to allow snapshot serialization; the 5,000-step limit remains in place. C++ keeps its ten-second budget.

Paging and folding navigate retained data only. Clipped, missing, and out-of-scope values remain explicit; a view never fills unknown cells with assumed zeros or invents unrecorded operations.

## Requirements

- Python 3.11 or newer
- `g++` and `gdb` when using C++ mode: on `PATH`, or a complete Windows UCRT64 toolchain in `.tools/msys64/ucrt64`
- Windows, macOS, or Linux

## Installation

### Windows PowerShell

For C++ mode, tools on `PATH` take priority. Missing tools can also be found in the project-local `.tools/msys64/ucrt64/bin` directory. Keep the full MSYS2 toolchain and its dependencies; copying only the two executables is insufficient. Restart Uvicorn after updating application code. The `.tools` directory is ignored by Git.

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

The suite covers tracing, recursion, object identity, exceptions, partial traces, capture limits, algorithm lenses, supported Python standard-library imports, C++ source/GDB container parsing, frontend contracts, and the API. It detects tools on `PATH` and the Windows project-local toolchain. C++ tests are skipped automatically when either `g++` or `gdb` is unavailable in both locations.

## API

`POST /api/debug`

```json
{
  "language": "python",
  "code": "value = int(input())\nprint(value * 2)",
  "stdin": "21\n",
  "capture_items": 50,
  "capture_depth": 4,
  "bindings": {}
}
```

The `language` field accepts `python` or `cpp`. `bindings` can name roles, for example `{"mode":"window","primary":"nums","left":"left","right":"right","total":"total"}`. The response contains the original `source`, `stdin`, language, ordered `steps`, execution `status`, detected `algorithm`, and an optional top-level `error`. Each step records its source location, current-frame locals, filtered user call stack, cumulative stdout, exception/return data, and view models. `GET /api/examples` lists the bundled examples.

## Supported Python features

- Assignment, arithmetic, conditionals, `for`, and `while`
- Lists, tuples, dictionaries, sets, and circular/shared references
- Functions and recursion
- `input()` and `sys.stdin.read()` using the Test data field
- `print()` with cumulative stdout snapshots
- Python exceptions, including uncaught-exception visualization
- A practical subset of safe built-ins such as `range`, `len`, `sum`, and `sorted`
- Restricted algorithm standard-library imports: `sys.stdin`, public `heapq` and `bisect` operations, `collections.deque/defaultdict/Counter`, and public mathematical functions/constants from `math`. Both module imports and explicit member imports/aliases work; private members, wildcard imports, and other modules are rejected.
- Heuristic detection for grid traversal, DFS/BFS, recursion, binary search, three-sum/two-pointer search, sorting, dynamic-programming tables, and general array/matrix processing
- Grid, graph, Bars/Cells, Recursion tree/Call chain, union-find, segment tree, and the six additional modes listed above
- RE, step-limit, and TLE runs preserve the steps collected before execution stopped
- The Variables panel ranks algorithm-relevant state and suppresses common transient implementation details

## Current limitations

- Python imports are limited to the algorithm allowlist above; a member must exist in the running Python version.
- Async code, threads, and multiprocessing are not supported.
- File I/O, network access, GUI libraries, NumPy, pandas, and third-party libraries are outside the MVP.
- There are no user breakpoints, watch expressions, variable editing, `pdb` integration, or control-flow graphs.
- The Variables panel shows the current frame's locals plus unshadowed globals (tagged `global`). Use Call chain or Recursion tree to inspect the active call path.
- Algorithm detection is heuristic. The UI labels it “guessed from the code”; use variable pairing to correct a match. A mode still needs compatible captured data and source structure.
- `list.sort()`, C-backed `heapq` operations, and C++ library internals do not expose a complete sequence of internal operations. Their observed inputs/results can be displayed; comparisons, swaps, sifts, pruning, and solutions are labelled only when supported by recorded user-code events/state.
- Object IDs are used internally to preserve identity, but the UI deliberately displays stable labels such as `List #1` instead of memory addresses.
- A trace contains at most 5,000 snapshots. Container capture defaults to 50 items and Python nesting to four levels; configurable limits are described above. Captured stdout is capped at 100,000 characters. Large trees also have bounded display/layout sizes.
- C++ mode uses `g++ -g -O0` and GDB. It extracts supported scalars, strings, native arrays, vectors (including `vector<bool>`, pairs, strings, and nested/adjacency vectors), namespace-scope state, plus supported `deque`, default deque-backed `queue/stack`, vector-backed `priority_queue`, ordered `set/multiset`, and `map/multimap` values. Function calls, stdin, stdout, and uncaught exceptions/signals are traced.
- C++ extraction depends on libstdc++ layouts. libc++ and MSVC STL need another adapter. Unordered containers and unsupported element types/adaptor storage still appear as undecoded container values.
- C++ sequences use the configured capture-item limit; nested tables and `adj[N]` remain capped at 30 × 40. Large native arrays are read in bounded slices instead of evaluating the entire GDB value.
- Default execution limits are three seconds for Python and ten seconds for C++. Large C++ containers need additional GDB commands per step; a partial trace is returned on timeout.

## Security limitations

This project is a teaching tool, **not a secure sandbox**. User code runs in a separate isolated-mode Python subprocess with a bounded timeout, a temporary working directory, restricted built-ins and algorithm-module namespaces, AST checks, and a trace-step limit. These controls reduce accidental damage but are not a hardened security boundary and must not be used to execute untrusted hostile code on a public server.
