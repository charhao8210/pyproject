// The Variables panel: single values, containers, tables, and shared references.

const containerTypes = new Set(["list", "tuple", "dict", "set", "frozenset", "object"]);

// Values read from stdin and never changed (`n`, `m`) are shown once beside the visualization,
// so Variables hides them, also before they are read (C++ would show garbage there).
function inputNames(step) {
    if (elements.algorithmPanel.classList.contains("is-collapsed")) return [];
    return (step.inputs || []).map((entry) => entry.name);
}

function renderInputs(step, visualization) {
    const drawn = new Set((visualization?.uses || []).map(String));
    // On the line that reads a value (`cin >> n`) it already shows, blue, with the value it gets.
    const appearing = step.usage?.appearing || {};
    const shown = (step.inputs || [])
        .filter((entry) => !drawn.has(entry.name) && !isDisplayedArraySize(entry.name, entry, visualization) && (entry.read || Object.hasOwn(appearing, entry.name)))
        .map((entry) => (entry.read ? [entry, false] : [{name: entry.name, ...appearing[entry.name].value}, true]));
    const onLine = new Set(step.usage?.line || []);
    elements.algorithmInputs.replaceChildren(...shown.map(([entry, isNew]) => {
        const item = textSpan(`${entry.name} = ${numberText(entry)}`, "algorithm-readout");
        item.classList.toggle("is-on-line", onLine.has(entry.name));
        item.classList.toggle("is-new", isNew);
        return item;
    }));
    elements.algorithmInputs.hidden = !shown.length;
}

// Only fold conventional size inputs when the current array actually displays that size.
// Search targets, bounds and inputs for other renderer types stay visible.
function isDisplayedArraySize(name, value, view) {
    if (!view?.ready || !["array", "cells"].includes(view.renderer)) return false;
    if (!/^(n|size|length|count)$/.test(name)) return false;
    const length = view.length ?? view.total_length ?? view.captured_length ?? view.values?.length;
    const source = state.result?.source || "";
    const isLoopBound = new RegExp(`(?:<\\s*${name}\\b|range\\(\\s*${name}\\s*\\))`).test(source);
    return isLoopBound && Number.isInteger(length) && Number(numberText(value)) === length;
}

