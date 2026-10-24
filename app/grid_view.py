"""The grid view: a character map or 2D table with visited, frontier, and current cells."""
from __future__ import annotations

from typing import Any, Callable

from .values import (
    MAX_VISUAL_ITEMS,
    is_grid,
    is_index,
    is_infinity,
    is_number,
    normalize_grid,
    preferred_values,
    scope_lookup,
    unique_names,
    used_rows,
)


MAX_VISUAL_ROWS = 30
MAX_VISUAL_COLUMNS = 40
# Same-shaped grids that mark a cell as reached when they hold anything for it.
REACHED_GRID_NAMES = ("mov", "move", "moves", "back", "from", "pre", "prev", "par", "parent", "dist", "dis", "d", "step", "steps")
FRONTIER_NAMES = frozenset({"q", "queue", "que", "pq", "st", "stack", "frontier", "dq"})


def grid_visualization(
    scope: dict[str, Any],
    step: dict[str, Any],
    name: str | None = None,
    extents: dict[str, tuple[int, int]] | None = None,
    reached_rules: dict[str, str] | None = None,
) -> dict[str, Any]:
    if name is None:
        # A character map (the maze, the board) is the grid; tables beside it only mark it.
        grid_name, grid = _character_map(scope)
        if grid is None:
            grid_name, grid = _find_grid(scope)
    else:
        value = scope.get(name)
        grid_name, grid = (name, value) if is_grid(value) else (None, None)
    if grid is None:
        return {"renderer": "grid", "ready": False}
    rows = normalize_grid(used_rows(grid))
    names = [grid_name]
    walls = _wall_cells(rows)
    # A character map (`a`) and a number table (`dp`) are drawn as one grid: the map
    # while the table is still all zero (the input is being read), then the table's
    # numbers with the map's walls kept in place.
    pair = _map_and_table(scope) if name is None else None
    if pair is not None:
        (map_name, map_rows), (table_name, table_rows) = pair
        walls = _wall_cells(map_rows)
        filled = any(_has_content(cell) for row in table_rows for cell in row)
        height = max(len(map_rows), len(table_rows))
        width = max((len(row) for row in [*map_rows, *table_rows]), default=0)
        rows = [
            [
                _cell(map_rows, row, column, "\0")
                if (row, column) in walls or not filled
                else _cell(table_rows, row, column, 0)
                for column in range(width)
            ]
            for row in range(height)
        ]
        grid_name = table_name if filled else map_name
        names = [table_name, map_name]
    # The largest part used anywhere in the trace keeps the grid one size from start to end,
    # including while the input is still being read into it.
    used = [(extents or {}).get(variable, (0, 0)) for variable in names]
    blank = "\0" if any(isinstance(cell, str) for row in rows for cell in row) or not rows else 0
    target_height = max([len(rows), *(height for height, _ in used)])
    target_width = max([max((len(row) for row in rows), default=0), *(width for _, width in used)])
    rows = [
        list(row) + [blank] * (target_width - len(row))
        for row in rows + [[] for _ in range(target_height - len(rows))]
    ]
    full_height = len(rows)
    full_width = max((len(row) for row in rows), default=0)
    row_count = _visible_extent(
        full_height,
        [index for index, row in enumerate(rows) if any(_has_content(cell) for cell in row)]
        + [height - 1 for height, _ in used if height],
        scope.get("n"),
        MAX_VISUAL_ROWS,
    )
    column_count = _visible_extent(
        full_width,
        [index for row in rows for index, cell in enumerate(row) if _has_content(cell)]
        + [width - 1 for _, width in used if width],
        scope.get("m", scope.get("n")),
        MAX_VISUAL_COLUMNS,
    )
    if not row_count or not column_count:
        return {"renderer": "grid", "ready": False}
    captured_rows = rows
    rows = [row[:column_count] for row in rows[:row_count]]

    visited_name, visited = _find_visited(scope, row_count, column_count, reached_rules)
    # A wall is never visited, whatever value a table keeps for it.
    for row, column in walls:
        if row < row_count and column < column_count:
            visited[row][column] = False
    active, active_names, coordinates = _active_cells(scope, row_count, column_count)
    frontier_name, frontier = _frontier_cells(scope, row_count, column_count)
    queue = scope.get(frontier_name) if frontier_name else None
    return {
        "renderer": "grid",
        "ready": True,
        "name": grid_name,
        "uses": unique_names([*names, visited_name, *active_names, frontier_name]),
        "rows": rows,
        "captured_rows": captured_rows,
        "full_height": full_height,
        "full_width": full_width,
        "walls": [
            {"row": row, "column": column}
            for row, column in sorted(walls)
            if row < row_count and column < column_count
        ],
        "visited": visited,
        "active": active,
        "frontier": frontier,
        # Coordinates as numbers and the queue in its order: the coloured cells alone show
        # neither which variable holds a cell nor which cell leaves the queue next.
        "coordinates": coordinates,
        "queue": (
            {"name": frontier_name, "entries": [f"({item[0]}, {item[1]})" for item in queue[:MAX_VISUAL_ITEMS]]}
            if isinstance(queue, list)
            else None
        ),
        "truncated": full_height > MAX_VISUAL_ROWS or full_width > MAX_VISUAL_COLUMNS,
        "event": step.get("event"),
    }


