"""Lightweight C++ source analysis used to drive GDB value extraction.

The tracer cannot recover from a GDB error inside a breakpoint command list, so
every expression it emits must be valid at that breakpoint. This module finds
vector declarations, their lexical lifetimes, type aliases, and namespace-scope
variables. The runner then intersects these lexical facts with GDB's DWARF
scope information before generating any expression.
"""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass, field, replace


FUNDAMENTAL_TYPES = frozenset(
    {
        "bool",
        "char",
        "signed char",
        "unsigned char",
        "wchar_t",
        "short",
        "short int",
        "unsigned short",
        "short unsigned int",
        "int",
        "signed",
        "signed int",
        "unsigned",
        "unsigned int",
        "long",
        "long int",
        "unsigned long",
        "long unsigned int",
        "long long",
        "long long int",
        "unsigned long long",
        "long long unsigned int",
        "float",
        "double",
        "long double",
        "size_t",
        "int8_t",
        "int16_t",
        "int32_t",
        "int64_t",
        "uint8_t",
        "uint16_t",
        "uint32_t",
        "uint64_t",
        "__int128",
    }
)

# Element types that can appear in a GDB cast without relying on user typedefs.
CAST_SAFE_TYPES = frozenset(
    {
        "char",
        "signed char",
        "unsigned char",
        "short",
        "short int",
        "unsigned short",
        "int",
        "unsigned",
        "unsigned int",
        "long",
        "long int",
        "unsigned long",
        "long long",
        "long long int",
        "unsigned long long",
        "float",
        "double",
        "long double",
    }
)

_BUILTIN_TYPE_WORDS = frozenset(
    {"bool", "char", "short", "int", "long", "float", "double", "unsigned", "signed"}
)

_NON_DECLARATOR_WORDS = frozenset(
    {
        "operator",
        "const",
        "constexpr",
        "volatile",
        "static",
        "typename",
        "class",
        "struct",
        "return",
        "new",
        "delete",
        "sizeof",
    }
    | {word for type_name in FUNDAMENTAL_TYPES for word in type_name.split()}
)

_GLOBAL_STATEMENT_SKIP = re.compile(
    r"^(?:using|typedef|template|extern|static_assert|friend|return|struct|class|"
    r"enum|union|namespace|const|constexpr|inline)\b"
)

# Local declarations of these templates get explicit extraction commands (see classify_type).
# Ordered associative containers, read node by node from the red-black tree.
TREE_TEMPLATES = ("set<", "multiset<", "map<", "multimap<")
TREE_KINDS = frozenset(template[:-1] for template in TREE_TEMPLATES)
EXTRACTED_TEMPLATES = ("vector<", "deque<", "queue<", "stack<", "priority_queue<", *TREE_TEMPLATES)


@dataclass(frozen=True)
class ValueSpec:
    """A variable whose value the tracer extracts with explicit GDB commands."""

    name: str
    kind: str
    element: str = ""
    row_type: str = ""
    declaration_line: int = 0
    ready_line: int = 0
    scope_end_line: int = 0
    end_inclusive: bool = True
    # Declared inside parentheses: a function parameter or a range-for variable.
    parameter: bool = False

    def visible_at(self, line: int) -> bool:
        if line <= self.ready_line:
            return False
        if self.scope_end_line and line > self.scope_end_line:
            return False
        return line < self.scope_end_line or self.end_inclusive or not self.scope_end_line


@dataclass(frozen=True)
class GlobalCandidate:
    name: str
    declaration_line: int


@dataclass(frozen=True)
class SourceModel:
    vectors: tuple[ValueSpec, ...]
    globals: tuple[GlobalCandidate, ...]
    # typedef/using names; GDB reports these names in `whatis` output.
    aliases: dict[str, str]
    # Object-like #define names; they only exist before compilation.
    macros: dict[str, str]
    first_uses: dict[int, dict[str, int]]
    function_blocks: tuple[tuple[int, int], ...]
    # False when a macro renames a builtin type (for example `#define int long long`),
    # because lexical element types can then disagree with the compiled types.
    raw_casts: bool = True
    # Names declared by a statement that starts on each line. A stop on that line comes
    # before the declaration runs, so GDB would show uninitialized memory for them.
    line_declarations: dict[int, frozenset[str]] = field(default_factory=dict)

    def block_for_line(self, line: int) -> int | None:
        for index, (start, end) in enumerate(self.function_blocks):
            if start <= line <= end:
                return index
        return None