function renderVariables(step, visualization) {
    const onLine = new Set(step.usage?.line || []);
    const changed = new Set(step.usage?.changed || []);
    const appeared = new Set(step.usage?.new || []);
    // What the highlighted line is about to do: the value it will leave, the entries it will write.
    const upcoming = step.usage?.next || {};
    const upcomingCells = step.usage?.cells || {};
    const formulas = step.usage?.formula || {};
    const hidden = new Set([...(visualization?.uses || []).map(String), ...inputNames(step)]);
    // Variables the highlighted line creates are listed already, with the value they will get.
    const locals = {...(step.locals || {})};
    const globals = {...(step.globals || {})};
    Object.entries(step.usage?.appearing || {}).forEach(([name, entry]) => {
        (entry.global ? globals : locals)[name] = entry.value;
    });
    const entries = variableEntries(locals, globals, hidden);
    elements.variables.replaceChildren();
    elements.variables.className = "panel-body";
    if (!entries.length) {
        elements.variables.classList.add("empty-state");
        elements.variables.textContent = hidden.size
            ? "變數已顯示在圖中"
            : "此步尚無變數";
        return;
    }

    // Single values are rows on the left; containers sit beside them on the right, so neither
    // pushes the other out of view. Both keep the order the variables first appeared in.
    const zones = document.createElement("div");
    zones.className = "variable-zones";
    const isCpp = state.language === "cpp";
    zones.classList.toggle("is-cpp", isCpp);
    const scalars = document.createElement("div");
    scalars.className = "scalar-zone";
    const containers = document.createElement("div");
    containers.className = "container-zone";
    entries.forEach(([name, value, isGlobal]) => {
        const isScalar = isScalarValue(value);
        if (isScalar && isGlobal && !scalars.querySelector(".scalar-group") && scalars.childElementCount) {
            scalars.append(textSpan("global", "scalar-group"));
        }
        const card = document.createElement(isScalar ? "div" : "article");
        card.dataset.variable = name;
        card.className = isScalar ? "scalar-row" : "variable-card";
        // Yellow: used by the line about to run. Orange: changed by the line that just ran.
        card.classList.toggle("is-on-line", onLine.has(name));
        card.classList.toggle("is-changed", changed.has(name));
        // Blue: shown for the first time in this trace.
        card.classList.toggle("is-new", appeared.has(name));
        if (appeared.has(name)) card.dataset.term = "First appearance";
        const nameNode = textSpan(name, "variable-label");
        const hint = isScalar ? "" : CONTAINER_HINTS[value?.class_name] || "";
        const type = textSpan(
            [!isScalar && isGlobal ? "global" : "", displayType(value), hint].filter(Boolean).join(" · "),
            "type-tag",
        );
        const content = document.createElement("div");
        content.className = "value-view";
        const formula = isScalar ? formulaText(formulas[name], Object.hasOwn(upcoming, name) ? upcoming[name] : value) : "";
        if (isScalar && Object.hasOwn(upcoming, name)) {
            // On the line that changes it: `7 -> mid+1 = 7+1 = 8`, the value now, how the line
            // computes the next one, and that value.
            const before = renderValue(value, 0);
            before.classList.add("change-before");
            const arrow = textSpan("->", "change-arrow");
            arrow.dataset.term = "now -> next";
            content.append(before, arrow);
            if (formula) content.append(textSpan(formula, "change-formula"));
            content.append(renderValue(upcoming[name], 0));
        } else if (formula) {
            // A variable the line creates: `l = ma = 7`.
            content.append(textSpan(formula, "change-formula"), renderValue(value, 0));
        } else {
            content.append(renderValue(value, 0, upcomingCells[name]));
        }
        if (isScalar && isCpp) {
            // Read like a C++ declaration: `bool flag false`.
            const declared = cppTypeName(value);
            type.textContent = declared.text;
            type.classList.toggle("is-kind", !declared.declared);
            if (!declared.declared) type.dataset.term = "integer";
            card.append(type, nameNode, content);
            scalars.append(card);
        } else if (isScalar) {
            card.append(nameNode, content, type);
            scalars.append(card);
        } else {
            const header = document.createElement("div");
            header.className = "variable-name";
            header.append(nameNode, type);
            card.append(header, content);
            containers.append(card);
        }
    });
    if (scalars.childElementCount) zones.append(scalars);
    if (containers.childElementCount) zones.append(containers);
    zones.classList.toggle("is-split", zones.childElementCount === 2);
    elements.variables.classList.add("has-zones");
    elements.variables.append(zones);
}