WALL_CHARACTERS = frozenset("#*")


def grid_extents(scopes: list[dict[str, Any]]) -> dict[str, tuple[int, int]]:
    """Rows and columns holding data in each 2D array (and the used length of each 1D
    array, as `(length, 0)`) over the whole trace."""
    extents: dict[str, tuple[int, int]] = {}
    measured: dict[int, tuple[int, int]] = {}
    for scope in scopes:
        for name, value in scope.items():
            if not isinstance(value, list) or not value:
                continue
            if not all(isinstance(row, (list, str)) for row in value):
                if id(value) not in measured:
                    used = max((index for index, item in enumerate(value) if _has_content(item)), default=-1) + 1
                    measured[id(value)] = (used, 0)
                previous = extents.get(name, (0, 0))
                extents[name] = (max(previous[0], measured[id(value)][0]), 0)
                continue
            if id(value) not in measured:
                rows = normalize_grid(used_rows(value))
                content = [
                    (row_index, column_index)
                    for row_index, row in enumerate(rows)
                    for column_index, cell in enumerate(row)
                    if _has_content(cell)
                ]
                measured[id(value)] = (
                    max((row for row, _ in content), default=-1) + 1,
                    max((column for _, column in content), default=-1) + 1,
                )
            height, width = measured[id(value)]
            previous = extents.get(name, (0, 0))
            extents[name] = (max(previous[0], height), max(previous[1], width))
    return extents


def _character_map(scope: dict[str, Any]) -> tuple[str | None, list[Any] | None]:
    """The first character grid that is not a search's bookkeeping (`mov`, `vis`)."""
    skip = {"vis", "visited", "seen", *REACHED_GRID_NAMES}
    for name, value in preferred_values(scope, ("grid", "board", "maze", "matrix", "map", "mp", "a", "s", "g")):
        if name.lower() in skip or not isinstance(value, list) or not value:
            continue
        if not all(isinstance(row, str) for row in value):
            continue
        # Before the input is read a C++ char grid is all empty rows; it is still the map.
        if is_grid(value) or all(row == "" for row in value):
            return name, value
    return None, None


def _map_and_table(
    scope: dict[str, Any],
) -> tuple[tuple[str, list[list[Any]]], tuple[str, list[list[Any]]]] | None:
    """A character grid plus a numeric grid, as in grid DP (`a` and `dp`)."""
    character_grid = number_grid = None
    for name, value in preferred_values(scope, ("grid", "board", "maze", "matrix", "a", "dp")):
        if name.lower() in {"vis", "visited", "seen"}:
            continue
        # A C++ char grid before any input is read: every row is still an empty string.
        if (
            character_grid is None
            and isinstance(value, list)
            and value
            and all(row == "" for row in value)
        ):
            character_grid = (name, [])
            continue
        if not is_grid(value):
            continue
        rows = normalize_grid(used_rows(value))
        cells = [cell for row in rows for cell in row]
        if character_grid is None and all(isinstance(cell, str) and len(cell) <= 1 for cell in cells):
            character_grid = (name, rows)
        elif number_grid is None and all(is_number(cell) for cell in cells):
            number_grid = (name, rows)
    if character_grid is None or number_grid is None:
        return None
    # The table must cover the map, which rules out small tables such as `dirs`.
    map_rows, table_rows = character_grid[1], number_grid[1]
    if len(table_rows) < len(map_rows) or max(map(len, table_rows), default=0) < max(map(len, map_rows), default=0):
        return None
    return character_grid, number_grid


