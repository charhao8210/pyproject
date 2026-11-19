# Code Visual Debugger

English | [繁體中文](README.zh-TW.md)

A local web app that automates tracing a program by hand on paper, built for teaching with small test inputs. Paste a Python or C++17 program and its input, pick what the program does (for example BFS), run it once, and step through every line: how the variables change and what the array, maze, graph, stack, queue, or linked list looks like.

## Features

### Before Run: pick the algorithm

- Cards on the right tell the debugger what the program does: Array simulation, Sorting, Stack, Queue, Linked List, BFS, DFS, Shortest path, Recursion, or Other (let it guess; the drawing may be poor).
- Each card asks plain questions about which variables to draw (BFS asks for the graph, queue, visited, and distance) and pre-fills them from the code. Change any pick, or choose 「不用」 (none) for optional ones.
- Run is disabled until a card is picked; Edit code brings the cards back.

### Views

- **Bars** for arrays and sorting; negative values hang below the zero line, `INF` is a dashed `∞`.
- **Cells** for strings, char arrays, and ragged 2D lists.
- **Grid** for mazes, character maps, and 2D tables, with the current cell, visited cells, frontier, walls, and distances; plain tables show row/column indexes.
- **Graph** with draggable vertices, trees drawn root-down, edge weights, and the edge being checked lit up; directed/undirected can be switched by hand. BFS/DFS draw their queue/stack above the graph or grid.
- **Stack** (top up), **Queue** (front left, back right), **Linked List** (`value | •` boxes with arrows; `head ↓ ∅` for None/nullptr).
- **Recursion tree**.
- The View picker switches the drawing or the drawn variable without re-running (entries marked `(runs again)` re-run once).
- Reading / Changed / New marks show entries the line reads, entries whose value changed, and entries just added. Hover any legend item or mark for its meaning; `/help` has the full guide and glossary (Traditional Chinese).

### Stepping

- The highlighted line is the one about to run; the view, variables, and stdout show the state after it runs (stopped on `vis[v] = true`, v is already ticked).
- `變數 ▾` (Variables) picks variables to draw beside the view: all single values on one card, one card per array or container, values only.
- Input values read once (`n`, `m`) stay above the view.
- Timeline: slider, `←` / `→` for previous/next, `Space` to autoplay (0.25×–2×), `|‹` / `›|` to jump to before/after the current loop.
- A runtime error (RE) stops on the failing line; on a timeout (TLE) or the step limit every step before it is kept. Compile and syntax errors are marked in the editor.

### Editor

- Syntax highlighting and line numbers; pasting code of the other language switches the language (with an undo, 改回).
- Code and test data of both languages are saved in the browser and restored on reload.
- Light/dark theme; every panel can be hidden and resized by dragging its divider.

## Requirements

- Python 3.11 or newer
- `g++` and `gdb` on `PATH` for C++ mode (GCC with libstdc++; see the Chinese README for a Windows MSYS2 setup)
- Windows or Linux; on macOS only Python mode is supported

## Installation

The current version is on the `mvp` branch.

```powershell
git clone -b mvp https://github.com/charhao8210/pyproject.git
cd pyproject
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

On macOS / Linux use `python3 -m venv .venv` and `.venv/bin/python` instead.

## Run

```powershell
.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Then open <http://127.0.0.1:8000>.

1. Choose `Python` or `C++` under Language.
2. Paste the program into Source code and its input into Test data (stdin).
3. Pick a card under 「這個程式在做什麼？」 and check the variables below it.
4. Press `Run as …` (about 1–3 s for Python, 1–30 s for C++).
5. Step with `→` / `←` or the timeline; press Edit code to change the program or the algorithm.

## Test

```powershell
.venv\Scripts\python.exe -m pytest -q
```

C++ tests are skipped automatically when `g++` or `gdb` is not on `PATH`.

## API

- `POST /api/candidates` lists, from the source alone, the variables each card's questions can take (`{"language": "cpp", "code": "..."}`).
- `POST /api/debug` runs the program and returns every step.

```json
{
  "language": "python",
  "code": "a = [3, 1, 2]\na.sort()\nprint(a)",
  "stdin": "",
  "choice": {"algorithm": "array", "variables": {"array": "a"}}
}
```

`language` is `python` or `cpp`. `choice` is optional; without it the backend guesses what to draw (like Other). The response carries `status` (`completed`, `exception`, `step_limit`, `timeout`), `algorithm` (the drawing and the View picker's list), and the ordered `steps`: each step's line, locals, globals, call stack, output so far, exception, and the backend-computed `visualization`.

## Architecture

```text
Browser
  │ POST /api/candidates  list variables for the chosen card
  │ POST /api/debug       run and get every step
  ▼
FastAPI ── language dispatcher
  │
  ├── Python: AST checks → isolated subprocess (-I -S, temporary directory)
  │      └── sys.settrace() records every step; values serialized with object identity
  │
  ├── C++17: g++ -g -O0 → GDB line tracing
  │      ├── source analysis of declarations and scopes, checked against DWARF
  │      ├── STL containers decoded; values no line wrote are reused from the previous step
  │      └── unbuffered stdout, so output lines up with the step that printed it
  │
  ├── analyzer: per-step view models for the chosen algorithm (or a guess)
  │      └── bars, cells, grid, graph, stack, queue, linked list, recursion tree
  ▼
Vanilla JavaScript: source, view, picked variables, stdout, timeline
```

The browser never interprets program semantics; it only draws the JSON the backend computed. Stepping back switches to a saved snapshot; nothing runs in reverse.

## Limitations

- Built for small inputs: at most 5,000 steps are shown. Python runs up to 50,000 steps and 3 s (the page says how many steps ran and how the run ended); C++ up to 30 s, and a line inside a loop stops at most 1,000 times, after which it runs on without stopping and the page names the skipped lines.
- Python can import only `sys` (`stdin`, `exit`, `setrecursionlimit`), `collections` (`deque`, `defaultdict`, `Counter`), `heapq`, `bisect`, and `math`; `open`, `eval`, `exec`, async, threads, file I/O, network, and third-party libraries are not available.
- C++ relies on GCC, GDB, and libstdc++ internals; MSVC's STL and libc++ are not supported. Decoded: `vector` (including `vector<bool>`), `string`, native arrays, `std::array`, `pair`, `queue` / `stack` / `deque`, `priority_queue`, and `set` / `multiset` / `map` / `multimap` of builtin or pair elements. `unordered_*` shows "contents not decoded"; 3D arrays are not read.
- Containers are read up to 50 items and 4 levels deep, strings up to 1,000 characters, output up to 100,000 characters.
- With Other the algorithm is guessed from the code and may be drawn wrong; a graph's direction is guessed too and can be changed above the graph.
- Built-in C implementations such as `list.sort()` hide their comparisons; only the before/after states are shown.
- No user breakpoints, watch expressions, or variable editing.

## Security

This is a teaching tool, **not a secure sandbox**. Python code runs in an isolated subprocess with a time limit, a temporary directory, AST checks, restricted built-ins, and a step limit; C++ code is compiled and run natively under GDB. These reduce accidental damage only. Do not deploy it publicly to run untrusted code.