// `mid+1 = 7+1 = ` in front of the value a line assigns. A bare number (`ma = 0`, `r = 1e18`)
// shows only the result, and the substituted form is left out when it adds nothing or holds a
// number of 10^6 or more (`(7+1000000000000000000)/2` is unreadable; the user's choice).
function formulaText(formula, result) {
    if (!formula || /^[-+]?[\d.][\w.']*$/.test(formula.expression.trim())) return "";
    const resultText = compactValue(result);
    // `flag = false`: a literal that is already the value adds nothing.
    if (formula.expression.trim() === resultText) return "";
    const parts = [formula.expression];
    const substituted = formula.substituted;
    if (substituted !== formula.expression && substituted !== resultText && !/\d{7,}/.test(substituted)) parts.push(substituted);
    return `${parts.join(" = ")} = `;
}

// The type a C++ variable was declared with (`long long`, `string`), from the tracer's `c_type`.
// Without one only the kind of value is known, so that is what shows (`integer`, never a guessed
// `int` for what may be a `long long`), marked as a kind rather than a declaration.
const CPP_VALUE_KINDS = {int: "integer", float: "floating", str: "text", bool: "bool", none: "pointer"};

function cppTypeName(value) {
    if (value?.c_type) return {text: value.c_type, declared: true};
    return {text: CPP_VALUE_KINDS[value?.type] || displayType(value), declared: false};
}

// C++ spells booleans in lowercase; Python keeps True and False.
function boolText(value) {
    if (state.language === "cpp") return value ? "true" : "false";
    return value ? "True" : "False";
}

// Which end of a decoded C++ container is which.
const CONTAINER_HINTS = {
    queue: "front at index 0",
    stack: "top at the right",
    set: "sorted",
    multiset: "sorted",
    map: "sorted by key",
    multimap: "sorted by key",
    priority_queue: "heap order, top at index 0",
};

function isScalarValue(value) {
    if (["int", "float", "bool", "none", "reference"].includes(value?.type)) return true;
    return value?.type === "str" && value.value.length <= 24;
}

// Every name's position is the order it first appears in the trace, so rows never trade places.
const variableOrders = new WeakMap();

function variableOrder(result) {
    if (!variableOrders.has(result)) {
        const order = new Map();
        result.steps.forEach((step) => {
            [...Object.keys(step.locals || {}), ...Object.keys(step.globals || {})].forEach((name) => {
                if (!order.has(name)) order.set(name, order.size);
            });
        });
        variableOrders.set(result, order);
    }
    return variableOrders.get(result);
}

function variableEntries(locals, globals, hidden) {
    const order = variableOrder(state.result);
    const rank = ([name]) => order.get(name) ?? Infinity;
    // Functions, classes, the `sys` shim, and Python's hidden comprehension iterator (`.0`) are
    // program structure, not state.
    const isNoise = (name, value) => name.startsWith("__") || name.startsWith(".")
        || value?.type === "function"
        || ["type", "module", "SimpleNamespace", "builtin_function_or_method"].includes(value?.class_name);
    // Globals are visible from function frames too, but locals shadow them and come first.
    const frame = Object.entries(locals).sort((left, right) => rank(left) - rank(right));
    const shared = Object.entries(globals)
        .filter(([name]) => !Object.hasOwn(locals, name))
        .sort((left, right) => rank(left) - rank(right));
    return [
        ...frame.map(([name, value]) => [name, value, false]),
        ...shared.map(([name, value]) => [name, value, true]),
    ].filter(([name, value]) => !hidden.has(name) && !isNoise(name, value));
}

// `changes` (`step.usage.cells[name]`) marks the entries the highlighted line will change: `items` are
// list or dict positions, `cells` are [row, column] of a table.
function renderValue(value, depth, changes = null) {
    if (!value) return textSpan("—", "primitive none");
    const changedItems = new Set(changes?.items || []);
    const changedTableCells = new Set((changes?.cells || []).map(([row, column]) => `${row}:${column}`));
    if (value.type === "reference") {
        const reference = textSpan(referenceText(value.object_id), "reference-value");
        reference.dataset.term = "same list as";
        const target = referenceTarget(value.object_id);
        if (target) {
            reference.dataset.aliasName = target.name;
            reference.dataset.aliasIndex = target.index === null ? "" : String(target.index);
        }
        return reference;
    }
    if (value.type === "str") {
        return textSpan(JSON.stringify(value.value) + truncatedSuffix(value), "primitive str");
    }
    if (["int", "float"].includes(value.type)) {
        return textSpan(numberText(value), "primitive number");
    }
    if (value.type === "bool") {
        return textSpan(boolText(value.value), "primitive bool");
    }
    if (value.type === "none") return textSpan("None", "primitive none");

    if (depth === 0 && isTableValue(value)) return renderTableValue(value, changedTableCells);
    if (["list", "tuple", "set", "frozenset"].includes(value.type)) {
        // A pair inside a list reads best as `(1, 2)`, not as a nested row of cells.
        const flatTuple = value.type === "tuple" && (value.items || []).every(isScalarValue);
        if (depth >= 2 || (depth >= 1 && flatTuple)) return textSpan(compactValue(value), "primitive");
        const wrapper = document.createElement("div");
        const array = document.createElement("div");
        array.className = "array-view";
        // A long run of trailing zeros (`dis[100005]` with five nodes) becomes one note.
        const items = value.fill ? (value.items || []).slice(0, value.fill.from) : value.items || [];
        items.forEach((item, index) => {
            const cell = document.createElement("div");
            cell.className = "array-cell";
            cell.dataset.index = String(index);
            if (changedItems.has(index)) cell.classList.add("is-changed-cell");
            const indexNode = document.createElement("div");
            indexNode.className = "array-index";
            indexNode.textContent = value.type === "list" || value.type === "tuple" ? index : "item";
            const itemNode = document.createElement("div");
            itemNode.className = "array-item";
            itemNode.append(renderValue(item, depth + 1));
            cell.append(indexNode, itemNode);
            array.append(cell);
        });
        // Entries the highlighted line is about to push, after the current ones, in blue.
        if (!value.fill && !value.truncated) {
            (changes?.appended || []).forEach((item, offset) => {
                const cell = document.createElement("div");
                cell.className = "array-cell is-new-cell";
                const indexNode = document.createElement("div");
                indexNode.className = "array-index";
                indexNode.textContent = value.type === "list" || value.type === "tuple" ? items.length + offset : "item";
                const itemNode = document.createElement("div");
                itemNode.className = "array-item";
                itemNode.append(renderValue(item, depth + 1));
                cell.append(indexNode, itemNode);
                array.append(cell);
            });
        }
        if (array.childElementCount) wrapper.append(array);
        else if (!value.fill && !value.truncated) wrapper.append(textSpan("empty", "fill-note"));
        if (value.fill) {
            wrapper.append(textSpan(fillNote(value), "fill-note"));
        } else if (value.truncated) {
            wrapper.append(textSpan("… truncated", "truncated-note"));
        }
        return wrapper;
    }

    if (value.type === "dict") {
        if (depth >= 2) return textSpan(compactValue(value), "primitive");
        const dict = document.createElement("div");
        dict.className = "dict-view";
        (value.entries || []).forEach((entry, position) => {
            const row = document.createElement("div");
            row.className = "dict-row";
            if (changedItems.has(position)) row.classList.add("is-changed-cell");
            const key = document.createElement("div");
            key.className = "dict-key";
            // An object's fields read as plain names (`value`), a dict's keys as values (`"a"`).
            key.textContent = isObjectFields(value) ? String(entry.key?.value) : compactValue(entry.key);
            const item = document.createElement("div");
            item.className = "dict-value";
            item.append(renderValue(entry.value, depth + 1));
            row.append(key, item);
            dict.append(row);
        });
        if (value.truncated) dict.append(textSpan("… truncated", "truncated-note"));
        if (!(value.entries || []).length && !value.truncated) dict.append(textSpan("empty", "fill-note"));
        return dict;
    }

    if (value.type === "range") {
        const range = value.value;
        return textSpan(`range(${range.start}, ${range.stop}, ${range.step})`, "primitive");
    }
    return textSpan(value.value ?? `<${displayType(value)}>`, "primitive");
}

// A 2D array: rows of single values, or C++ character rows (strings that keep NUL cells).
function isTableValue(value) {
    const rows = value?.type === "list" ? value.items || [] : [];
    if (rows.length < 2) return false;
    if (rows.every((row) => row.type === "str")) {
        const widths = new Set(rows.map((row) => row.value.length));
        // A fixed-size C++ char grid before any input arrives: every row is still empty.
        const unread = value.truncated && rows.every((row) => row.value === "");
        return unread || rows.some((row) => row.value.includes("\0")) || (widths.size === 1 && !widths.has(0) && !widths.has(1));
    }
    return rows.every((row) => ["list", "tuple"].includes(row.type) && (row.items || []).every(isScalarValue))
        && rows.some((row) => (row.items || []).length > 1);
}

function isBlankCell(item) {
    return [0, "", "\0", false, null, undefined].includes(item?.value) && item?.type !== "reference";
}

function renderTableValue(value, changedCells = new Set()) {
    const rows = value.items.map((row) => (row.type === "str"
        ? [...row.value].map((character) => ({type: "str", value: character}))
        : row.items || []));
    let height = rows.length;
    let width = Math.max(0, ...rows.map((row) => row.length));
    // Fixed-size C++ arrays (dp[1005][1005]) arrive clipped; draw only the part holding data.
    const clipped = value.truncated || value.items.some((row) => row.truncated);
    if (clipped) {
        height = 0;
        width = 0;
        rows.forEach((row, rowIndex) => row.forEach((item, columnIndex) => {
            if (isBlankCell(item)) return;
            height = Math.max(height, rowIndex + 1);
            width = Math.max(width, columnIndex + 1);
        }));
    }
    const wrapper = document.createElement("div");
    if (!height || !width) {
        wrapper.append(textSpan("Every cell read so far is empty", "fill-note"));
        return wrapper;
    }
    const table = document.createElement("div");
    table.className = "table-view";
    table.style.gridTemplateColumns = `auto repeat(${width}, minmax(28px, max-content))`;
    const header = (text) => textSpan(text, "table-index");
    table.append(header(""));
    for (let column = 0; column < width; column++) table.append(header(String(column)));
    for (let row = 0; row < height; row++) {
        table.append(header(String(row)));
        for (let column = 0; column < width; column++) {
            const item = rows[row]?.[column];
            const text = !item || item.value === "\0" ? "" : compactValue(item);
            const cell = textSpan(text, "table-cell");
            cell.dataset.row = String(row);
            if (changedCells.has(`${row}:${column}`)) cell.classList.add("is-changed-cell");
            table.append(cell);
        }
    }
    wrapper.append(table);
    if (clipped) wrapper.append(textSpan("Only the rows and columns holding data are shown; the array is larger.", "fill-note"));
    return wrapper;
}

function fillNote(value) {
    const length = value.length ?? (value.items || []).length;
    const zero = compactValue(value.fill.value);
    const count = (length - value.fill.from).toLocaleString("en-US");
    if (value.fill.from === 0) return `All ${count} items are ${zero}`;
    return `… the other ${count} items (index ${value.fill.from}–${(length - 1).toLocaleString("en-US")}) are ${zero}`;
}

function textSpan(text, className) {
    const span = document.createElement("span");
    span.className = className;
    span.textContent = text;
    return span;
}

function truncatedSuffix(value) {
    return value.truncated ? "…" : "";
}

function displayType(value) {
    if (value?.type === "reference") return state.objectTypes.get(String(value.object_id)) || "reference";
    return value?.class_name || value?.type || "unknown";
}

// Integers beyond 2^53 lose digits as JSON numbers; the server adds their exact `text`.
function numberText(value) {
    return value.text ?? String(value.value);
}

// An instance of a class the program defined (`Node`), serialized as a dict of its fields.
function isObjectFields(value) {
    return value?.type === "dict" && Boolean(value.class_name) && value.class_name !== "dict";
}

function compactValue(value, depth = 0) {
    if (!value) return "—";
    if (value.type === "reference") return referenceText(value.object_id);
    if (value.type === "str") return JSON.stringify(value.value.length > 18 ? `${value.value.slice(0, 18)}…` : value.value);
    if (value.type === "none") return "None";
    if (["int", "float"].includes(value.type)) return numberText(value);
    if (value.type === "bool") return boolText(value.value);
    if (depth > 0 && containerTypes.has(value.type)) return objectLabel(value.object_id);
    if (["list", "tuple", "set", "frozenset"].includes(value.type)) {
        const brackets = value.type === "tuple" ? ["(", ")"] : value.type === "list" ? ["[", "]"] : ["{", "}"];
        const items = (value.items || []).slice(0, 4).map((item) => compactValue(item, depth + 1));
        if ((value.items || []).length > 4 || value.truncated) items.push("…");
        return `${brackets[0]}${items.join(", ")}${brackets[1]}`;
    }
    if (value.type === "dict") {
        const fieldKey = (entry) => (isObjectFields(value) ? String(entry.key?.value) : compactValue(entry.key, 1));
        const items = (value.entries || []).slice(0, 3).map((entry) => `${fieldKey(entry)}: ${compactValue(entry.value, 1)}`);
        if ((value.entries || []).length > 3 || value.truncated) items.push("…");
        return `${isObjectFields(value) ? value.class_name : ""}{${items.join(", ")}}`;
    }
    if (value.type === "range") return `range(${value.value.start}, ${value.value.stop}, ${value.value.step})`;
    return String(value.value ?? `<${displayType(value)}>`);
}

function indexObjects(steps) {
    state.objectLabels.clear();
    state.objectTypes.clear();
    const counters = new Map();

    const visit = (value) => {
        if (!value || typeof value !== "object") return;
        if (value.object_id !== undefined && value.type !== "reference") {
            const key = String(value.object_id);
            state.objectTypes.set(key, value.type);
            if (!state.objectLabels.has(key)) {
                const display = titleCase(value.type === "object" ? value.class_name : value.type);
                const count = (counters.get(display) || 0) + 1;
                counters.set(display, count);
                state.objectLabels.set(key, `${display} #${count}`);
            }
        }
        (value.items || []).forEach(visit);
        (value.entries || []).forEach((entry) => {
            visit(entry.key);
            visit(entry.value);
        });
    };

    steps.forEach((step) => {
        Object.values(step.locals || {}).forEach(visit);
        Object.values(step.globals || {}).forEach(visit);
    });
}

function objectLabel(objectId) {
    return state.objectLabels.get(String(objectId)) || "Object";
}

// `b = a` makes b a second name for a's list: say so by name, `↪ same list as a`, instead of an
// object number shown nowhere else. A part of another container is named by its path:
// `row = matrix[1]` reads `↪ matrix[1]`, an object's field `↪ head.next`. Falls back to the
// number when no variable reaches the object within a few levels.
function referenceText(objectId) {
    const step = state.result?.steps?.[state.currentStep];
    const scopes = [step?.locals || {}, step?.globals || {}];
    for (const scope of scopes) {
        for (const [name, value] of Object.entries(scope)) {
            if (value?.type !== "reference" && value?.object_id !== undefined && String(value.object_id) === String(objectId)) {
                return `↪ same ${value.type === "dict" ? "dict" : value.type || "object"} as ${name}`;
            }
        }
    }
    for (const scope of scopes) {
        for (const [name, value] of Object.entries(scope)) {
            const path = objectPath(value, objectId, name, 0);
            if (path) return `↪ ${path}`;
        }
    }
    return `↪ ${objectLabel(objectId)}`;
}

// The variable holding `objectId` and, for a part of it, the first index (`matrix[1]` → matrix, 1),
// so hovering `row ↪ matrix[1]` can light up that row wherever matrix is drawn.
function referenceTarget(objectId) {
    const text = referenceText(objectId).replace(/^↪ (same \w+ as )?/, "");
    const match = text.match(/^([A-Za-z_]\w*)(?:\[(\d+)\])?/);
    if (!match || text.startsWith("Object") || /^(List|Dict|Tuple|Set) #/.test(text)) return null;
    return {name: match[1], index: match[2] === undefined ? null : Number(match[2])};
}

function aliasTargets(name, index) {
    const found = [];
    // The algorithm view, when it draws that variable: a grid row, or one bar / cell.
    if (elements.algorithmView.dataset.view === name) {
        const selector = index === null
            ? ".algorithm-cell, .array-column, .cells-item"
            : `.algorithm-cell[data-row="${index}"], .array-column[data-index="${index}"], .cells-item[data-index="${index}"]`;
        found.push(...elements.algorithmView.querySelectorAll(selector));
    }
    // Its card in Variables: that entry, or that row of a table.
    const card = elements.variables.querySelector(`[data-variable="${CSS.escape(name)}"]`);
    if (card) {
        if (index === null) found.push(card);
        else found.push(...card.querySelectorAll(`.array-cell[data-index="${index}"], .table-cell[data-row="${index}"]`));
    }
    return found;
}

let aliasLit = [];
document.addEventListener("mouseover", (event) => {
    const reference = event.target.closest?.("[data-alias-name]");
    aliasLit.forEach((element) => element.classList.remove("is-alias-target"));
    aliasLit = reference
        ? aliasTargets(reference.dataset.aliasName, reference.dataset.aliasIndex === "" ? null : Number(reference.dataset.aliasIndex))
        : [];
    aliasLit.forEach((element) => element.classList.add("is-alias-target"));
});

// Where `objectId` sits inside `value`, written as code (`matrix[1]`, `head.next`), or null.
function objectPath(value, objectId, path, depth) {
    if (!value || value.type === "reference" || depth > 3) return null;
    if (depth > 0 && value.object_id !== undefined && String(value.object_id) === String(objectId)) return path;
    if (Array.isArray(value.items)) {
        for (let index = 0; index < value.items.length; index += 1) {
            const found = objectPath(value.items[index], objectId, `${path}[${index}]`, depth + 1);
            if (found) return found;
        }
    }
    if (Array.isArray(value.entries)) {
        // An object's fields read as `.name`; a dict's keys as `[key]`.
        const isObject = value.type === "dict" && value.class_name && value.class_name !== "dict";
        for (const entry of value.entries) {
            const key = entry.key?.value;
            const step = isObject ? `.${key}` : `[${compactValue(entry.key)}]`;
            const found = objectPath(entry.value, objectId, `${path}${step}`, depth + 1);
            if (found) return found;
        }
    }
    return null;
}

function titleCase(value) {
    const text = String(value || "object");
    return text.charAt(0).toUpperCase() + text.slice(1);
}