def _wall_cells(rows: list[list[Any]]) -> set[tuple[int, int]]:
    return {
        (row_index, column_index)
        for row_index, row in enumerate(rows)
        for column_index, cell in enumerate(row)
        if isinstance(cell, str) and cell in WALL_CHARACTERS
    }


def _cell(rows: list[list[Any]], row: int, column: int, blank: Any) -> Any:
    if row < len(rows) and column < len(rows[row]):
        return rows[row][column]
    return blank


def _has_content(cell: Any) -> bool:
    if isinstance(cell, list):
        return any(_has_content(item) for item in cell)
    return cell not in (0, "", "\0", None) and cell is not False


def _visible_extent(size: int, content: list[int], count: Any, cap: int) -> int:
    """How much of a grid dimension to draw.

    A dimension that reaches the visual cap is a fixed-size C++ array (`dp[1005][1005]`);
    it is cut to the cells that hold data, and at least to `n` once `n` is read.
    Smaller grids are the program's own size and are drawn whole.
    """
    if size < cap:
        return size
    used = max(content) + 1 if content else 0
    if is_index(count) and 0 < count <= size:
        used = max(used, count)
    return min(size, used)


def _find_grid(scope: dict[str, Any]) -> tuple[str | None, list[Any] | None]:
    for name, value in preferred_values(
        scope,
        ("grid", "board", "maze", "matrix", "dp", "a"),
    ):
        # A queue of (row, col) pairs is the frontier drawn on a grid, not the grid itself.
        if is_grid(value) and name.lower() not in {"vis", "visited", "seen"} | FRONTIER_NAMES:
            return name, value
    return None, None


def _find_visited(
    scope: dict[str, Any],
    rows: int,
    columns: int,
    reached_rules: dict[str, str] | None = None,
) -> tuple[str | None, list[list[bool]]]:
    for name in ("vis", "visited", "seen"):
        value = scope.get(name)
        if not isinstance(value, list) or len(value) < rows:
            continue
        if all(isinstance(row, list) and len(row) >= columns for row in value[:rows]):
            return name, [
                [bool(cell) for cell in row[:columns]]
                for row in value[:rows]
            ]
    for name in REACHED_GRID_NAMES:
        key, value = scope_lookup(scope, name)
        rows_of = normalize_grid(used_rows(value)) if isinstance(value, list) else []
        reached = _reached_test([cell for row in rows_of for cell in row], (reached_rules or {}).get(key))
        if reached is None:
            continue
        marks = [
            [reached(rows_of[row][column]) if row < len(rows_of) and column < len(rows_of[row]) else False
             for column in range(columns)]
            for row in range(rows)
        ]
        if any(any(row) for row in marks):
            return key, marks
    return None, [[False] * columns for _ in range(rows)]


def find_reached_rules(scopes: list[dict[str, Any]]) -> tuple[tuple[str, str], ...]:
    """For each distance table, how it marks "not reached", from every step of the trace.

    Once the last `-1` is gone (every cell reached), the table alone would look like a
    "0 means unreached" table and the start (distance 0) would lose its mark; the rule found
    while the search ran holds to the end.
    """
    rules: dict[str, str] = {}
    measured: set[int] = set()
    for scope in scopes:
        for name in REACHED_GRID_NAMES:
            key, value = scope_lookup(scope, name)
            if not isinstance(value, list) or id(value) in measured:
                continue
            measured.add(id(value))
            cells = [cell for row in value if isinstance(row, list) for cell in row if is_number(cell)]
            if any(cell < 0 for cell in cells):
                rules[key] = "negative"
            elif rules.get(key) != "negative" and any(is_infinity(cell) for cell in cells):
                rules[key] = "infinity"
    return tuple(sorted(rules.items()))


