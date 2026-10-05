/* Specialized lenses show captured state, never invented algorithm operations. */
(() => {
    "use strict";

    const supported = new Set(["heap", "window", "monotonic", "fenwick", "string_match", "trie"]);
    const pages = new Map();
    const selections = new Map();
    const foldedTries = new Map();
    const SVG_NS = "http://www.w3.org/2000/svg";

    function element(tag, className, text) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined) node.textContent = printable(text);
        return node;
    }

    function printable(value) {
        if (value === null) return "null";
        if (value === undefined) return "…";
        if (typeof value === "object") {
            try { return JSON.stringify(value); } catch (_) { return String(value); }
        }
        return String(value);
    }

    function integer(value) {
        return value !== null && value !== undefined && Number.isInteger(Number(value)) ? Number(value) : null;
    }

    function svgElement(tag, attributes = {}, text) {
        const node = document.createElementNS(SVG_NS, tag);
        Object.entries(attributes).forEach(([name, value]) => node.setAttribute(name, String(value)));
        if (text !== undefined) node.textContent = printable(text);
        return node;
    }

    function note(root, text, extraClass = "") {
        root.append(element("p", `al-note ${extraClass}`.trim(), text));
    }

    function modeKey(view, suffix = "") {
        return `${view.renderer}:${view.name || "state"}:${suffix}`;
    }

    function title(root, text, subtitle) {
        const heading = element("header", "al-header");
        heading.append(element("h3", "al-title", text));
        if (subtitle) heading.append(element("span", "al-subtitle", subtitle));
        root.append(heading);
    }

    function section(root, text) {
        const block = element("section", "al-section");
        block.append(element("h4", "al-section-title", text));
        root.append(block);
        return block;
    }

    function readouts(root, entries) {
        const valid = (entries || []).filter((entry) => entry && (entry.value !== undefined || entry.text !== undefined));
        if (!valid.length) return;
        const list = element("dl", "al-readouts");
        valid.forEach((entry) => {
            const pair = element("div", "al-readout");
            pair.append(element("dt", "", entry.label || entry.name || "Value"));
            pair.append(element("dd", "", entry.text ?? entry.value));
            list.append(pair);
        });
        root.append(list);
    }

    function operation(root, view) {
        const op = view.operation;
        if (!op) return;
        const box = element("div", "al-operation");
        if (op.label) box.append(element("span", "al-operation-label", op.label));
        const records = [];
        (op.reads || []).forEach((entry) => records.push({entry, write: false}));
        (op.writes || []).forEach((entry) => records.push({entry, write: true}));
        const isTrace = op.evidence === "trace";
        if (records.length && isTrace) {
            const list = element("ul", "al-operation-records");
            records.slice(0, 6).forEach(({entry, write}) => {
                const at = entry.cell !== undefined ? `[${printable(entry.cell)}]` : entry.index !== undefined ? `[${entry.index}]` : "";
                const value = write
                    ? `${printable(entry.before)} → ${printable(entry.after)}`
                    : printable(entry.value);
                list.append(element("li", write ? "al-written-text" : "", `${write ? "Write" : "Read"} ${entry.name || view.name || "state"}${at}: ${value}`));
            });
            if (records.length > 6) list.append(element("li", "al-muted", `${records.length - 6} more accesses on this line`));
            box.append(list);
        }
        if (!box.childElementCount) return;
        root.append(box);
    }

    function markerMap(view) {
        const map = new Map();
        (view.markers || []).forEach((marker) => {
            const index = integer(marker.index);
            if (index === null) return;
            if (!map.has(index)) map.set(index, []);
            map.get(index).push(marker);
        });
        return map;
    }

    function writtenIndices(view) {
        const result = new Set((view.written || []).map(integer).filter((value) => value !== null));
        if (view.operation?.evidence === "trace") {
            (view.operation.writes || []).forEach((entry) => {
                if ((!entry.name || entry.name === view.name) && integer(entry.index) !== null) result.add(integer(entry.index));
            });
        }
        return result;
    }

    function activeIndex(view) {
        if (integer(view.current) !== null) return integer(view.current);
        const marker = (view.markers || []).find((entry) => integer(entry.index) !== null);
        if (marker) return integer(marker.index);
        const accessed = (view.accesses || []).find((entry) => integer(entry) !== null);
        return accessed === undefined ? null : integer(accessed);
    }

    // Captured values are paged without implying that uncaptured values are available.
    function sequence(root, view, ctx, options = {}) {
        const values = options.values || view.values || [];
        const offset = integer(options.offset ?? view.offset) ?? 0;
        const indexes = options.indexes || values.map((_, position) => offset + position);
        const exact = options.texts || view.values_text || values;
        const pageSize = ctx.target.clientWidth < 440 ? 12 : 24;
        const key = modeKey(view, options.key || "values");
        let start = pages.get(key) || 0;
        start = Math.min(Math.max(0, start), Math.max(0, Math.floor((values.length - 1) / pageSize) * pageSize));
        const current = options.followIndex ?? activeIndex(view);
        const position = indexes.indexOf(current);
        if (ctx.follow && position >= 0 && (position < start || position >= start + pageSize)) {
            start = Math.floor(position / pageSize) * pageSize;
        }
        pages.set(key, start);
        const end = Math.min(values.length, start + pageSize);
        const toolbar = element("div", "al-sequence-toolbar");
        const count = element("span", "al-muted", values.length ? `Captured indices ${indexes[start]}–${indexes[end - 1]}` : "Empty captured sequence");
        toolbar.append(count);
        if (values.length > pageSize) {
            const navigation = element("div", "al-page-buttons");
            [["Previous", -pageSize, start === 0], ["Next", pageSize, end === values.length]].forEach(([label, delta, disabled]) => {
                const button = element("button", "al-page-button", label);
                button.type = "button";
                button.disabled = disabled;
                button.setAttribute("aria-label", `${label} captured ${options.label || view.name || "values"} page`);
                button.addEventListener("click", () => {
                    pages.set(key, start + delta);
                    render(view, {...ctx, follow: false});
                    const candidates = ctx.target.querySelectorAll(".al-page-button");
                    const candidate = [...candidates].find((item) => item.getAttribute("aria-label") === button.getAttribute("aria-label"));
                    if (candidate && !candidate.disabled) candidate.focus();
                });
                navigation.append(button);
            });
            toolbar.append(navigation);
        }
        root.append(toolbar);
        const list = element("div", "al-sequence");
        list.setAttribute("role", "list");
        list.setAttribute("aria-label", options.label || view.name || "Captured values");
        const marks = options.markers || markerMap(view);
        const written = options.written || writtenIndices(view);
        for (let position = start; position < end; position += 1) {
            const index = indexes[position];
            const markers = marks.get(index) || [];
            const classes = ["al-cell"];
            if (markers.length) classes.push("is-active");
            if (written.has(index)) classes.push("is-written");
            if (options.inRange && options.inRange(index)) classes.push("is-in-range");
            if (options.dim && !options.dim(index)) classes.push("is-muted");
            const cell = element(options.onSelect ? "button" : "div", classes.join(" "));
            cell.dataset.index = String(index);
            cell.setAttribute("role", options.onSelect ? "button" : "listitem");
            const extra = options.extra?.(index, position);
            const label = `${options.label || view.name || "value"}[${index}] = ${printable(exact[position])}${extra ? `, ${extra}` : ""}${markers.length ? `, ${markers.map((item) => item.label || "current").join(", ")}` : ""}`;
            cell.setAttribute("aria-label", label);
            cell.title = label;
            cell.append(element("span", "al-cell-index", index));
            cell.append(element("span", "al-cell-value", exact[position]));
            if (extra) cell.append(element("span", "al-cell-extra", extra));
            if (markers.length) cell.append(element("span", "al-cell-markers", markers.map((item) => item.label || "current").join(", ")));
            if (options.onSelect) {
                cell.type = "button";
                cell.addEventListener("click", () => options.onSelect(index));
            }
            list.append(cell);
        }
        root.append(list);
        if (position < 0 && current !== null && ctx.follow) note(root, `Current index ${current} is outside the captured values.`);
        return list;
    }

    function heap(root, view, ctx) {
        const values = view.values || [];
        const order = view.order === "min" ? "Min heap" : view.order === "max" ? "Max heap" : "Heap";
        title(root, order, `${view.name || "heap"} · ${values.length} captured items`);
        const top = view.top ?? values[0];
        if (top !== undefined) readouts(root, [{label: "Top", value: top}]);
        note(root, "Array positions are heap storage order. The tree uses the same indices.");
        operation(root, view);
        const treeNodes = (view.nodes || values.map((value, index) => ({index, value, parent: index ? Math.floor((index - 1) / 2) : null}))).slice(0, 15);
        const selectedKey = modeKey(view, "selection");
        let selected = selections.get(selectedKey) ?? activeIndex(view) ?? 0;
        const detail = element("p", "al-selection-detail");
        const updateSelection = (index) => {
            selected = index;
            selections.set(selectedKey, index);
            root.querySelectorAll("[data-index]").forEach((item) => {
                item.classList.toggle("is-selected", Number(item.dataset.index) === index);
                if (item.getAttribute("role") === "button") item.setAttribute("aria-pressed", String(Number(item.dataset.index) === index));
            });
            const node = (view.nodes || []).find((entry) => integer(entry.index) === index);
            const parent = node ? integer(node.parent) : index ? Math.floor((index - 1) / 2) : null;
            const left = node ? integer(node.left) : index * 2 + 1;
            const right = node ? integer(node.right) : index * 2 + 2;
            const relations = [];
            if (parent !== null && parent >= 0 && parent < values.length) relations.push(`parent [${parent}] = ${printable(values[parent])}`);
            if (left !== null && left >= 0 && left < values.length) relations.push(`left [${left}] = ${printable(values[left])}`);
            if (right !== null && right >= 0 && right < values.length) relations.push(`right [${right}] = ${printable(values[right])}`);
            detail.textContent = values.length ? `[${index}] = ${printable(view.values_text?.[index] ?? values[index])}${relations.length ? ` · ${relations.join(" · ")}` : ""}` : "The heap is empty.";
        };
        const storage = section(root, "Storage array");
        sequence(storage, view, ctx, {onSelect: updateSelection, label: view.name || "heap"});
        const tree = section(root, "Parent and child relationships");
        if (!treeNodes.length) {
            note(tree, "The heap is empty.");
        } else {
            const width = Math.max(320, Math.min(8, Math.ceil((treeNodes.length + 1) / 2)) * 66);
            const height = (Math.floor(Math.log2(treeNodes.length)) + 1) * 74;
            const scroll = element("div", "al-tree-scroll");
            scroll.tabIndex = 0;
            scroll.setAttribute("aria-label", "Heap tree, scroll horizontally to inspect nodes");
            const svg = svgElement("svg", {class: "al-heap-tree", viewBox: `0 0 ${width} ${height}`, width, height, role: "group", "aria-label": "Heap parent and child relationships"});
            const points = new Map();
            treeNodes.forEach((node, position) => {
                const index = integer(node.index) ?? position;
                const level = Math.floor(Math.log2(index + 1));
                const first = 2 ** level - 1;
                points.set(index, {x: ((index - first + 0.5) / 2 ** level) * width, y: level * 74 + 29});
            });
            treeNodes.forEach((node, position) => {
                const index = integer(node.index) ?? position;
                const parent = integer(node.parent) ?? (index ? Math.floor((index - 1) / 2) : null);
                const from = points.get(parent);
                const to = points.get(index);
                if (from && to) svg.append(svgElement("line", {class: "al-tree-edge", x1: from.x, y1: from.y + 19, x2: to.x, y2: to.y - 19}));
            });
            const writes = writtenIndices(view);
            treeNodes.forEach((node, position) => {
                const index = integer(node.index) ?? position;
                const point = points.get(index);
                const classes = ["al-tree-node"];
                if (writes.has(index)) classes.push("is-written");
                if (markerMap(view).has(index)) classes.push("is-active");
                const group = svgElement("g", {class: classes.join(" "), transform: `translate(${point.x} ${point.y})`, "data-index": index, role: "button", tabindex: 0, "aria-label": `Heap index ${index}, value ${printable(node.value)}`});
                group.append(svgElement("rect", {x: -27, y: -20, width: 54, height: 40, rx: 5}));
                const text = printable(view.values_text?.[index] ?? node.value);
                group.append(svgElement("text", {class: "al-tree-value", y: 0}, text.length > 8 ? `${text.slice(0, 7)}…` : text));
                group.append(svgElement("text", {class: "al-tree-index", y: 33}, `[${index}]`));
                group.append(svgElement("title", {}, `[${index}] = ${text}`));
                group.addEventListener("click", () => updateSelection(index));
                group.addEventListener("keydown", (event) => {
                    if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        updateSelection(index);
                    }
                });
                svg.append(group);
            });
            scroll.append(svg);
            tree.append(scroll);
            if (values.length > treeNodes.length) note(tree, `First ${treeNodes.length} captured tree nodes shown. Select other indices in the storage array to inspect their relationships.`);
        }
        tree.append(detail);
        updateSelection(Math.min(Math.max(0, selected), Math.max(0, values.length - 1)));
        readouts(root, view.readouts);
    }

    function windowLens(root, view, ctx) {
        const bounds = view.window || view.bounds || view.interval || {};
        const left = integer(bounds.left ?? bounds.low);
        const right = integer(bounds.right ?? bounds.high);
        const inclusive = bounds.inclusive ?? view.bounds?.inclusive ?? true;
        const empty = bounds.empty === true || (left !== null && right !== null && (inclusive ? left > right : left >= right));
        title(root, "Window", view.name || "sequence");
        if (left !== null && right !== null) {
            readouts(root, [{label: "Bounds", value: `${inclusive ? "[" : "["}${left}, ${right}${inclusive ? "]" : ")"}`}, {label: "Window", value: empty ? "empty" : `${Math.max(0, right - left + (inclusive ? 1 : 0))} positions`}]);
        } else note(root, "Window bounds are unavailable at this step.");
        operation(root, view);
        if (view.aggregate && view.aggregate.value !== undefined) readouts(root, [{label: view.aggregate.name || "Aggregate", value: view.aggregate.value}]);
        const marks = markerMap(view);
        [[left, "L"], [right, inclusive ? "R" : "R (excluded)"]].forEach(([index, label]) => {
            if (index === null || marks.has(index)) return;
            marks.set(index, [{index, label}]);
        });
        const inside = (index) => !empty && left !== null && right !== null && index >= left && (inclusive ? index <= right : index < right);
        sequence(root, view, ctx, {markers: marks, inRange: inside, followIndex: right, dim: ctx.focus && left !== null && right !== null ? (index) => inside(index) || index === left || index === right : null});
        const changes = view.pointer_changes || [];
        if (changes.length) readouts(root, changes.map((entry) => ({label: entry.name, value: `${printable(entry.before)} → ${printable(entry.after)}`})));
        readouts(root, (view.readouts || []).filter((entry) => !view.aggregate || (entry.label || entry.name) !== view.aggregate.name));
    }

    function monotonic(root, view, ctx) {
        const role = view.role === "deque" ? "deque" : "stack";
        const direction = view.direction === "increasing" || view.direction === "decreasing" ? `${view.direction} order inferred from code` : "order not established";
        title(root, `Monotonic ${role}`, `${view.name || role} · ${direction}`);
        operation(root, view);
        const entries = view.entries || (view.values || []).map((value, position) => ({value, position}));
        const storage = section(root, role === "deque" ? "Front → back" : "Bottom → top");
        if (!entries.length) note(storage, `The ${role} is empty.`);
        else {
            const row = element("ol", "al-monotonic-entries");
            row.tabIndex = 0;
            row.setAttribute("aria-label", `Captured ${role} entries, ${role === "deque" ? "front to back" : "bottom to top"}`);
            entries.forEach((entry, position) => {
                const item = element("li", "al-monotonic-entry");
                item.append(element("span", "al-cell-index", `position ${entry.position ?? position}`));
                if (entry.index !== undefined) item.append(element("span", "al-entry-source", `source [${entry.index}]`));
                item.append(element("strong", "al-cell-value", entry.data_value ?? entry.value));
                if (entry.index !== undefined && entry.data_value !== undefined) item.append(element("span", "al-muted", `stored ${printable(entry.value)}`));
                if ((role === "stack" && position === entries.length - 1) || (role === "deque" && (position === 0 || position === entries.length - 1))) item.append(element("span", "al-cell-markers", role === "stack" ? "top" : position === 0 ? "front" : "back"));
                row.append(item);
            });
            storage.append(row);
            if (ctx.follow) row.scrollTop = row.scrollHeight;
        }
        if (view.delta && (view.delta.added?.length || view.delta.removed?.length)) {
            readouts(root, [
                ...(view.delta.added?.length ? [{label: "Added since previous capture", value: view.delta.added.map(printable).join(", ")}] : []),
                ...(view.delta.removed?.length ? [{label: "Removed since previous capture", value: view.delta.removed.map(printable).join(", ")}] : []),
            ]);
        }
        if (Array.isArray(view.source_values)) {
            const source = section(root, `Source · ${view.source_name || "sequence"}`);
            const kept = new Set(entries.map((entry) => integer(entry.index)).filter((index) => index !== null));
            sequence(source, view, ctx, {values: view.source_values, texts: view.source_values_text || view.source_values, key: "source", offset: view.source_offset || 0, label: view.source_name || "source", inRange: (index) => kept.has(index), followIndex: activeIndex(view)});
        } else note(root, "Source values are unavailable; entries show only the captured container.");
        readouts(root, view.readouts);
    }

    function fenwick(root, view, ctx) {
        title(root, "Fenwick tree (BIT)", view.name || "tree");
        operation(root, view);
        const nodes = view.nodes || [];
        const indexes = nodes.map((node) => integer(node.index ?? node.id));
        const values = nodes.map((node) => node.value);
        const access = new Set((view.accesses || []).map(integer));
        const marks = markerMap(view);
        access.forEach((index) => {
            if (index !== null && !marks.has(index)) marks.set(index, [{index, label: index === integer(view.current) ? "current" : "accessed"}]);
        });
        if (nodes.length) {
            note(root, "Each tree entry stores an aggregate over its labelled range.");
            sequence(root, view, ctx, {values, texts: nodes.map((node) => node.value_text ?? node.value), indexes, markers: marks, label: view.name || "BIT", extra: (_index, position) => `[${nodes[position].low}..${nodes[position].high}]`, dim: ctx.focus && access.size ? (index) => access.has(index) : null});
            if (access.size) {
                const coverage = section(root, "Ranges accessed at this step");
                const list = element("ul", "al-range-list");
                nodes.filter((node) => access.has(integer(node.index))).forEach((node) => list.append(element("li", "", `${view.name || "tree"}[${node.index}] covers [${node.low}..${node.high}] = ${printable(node.value_text ?? node.value)}`)));
                if (list.childElementCount) coverage.append(list);
                else note(coverage, "Accessed indices are outside the captured entries.");
            }
        } else note(root, "No positive BIT indices were captured at this step.");
        readouts(root, view.readouts);
    }

    function stringMatch(root, view, ctx) {
        title(root, "String matching", view.name || "text and pattern");
        operation(root, view);
        const text = typeof view.text === "string" ? [...view.text] : null;
        const pattern = typeof view.pattern === "string" ? [...view.pattern] : null;
        const alignment = integer(view.alignment);
        if (text && pattern) {
            readouts(root, [{label: "Text index", value: view.i ?? "unavailable"}, {label: "Pattern index", value: view.j ?? "unavailable"}, {label: "Alignment", value: alignment ?? "unavailable"}]);
            if (alignment === null) note(root, "Alignment is unavailable at this step; the strings are shown separately.");
            const textSection = section(root, alignment === null ? "Text" : "Text and aligned pattern");
            if (alignment !== null) alignedStrings(textSection, view, ctx, text, pattern, alignment);
            const markers = new Map();
            if (integer(view.i) !== null) markers.set(integer(view.i), [{label: "i"}]);
            if (alignment === null) {
                sequence(textSection, view, ctx, {values: text, texts: text.map((char) => char === " " ? "␠" : char), markers, key: "text", offset: 0, label: "text", followIndex: integer(view.i), written: new Set()});
                const patternSection = section(root, "Pattern");
                const patternMarkers = new Map();
                if (integer(view.j) !== null) patternMarkers.set(integer(view.j), [{label: "j"}]);
                sequence(patternSection, view, ctx, {values: pattern, texts: pattern.map((char) => char === " " ? "␠" : char), markers: patternMarkers, key: "pattern", offset: 0, label: "pattern", followIndex: integer(view.j), written: new Set()});
            }
            if (view.comparison && view.operation?.evidence === "trace") {
                const comparison = view.comparison;
                readouts(root, [{label: "Comparison", value: `${printable(comparison.left)} ${comparison.equal ? "=" : "≠"} ${printable(comparison.right)}`}]);
            }
        } else {
            note(root, "Text or pattern is unavailable at this step.");
            (view.rows || []).forEach((row) => {
                const block = section(root, row.label || row.name || "Captured sequence");
                sequence(block, {...view, markers: row.markers || []}, ctx, {values: row.values || [], offset: row.offset || 0, label: row.name, key: row.name, written: new Set()});
            });
        }
        if (Array.isArray(view.prefix)) {
            const prefix = section(root, "Prefix / failure table");
            const prefixName = view.prefix_name || "prefix";
            const writes = view.operation?.evidence === "trace" ? (view.operation.writes || []).filter((entry) => entry.name === prefixName).map((entry) => integer(entry.index)).filter((index) => index !== null) : [];
            sequence(prefix, view, ctx, {values: view.prefix, key: "prefix", offset: 0, label: prefixName, markers: new Map(), written: new Set(writes)});
        }
        readouts(root, view.readouts);
    }

    function alignedStrings(root, view, ctx, text, pattern, alignment) {
        const pageSize = ctx.target.clientWidth < 440 ? 8 : 16;
        const key = modeKey(view, "alignment");
        const length = Math.max(text.length, alignment + pattern.length, 0);
        let start = pages.get(key) || 0;
        start = Math.min(start, Math.max(0, Math.floor((length - 1) / pageSize) * pageSize));
        const current = integer(view.i);
        if (ctx.follow && current !== null && current >= 0 && current < length) start = Math.floor(current / pageSize) * pageSize;
        pages.set(key, start);
        const end = Math.min(length, start + pageSize);
        const toolbar = element("div", "al-sequence-toolbar");
        toolbar.append(element("span", "al-muted", length ? `Text indices ${start}–${end - 1} · pattern starts at ${alignment}` : "Empty strings"));
        if (length > pageSize) {
            const buttons = element("div", "al-page-buttons");
            [["Previous", -pageSize, start === 0], ["Next", pageSize, end === length]].forEach(([label, delta, disabled]) => {
                const button = element("button", "al-page-button", label);
                button.type = "button";
                button.disabled = disabled;
                button.setAttribute("aria-label", `${label} aligned characters`);
                button.addEventListener("click", () => {
                    pages.set(key, start + delta);
                    render(view, {...ctx, follow: false});
                    const replacement = [...ctx.target.querySelectorAll(".al-page-button")].find((item) => item.getAttribute("aria-label") === button.getAttribute("aria-label"));
                    if (replacement && !replacement.disabled) replacement.focus();
                });
                buttons.append(button);
            });
            toolbar.append(buttons);
        }
        root.append(toolbar);
        const grid = element("div", "al-match-grid");
        grid.style.setProperty("--match-columns", String(Math.max(1, end - start)));
        const visible = (char) => char === " " ? "␠" : char === "\n" ? "↵" : char === "\t" ? "⇥" : char;
        for (let index = start; index < end; index += 1) {
            const patternIndex = index - alignment;
            const inPattern = patternIndex >= 0 && patternIndex < pattern.length;
            const cell = element("div", "al-match-column");
            if (index === current) cell.classList.add("is-active");
            cell.append(element("span", "al-cell-index", index));
            const textChar = element("span", "al-match-character", index < text.length ? visible(text[index]) : "·");
            textChar.title = index < text.length ? `text[${index}] = ${text[index]}` : "Outside text";
            cell.append(textChar);
            const patternChar = element("span", `al-match-character${inPattern ? "" : " is-empty"}`, inPattern ? visible(pattern[patternIndex]) : "·");
            patternChar.title = inPattern ? `pattern[${patternIndex}] = ${pattern[patternIndex]}` : "Outside pattern";
            cell.append(patternChar);
            cell.append(element("span", "al-cell-index", inPattern ? `p${patternIndex}` : ""));
            grid.append(cell);
        }
        root.append(grid);
        note(root, "Upper row: text. Lower row: pattern. Yellow border: current text position.");
    }

    function trie(root, view, ctx) {
        const nodes = view.nodes || [];
        const edges = view.edges || [];
        title(root, "Trie", `${view.name || "trie"} · ${nodes.length} captured nodes`);
        operation(root, view);
        const byId = new Map(nodes.map((node) => [String(node.id), node]));
        const children = new Map(nodes.map((node) => [String(node.id), []]));
        const parent = new Map();
        edges.forEach((edge) => {
            const from = String(edge.source), to = String(edge.target);
            if (!byId.has(from) || !byId.has(to)) return;
            children.get(from).push({id: to, label: edge.label});
            parent.set(to, from);
        });
        const path = new Set((view.path || []).map(String));
        if (view.current !== null && view.current !== undefined) {
            let cursor = String(view.current);
            while (byId.has(cursor) && !path.has(cursor)) {
                path.add(cursor);
                cursor = parent.get(cursor);
            }
        }
        const key = modeKey(view, "folded");
        const folded = foldedTries.get(key) || new Set();
        foldedTries.set(key, folded);
        const roots = nodes.filter((node) => !parent.has(String(node.id)));
        const tree = element("ul", "al-trie-tree");
        tree.setAttribute("role", "tree");
        tree.setAttribute("aria-label", "Captured prefix tree");
        let count = 0;
        const visited = new Set();
        const addNode = (id, destination, depth, edgeLabel) => {
            if (visited.has(id) || count >= 40) return;
            visited.add(id);
            count += 1;
            const node = byId.get(id);
            const descendants = children.get(id) || [];
            const item = element("li", "al-trie-item");
            item.setAttribute("role", "treeitem");
            item.setAttribute("aria-level", String(depth + 1));
            const row = element("div", "al-trie-row");
            row.style.setProperty("--trie-depth", String(Math.min(depth, 10)));
            if (path.has(id)) row.classList.add("is-on-path");
            if (String(view.current) === id) row.classList.add("is-current");
            const expanded = descendants.length && (!folded.has(id) || (ctx.follow && path.has(id)));
            const control = element("button", "al-trie-control", descendants.length ? expanded ? "−" : "+" : "·");
            control.type = "button";
            control.setAttribute("aria-label", `${node.path || node.label || "root"}${node.terminal ? ", terminal" : ""}, node ${id}`);
            if (descendants.length) {
                control.setAttribute("aria-expanded", String(Boolean(expanded)));
                item.setAttribute("aria-expanded", String(Boolean(expanded)));
                control.addEventListener("click", () => {
                    if (expanded) folded.add(id); else folded.delete(id);
                    render(view, {...ctx, follow: false});
                    const replacement = ctx.target.querySelector(`[data-trie-id="${CSS.escape(id)}"] > .al-trie-row > button`);
                    replacement?.focus();
                });
            }
            item.dataset.trieId = id;
            row.append(control);
            if (edgeLabel !== undefined) row.append(element("span", "al-trie-edge-label", printable(edgeLabel) || "ε"));
            row.append(element("span", "al-trie-prefix", node.path ? node.path : node.label || `node ${id}`));
            if (node.terminal) row.append(element("span", "al-trie-terminal", "end"));
            if (node.value !== undefined) row.append(element("span", "al-muted", node.value));
            item.append(row);
            destination.append(item);
            if (expanded) {
                const group = element("ul", "al-trie-group");
                group.setAttribute("role", "group");
                descendants.forEach((child) => {
                    if (ctx.focus && path.size && !path.has(id) && !path.has(child.id)) return;
                    addNode(child.id, group, depth + 1, child.label);
                });
                if (group.childElementCount) item.append(group);
            }
        };
        roots.forEach((node) => addNode(String(node.id), tree, 0));
        if (!roots.length && nodes.length) addNode(String(nodes[0].id), tree, 0);
        root.append(tree);
        if (nodes.length > count) note(root, `${count} nodes shown; other branches are folded, filtered, or beyond the 40-node display limit.`);
        note(root, "Edge letters build the prefix. An end marker comes from a captured terminal field.");
        if (view.character !== null && view.character !== undefined) readouts(root, [{label: "Character", value: view.character}]);
        readouts(root, view.readouts);
    }

    function render(view, ctx) {
        if (!view || !supported.has(view.renderer) || !ctx?.target) return false;
        const root = element("section", `algorithm-lens al-${view.renderer}`);
        root.setAttribute("aria-label", `${view.renderer.replaceAll("_", " ")} visualization`);
        ctx.target.replaceChildren(root);
        if (!view.ready) {
            title(root, {heap: "Heap", window: "Window", monotonic: "Monotonic container", fenwick: "Fenwick tree", string_match: "String matching", trie: "Trie"}[view.renderer]);
            note(root, "Waiting for the program to construct this state.");
            return true;
        }
        ({heap, window: windowLens, monotonic, fenwick, string_match: stringMatch, trie}[view.renderer])(root, view, ctx);
        if (view.carried) note(root, "Last captured state; this data is outside the current scope.", "al-status");
        if (view.truncated || view.partial) note(root, `Partial capture${view.length ? ` of ${view.length} items` : ""}. Only values retained in the trace can be inspected.`, "al-status");
        (view.notes || []).forEach((text) => note(root, text));
        return true;
    }

    window.AlgorithmLenses = Object.freeze({render});
})();