def analyze_source(source: str) -> SourceModel:
    text = strip_code(source)
    index = _TextIndex(text)
    aliases = _type_aliases(text)
    macros = _type_macros(source)
    raw_casts = not any(name in _BUILTIN_TYPE_WORDS for name in macros)
    vectors = _vector_declarations(text, index, {**aliases, **macros})
    if not raw_casts:
        # Tree containers keep their element types: they come from macro-expanded text.
        vectors = [spec if spec.kind in TREE_KINDS else replace(spec, row_type="") for spec in vectors]
    return SourceModel(
        vectors=tuple(vectors),
        globals=tuple(_global_candidates(text, index)),
        aliases=aliases,
        macros=macros,
        first_uses=_first_uses(text, index),
        line_declarations=_line_declarations(text, index),
        function_blocks=tuple(index.top_level_blocks()),
        raw_casts=raw_casts,
    )


def strip_code(source: str) -> str:
    """Blank comments, preprocessor lines, and literal contents.

    Offsets and line breaks are preserved so positions still map to source lines.
    """
    characters = list(source)
    length = len(source)
    position = 0
    line_start = True
    while position < length:
        character = source[position]
        if character == "\n":
            line_start = True
            position += 1
            continue
        if character in " \t\r\f\v":
            position += 1
            continue
        if line_start and character == "#":
            while position < length and source[position] != "\n":
                if source.startswith("\\\n", position) or source.startswith("\\\r\n", position):
                    characters[position] = " "
                    position = source.index("\n", position) + 1
                    continue
                characters[position] = " "
                position += 1
            continue
        line_start = False
        if source.startswith("//", position):
            while position < length and source[position] != "\n":
                characters[position] = " "
                position += 1
            continue
        if source.startswith("/*", position):
            end = source.find("*/", position + 2)
            end = length if end < 0 else end + 2
            for offset in range(position, end):
                if source[offset] != "\n":
                    characters[offset] = " "
            position = end
            continue
        if character in "\"'":
            offset = position + 1
            while offset < length and source[offset] not in (character, "\n"):
                characters[offset] = " "
                if source[offset] == "\\" and offset + 1 < length and source[offset + 1] != "\n":
                    characters[offset + 1] = " "
                    offset += 1
                offset += 1
            position = offset + 1
            continue
        position += 1
    return "".join(characters)


def classify_type(
    type_text: str,
    dimensions: int,
    aliases: dict[str, str],
) -> tuple[str, str, str] | None:
    """Map a declared or GDB-reported type to an extraction strategy.

    Returns ``(kind, row_kind, row_type)``. ``row_kind`` describes each row of a
    table (``vector`` or ``bits``); ``row_type`` is a builtin element type that is
    safe to name in a GDB cast, or an empty string when rows must be read through
    libstdc++ members instead.
    """
    base = _normalize_type(expand_aliases(type_text, aliases))
    if not base or base.startswith("const ") or "(" in base:
        return None
    if base in FUNDAMENTAL_TYPES or base.startswith("pair<"):
        if dimensions > 2:
            return None
        # Character arrays print as C strings, so their buffer size is not a length.
        element = "text" if base in {"char", "signed char", "unsigned char"} else ""
        return (("plain", "array", "matrix")[dimensions], element, "")
    if base.startswith("vector<"):
        element = _normalize_type(first_template_argument(base) or "")
        if element.startswith("vector<"):
            inner = _normalize_type(first_template_argument(element) or "")
            if dimensions or inner.startswith("vector<"):
                return None
            if inner == "bool":
                return ("nested", "bits", "")
            return ("nested", "vector", inner if inner in CAST_SAFE_TYPES else "")
        if dimensions == 0:
            return ("bits" if element == "bool" else "vector", "", "")
        if dimensions == 1:
            if element == "bool":
                return ("vector_array", "bits", "")
            return ("vector_array", "vector", element if element in CAST_SAFE_TYPES else "")
        return None
    if base == "string" and dimensions == 0:
        return ("string", "", "")
    if dimensions == 0 and base.startswith(("deque<", "queue<", "stack<")):
        kind = base[: base.index("<")]
        container = template_arguments(base)[1:2]
        # queue and stack keep their elements in a std::deque member `c` unless told otherwise.
        if kind != "deque" and container and not _normalize_type(container[0]).startswith("deque<"):
            return None
        return (kind, "", "")
    if dimensions == 0 and base.startswith(TREE_TEMPLATES):
        kind = base[: base.index("<")]
        count = 2 if kind in {"map", "multimap"} else 1
        types = [_normalize_type(argument) for argument in template_arguments(base)[:count]]
        # Elements are read from raw tree nodes with a cast, so only plain types qualify.
        if len(types) < count or not all(_node_value_type(type_text) for type_text in types):
            return None
        return (kind, "", "|".join(types))
    if dimensions == 0 and base.startswith("priority_queue<"):
        container = template_arguments(base)[1:2]
        if container and not _normalize_type(container[0]).startswith("vector<"):
            return None
        return ("priority_queue", "", "")
    return None