def _reached_test(cells: list[Any], rule: str | None = None) -> Callable[[Any], bool] | None:
    """How to tell a reached cell in a distance table, from the value it starts with.

    `-1` (or any negative) or an `INF` constant marks "not reached", so 0 (the start)
    counts as reached. A table with neither (0 means unreached) marks only nonzero cells.
    `rule` is that choice made over the whole trace (`find_reached_rules`). Anything else (not
    all numbers) cannot be read reliably and marks nothing.
    """
    numbers = [cell for cell in cells if is_number(cell)]
    if not numbers or len(numbers) != len(cells):
        return None
    if rule in {"negative", "infinity"} and not any(numbers):
        # Still all zero: the table is not filled with its "not reached" value yet (before
        # `memset(dist, -1, ...)`), so nothing has been reached.
        return None
    if rule == "negative" or (rule is None and any(number < 0 for number in numbers)):
        return lambda cell: is_number(cell) and cell >= 0
    if rule == "infinity" or (rule is None and any(is_infinity(number) for number in numbers)):
        return lambda cell: is_number(cell) and not is_infinity(cell)
    return lambda cell: is_number(cell) and cell != 0


def _active_cells(
    scope: dict[str, Any],
    rows: int,
    columns: int,
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    """Cells the code is at (`row, col`, a pair `cur`), the names it read them from, and a
    readout per coordinate pair (`row,col = (0, 1)`), also for one off the grid (`nr = -1`),
    which keeps the names out of Variables whether or not the cell is on the grid."""
    # Code that walks with (c, r) uses c for the row, so nc/nr follow that order.
    new_cell = ("nc", "nr") if "c" in scope and "r" in scope else ("nr", "nc")
    patterns = (
        ("row", "col", "current"),
        ("i", "j", "scan"),
        ("c", "r", "current"),
        ("new_row", "new_col", "candidate"),
        (*new_cell, "candidate"),
        ("nx", "ny", "candidate"),
        ("wc", "wr", "candidate"),
        ("x", "y", "current"),
    )
    cells: list[dict[str, Any]] = []
    names: list[str] = []
    readouts: list[str] = []
    seen: set[tuple[int, int, str]] = set()
    # A cell held as a pair: `pii now = q.front();`
    for name in ("now", "cur", "current", "cell", "top", "front", "u"):
        value = scope.get(name)
        if (
            isinstance(value, list)
            and len(value) == 2
            and all(is_index(item) for item in value)
            and 0 <= value[0] < rows
            and 0 <= value[1] < columns
        ):
            names.append(name)
            readouts.append(f"{name} = ({value[0]}, {value[1]})")
            seen.add((value[0], value[1], "current"))
            cells.append({"row": value[0], "column": value[1], "role": "current"})
            break
    for row_name, column_name, role in patterns:
        row, column = scope.get(row_name), scope.get(column_name)
        if not is_index(row) or not is_index(column):
            continue
        names.extend((row_name, column_name))
        inside = 0 <= row < rows and 0 <= column < columns
        readouts.append(f"{row_name},{column_name} = ({row}, {column}){'' if inside else ' off the grid'}")
        if not inside:
            continue
        marker = (row, column, role)
        if marker not in seen:
            cells.append({"row": row, "column": column, "role": role})
            seen.add(marker)
    return cells, names, readouts


def _frontier_cells(
    scope: dict[str, Any],
    rows: int,
    columns: int,
) -> tuple[str | None, list[dict[str, int]]]:
    def cell_list(value: Any) -> bool:
        return isinstance(value, list) and all(
            isinstance(item, list) and len(item) == 2 and all(is_index(part) for part in item)
            for item in value
        )

    frontier_name = next(
        (name for name in ("stack", "queue", "frontier", "q", "que", "st") if cell_list(scope.get(name))),
        None,
    ) or next(
        (name for name, value in scope.items() if value and cell_list(value)),
        None,
    )
    frontier = scope[frontier_name] if frontier_name else []
    cells = []
    for item in frontier[:MAX_VISUAL_ITEMS]:
        if (
            isinstance(item, list)
            and len(item) >= 2
            and isinstance(item[0], int)
            and isinstance(item[1], int)
            and 0 <= item[0] < rows
            and 0 <= item[1] < columns
        ):
            cells.append({"row": item[0], "column": item[1]})
    return frontier_name, cells