def _node_value_type(type_text: str) -> bool:
    """A builtin type, or a pair of them, that GDB can read through a pointer cast."""
    plain = CAST_SAFE_TYPES | {"bool"}
    if type_text.startswith("pair<"):
        parts = [_normalize_type(part) for part in template_arguments(type_text)]
        return len(parts) == 2 and all(part in plain for part in parts)
    return type_text in plain


def expand_aliases(type_text: str, aliases: dict[str, str]) -> str:
    expanded = type_text
    for _ in range(6):
        replaced = re.sub(
            r"\b[A-Za-z_]\w*\b",
            lambda match: aliases.get(match.group(0), match.group(0)),
            expanded,
        )
        if replaced == expanded:
            break
        expanded = replaced
    return expanded


def template_arguments(type_text: str) -> list[str]:
    opening = type_text.find("<")
    if opening < 0:
        return []
    arguments: list[str] = []
    depth = 0
    start = opening + 1
    for position in range(opening, len(type_text)):
        character = type_text[position]
        if character in "<(":
            depth += 1
        elif character in ">)":
            depth -= 1
            if depth == 0:
                arguments.append(type_text[start:position].strip())
                break
        elif character == "," and depth == 1:
            arguments.append(type_text[start:position].strip())
            start = position + 1
    return arguments


def first_template_argument(type_text: str) -> str | None:
    opening = type_text.find("<")
    if opening < 0:
        return None
    depth = 0
    for position in range(opening, len(type_text)):
        character = type_text[position]
        if character in "<(":
            depth += 1
        elif character in ">)":
            depth -= 1
            if depth == 0:
                return type_text[opening + 1 : position].strip()
        elif character == "," and depth == 1:
            return type_text[opening + 1 : position].strip()
    return None


def _normalize_type(type_text: str) -> str:
    text = re.sub(r"\bstd::(?:__cxx11::)?", "", type_text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s*([<>,])\s*", r"\1", text)
    if text.startswith("basic_string<char"):
        return "string"
    return text


class _TextIndex:
    def __init__(self, text: str) -> None:
        self.text = text
        self.line_starts = [0]
        for position, character in enumerate(text):
            if character == "\n":
                self.line_starts.append(position + 1)
        self.brace_depth: list[int] = []
        self.paren_depth: list[int] = []
        self.matching: dict[int, int] = {}
        brace = 0
        paren = 0
        paren_stack: list[int] = []
        openers: list[int] = []
        for position, character in enumerate(text):
            self.brace_depth.append(brace)
            self.paren_depth.append(paren)
            if character == "{":
                openers.append(position)
                paren_stack.append(paren)
                brace += 1
                paren = 0
            elif character == "}":
                if openers:
                    self.matching[openers.pop()] = position
                brace = max(0, brace - 1)
                paren = paren_stack.pop() if paren_stack else 0
            elif character == "(":
                paren += 1
            elif character == ")":
                paren = max(0, paren - 1)
        self.brace_depth.append(brace)
        self.paren_depth.append(paren)

    def line_of(self, position: int) -> int:
        return bisect.bisect_right(self.line_starts, position)

    def closing_brace(self, opening: int) -> int | None:
        return self.matching.get(opening)

    def enclosing_block_end(self, position: int) -> int | None:
        depth = self.brace_depth[position]
        if depth == 0:
            return None
        for offset in range(position, len(self.text)):
            if self.text[offset] == "}" and self.brace_depth[offset] == depth:
                return offset
        return None

    def brace_starts_line(self, position: int) -> bool:
        line_start = self.line_starts[self.line_of(position) - 1]
        return not self.text[line_start:position].strip()

    def top_level_blocks(self) -> list[tuple[int, int]]:
        blocks = []
        for opening, closing in self.matching.items():
            if self.brace_depth[opening] == 0:
                blocks.append((self.line_of(opening), self.line_of(closing)))
        return sorted(blocks)


def _type_aliases(text: str) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for match in re.finditer(r"\btypedef\s+([^;{}()]+?)\s+([A-Za-z_]\w*)\s*;", text):
        aliases[match.group(2)] = match.group(1).strip()
    for match in re.finditer(r"\busing\s+([A-Za-z_]\w*)\s*=\s*([^;{}]+);", text):
        aliases[match.group(1)] = match.group(2).strip()
    return aliases


def _type_macros(source: str) -> dict[str, str]:
    macros: dict[str, str] = {}
    pattern = re.compile(r"^[ \t]*#[ \t]*define[ \t]+([A-Za-z_]\w*)[ \t]+([^\r\n]+)", re.MULTILINE)
    for match in pattern.finditer(source):
        replacement = re.sub(r"//.*$|/\*.*?\*/", "", match.group(2)).strip()
        if re.fullmatch(r"[\w:<>,\s]+", replacement) and not replacement.isdigit():
            macros[match.group(1)] = replacement
    return macros


def _matching_angle(text: str, opening: int) -> int | None:
    depth = 0
    for position in range(opening, len(text)):
        character = text[position]
        if character == "<":
            depth += 1
        elif character == ">":
            depth -= 1
            if depth == 0:
                return position
        elif character in ";{}":
            return None
    return None


def _matching_close(text: str, opening: int) -> int | None:
    pairs = {"(": ")", "[": "]", "{": "}"}
    closer = pairs[text[opening]]
    depth = 0
    for position in range(opening, len(text)):
        if text[position] == text[opening]:
            depth += 1
        elif text[position] == closer:
            depth -= 1
            if depth == 0:
                return position
    return None


def _skip_spaces(text: str, position: int) -> int:
    while position < len(text) and text[position].isspace():
        position += 1
    return position


def _vector_type_pattern(aliases: dict[str, str]) -> re.Pattern[str]:
    alias_names = sorted(
        (
            name
            for name, target in aliases.items()
            if _normalize_type(expand_aliases(target, aliases)).startswith(EXTRACTED_TEMPLATES)
        ),
        key=len,
        reverse=True,
    )
    alternatives = [r"(?:std::)?(?:vector|deque|queue|stack|priority_queue|multiset|set|multimap|map)\s*<"]
    if alias_names:
        alternatives.append(r"(?:" + "|".join(map(re.escape, alias_names)) + r")\b")
    return re.compile(r"(?<![\w:.>])(?:" + "|".join(alternatives) + r")")


def _vector_declarations(
    text: str,
    index: _TextIndex,
    aliases: dict[str, str],
) -> list[ValueSpec]:
    declarations: list[ValueSpec] = []
    declarator = re.compile(r"\s*(?:const\b\s*)?(&&|&|\*)?\s*(?:const\b\s*)?([A-Za-z_]\w*)")
    for match in _vector_type_pattern(aliases).finditer(text):
        start = match.start()
        if text[match.end() - 1] == "<":
            closing = _matching_angle(text, match.end() - 1)
            if closing is None:
                continue
            type_end = closing + 1
        else:
            type_end = match.end()
        if index.brace_depth[start] == 0 and index.paren_depth[start] == 0:
            continue
        type_text = text[start:type_end]
        parameter_like = index.paren_depth[start] > 0
        cursor = type_end
        while True:
            name_match = declarator.match(text, cursor)
            if not name_match or name_match.group(1) == "*":
                break
            name = name_match.group(2)
            if name in _NON_DECLARATOR_WORDS or name in aliases:
                break
            after = _skip_spaces(text, name_match.end())
            dimensions = 0
            if after < len(text) and text[after] == "(":
                closing = _matching_close(text, after)
                if closing is None or _looks_like_parameters(text[after + 1 : closing]):
                    break
            while after < len(text) and text[after] == "[":
                closing = _matching_close(text, after)
                if closing is None:
                    break
                dimensions += 1
                after = _skip_spaces(text, closing + 1)
            classified = classify_type(type_text, dimensions, aliases)
            span = _declaration_span(text, index, name_match.start(2), parameter_like)
            if classified and span:
                ready, scope_end, inclusive = span
                kind, element, row_type = classified
                if kind not in {"plain", "string"}:
                    declarations.append(
                        ValueSpec(
                            name=name,
                            kind=kind,
                            element=element,
                            row_type=row_type,
                            declaration_line=index.line_of(name_match.start(2)),
                            ready_line=index.line_of(ready),
                            scope_end_line=index.line_of(scope_end),
                            end_inclusive=inclusive,
                            parameter=parameter_like,
                        )
                    )
            if parameter_like:
                break
            separator = _next_top_level_separator(text, name_match.end())
            if separator is None or text[separator] != ",":
                break
            cursor = separator + 1
    return declarations


def _declaration_span(
    text: str,
    index: _TextIndex,
    name_position: int,
    parameter_like: bool,
) -> tuple[int, int, bool] | None:
    """Return (ready position, scope-closing brace, closing line inclusive)."""
    if parameter_like:
        depth = index.paren_depth[name_position]
        position = name_position
        while position < len(text) and not (
            text[position] == ")" and index.paren_depth[position] == depth
        ):
            position += 1
        if position >= len(text):
            return None
        position += 1
        base_depth = index.paren_depth[position]
        while position < len(text):
            character = text[position]
            if character == ";" and index.paren_depth[position] == base_depth:
                return None
            if character == "{" and index.paren_depth[position] == base_depth:
                closing = index.closing_brace(position)
                if closing is None:
                    return None
                return position, closing, not index.brace_starts_line(closing)
            if character == "}":
                return None
            position += 1
        return None

    separator = _next_top_level_separator(text, name_position)
    closing = index.enclosing_block_end(name_position)
    if separator is None or closing is None:
        return None
    statement_end = separator
    while text[statement_end] == ",":
        following = _next_top_level_separator(text, statement_end + 1)
        if following is None:
            return None
        statement_end = following
    return statement_end, closing, not index.brace_starts_line(closing)


def _next_top_level_separator(text: str, position: int) -> int | None:
    while position < len(text):
        character = text[position]
        if character in "([{":
            closing = _matching_close(text, position)
            if closing is None:
                return None
            position = closing + 1
            continue
        if character in ",;":
            return position
        if character in ")}":
            return None
        position += 1
    return None


def _looks_like_parameters(content: str) -> bool:
    content = content.strip()
    if not content or content == "void":
        return True
    parts = _split_top_level(content)
    parameter = re.compile(
        r"(?:(?:const|volatile|unsigned|signed|struct|class|typename)\s+)*"
        r"[A-Za-z_][\w:]*(?:\s*<.*>)?(?:\s+[A-Za-z_]\w*)*"
        r"(?:\s*(?:\*|&&|&)\s*|\s+)(?:const\s+)?[A-Za-z_]\w*(?:\s*\[[^\]]*\])*",
        re.DOTALL,
    )
    for part in parts:
        part = part.split("=", 1)[0].strip()
        if part in FUNDAMENTAL_TYPES:
            continue
        if not parameter.fullmatch(part):
            return False
    return True


def _split_top_level(content: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    start = 0
    for position, character in enumerate(content):
        if character in "<([{":
            depth += 1
        elif character in ">)]}":
            depth = max(0, depth - 1)
        elif character == "," and depth == 0:
            parts.append(content[start:position])
            start = position + 1
    parts.append(content[start:])
    return parts


def _global_candidates(text: str, index: _TextIndex) -> list[GlobalCandidate]:
    candidates: list[GlobalCandidate] = []
    seen: set[str] = set()
    statement_start = 0
    position = 0
    while position < len(text):
        character = text[position]
        if index.brace_depth[position] != 0:
            position += 1
            continue
        if character == "{":
            prefix = text[statement_start:position].strip()
            closing = index.closing_brace(position)
            if closing is None:
                break
            if prefix.endswith("=") or _looks_like_variable_head(prefix):
                position = closing + 1
                continue
            statement_start = closing + 1
            position = closing + 1
            continue
        if character == ";" and index.paren_depth[position] == 0:
            for name, offset in _global_declarators(text, statement_start, position):
                if name not in seen:
                    seen.add(name)
                    candidates.append(GlobalCandidate(name, index.line_of(offset)))
            statement_start = position + 1
        position += 1
    return candidates


def _looks_like_variable_head(prefix: str) -> bool:
    if not prefix or _GLOBAL_STATEMENT_SKIP.match(prefix):
        return False
    return bool(re.fullmatch(r"[\w:<>,\s*&]+\s+[A-Za-z_]\w*(?:\s*\[[^\]]*\])*", prefix))


def _global_declarators(text: str, start: int, end: int) -> list[tuple[str, int]]:
    statement = text[start:end]
    leading = len(statement) - len(statement.lstrip())
    body = statement.strip()
    if not body or _GLOBAL_STATEMENT_SKIP.match(body):
        return []
    body_start = start + leading
    body = re.sub(r"^(?:static|thread_local)\s+", lambda match: " " * len(match.group(0)), body)

    names: list[tuple[str, int]] = []
    segments: list[tuple[int, int]] = []
    depth = 0
    segment_start = 0
    for position, character in enumerate(body):
        if character in "<([{":
            depth += 1
        elif character in ">)]}":
            depth = max(0, depth - 1)
        elif character == "," and depth == 0:
            segments.append((segment_start, position))
            segment_start = position + 1
    segments.append((segment_start, len(body)))

    for number, (segment_start, segment_end) in enumerate(segments):
        segment = body[segment_start:segment_end]
        head = re.split(r"[=(\[{]", segment, maxsplit=1)[0]
        identifiers = list(re.finditer(r"[A-Za-z_]\w*", head))
        if not identifiers or (number == 0 and len(identifiers) < 2):
            continue
        name = identifiers[-1]
        if name.group(0) in _NON_DECLARATOR_WORDS:
            continue
        names.append((name.group(0), body_start + segment_start + name.start()))
    return names


_NOT_TYPES = frozenset(
    {
        "return", "else", "case", "goto", "delete", "throw", "new", "using", "typedef",
        "namespace", "do", "if", "while", "for", "switch", "sizeof", "co_return", "operator",
    }
)
_DECLARATION = re.compile(
    r"(?:^|(?<=[;{}(]))\s*"
    r"(?:(?:const|static|constexpr|register|volatile|unsigned|signed)\s+)*"
    r"(?P<type>long\s+long|long\s+double|[A-Za-z_][\w:]*(?:\s*<[^;(){}]*>)?)"
    r"(?:\s*[&*]+\s*|\s+)"
    r"(?P<name>[A-Za-z_]\w*)\s*(?=[=;,\[({:])",
    re.MULTILINE,
)
_STRUCTURED_BINDING = re.compile(r"\bauto\s*[&*]*\s*\[(?P<names>[^\]]*)\]")


def _line_declarations(text: str, index: _TextIndex) -> dict[int, frozenset[str]]:
    """Map each line to the variable names declared by statements starting on it."""
    declared: dict[int, set[str]] = {}
    for match in _DECLARATION.finditer(text):
        if match.group("type") in _NOT_TYPES or match.group("name") in _NOT_TYPES:
            continue
        line = index.line_of(match.start("name"))
        names = declared.setdefault(line, set())
        names.add(match.group("name"))
        # `int a, b = 2;`: further declarators follow top-level commas.
        separator = _next_top_level_separator(text, match.end("name"))
        while separator is not None and text[separator] == ",":
            following = re.match(r"\s*[&*]*\s*([A-Za-z_]\w*)", text[separator + 1 :])
            if not following:
                break
            names.add(following.group(1))
            separator = _next_top_level_separator(text, separator + 1 + following.end())
    for match in _STRUCTURED_BINDING.finditer(text):
        line = index.line_of(match.start())
        declared.setdefault(line, set()).update(
            name.strip() for name in match.group("names").split(",") if name.strip()
        )
    return {line: frozenset(names) for line, names in declared.items()}


def _first_uses(text: str, index: _TextIndex) -> dict[int, dict[str, int]]:
    """Map each top-level block to the first line where each identifier appears."""
    uses: dict[int, dict[str, int]] = {}
    blocks = index.top_level_blocks()
    for block_number, (start_line, end_line) in enumerate(blocks):
        block_uses: dict[str, int] = {}
        start = index.line_starts[start_line - 1]
        end = index.line_starts[end_line] if end_line < len(index.line_starts) else len(text)
        for match in re.finditer(r"(?<![\w.:])(?<!->)[A-Za-z_]\w*", text[start:end]):
            block_uses.setdefault(match.group(0), index.line_of(start + match.start()))
        uses[block_number] = block_uses
    return uses
