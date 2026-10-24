// The data panel: one renderer per view (grid, bars, cells, graph, trees, call chain).

const SVG_NS = "http://www.w3.org/2000/svg";

function svgElement(tag, attributes = {}) {
    const element = document.createElementNS(SVG_NS, tag);
    Object.entries(attributes).forEach(([name, value]) => element.setAttribute(name, value));
    return element;
}

function enableSvgNodeDragging({
    svg,
    nodeElements,
    positions,
    updateEdges,
    positionStore,
    nodeWidth,
    nodeHeight,
    centered,
}) {
    let drag = null;
    const viewBox = svg.viewBox.baseVal;
    // The screen CTM accounts for CSS scaling and preserveAspectRatio letterboxing,
    // so the dragged node stays under the pointer at any rendered size.
    const pointerPosition = (event) => {
        const matrix = svg.getScreenCTM();
        if (!matrix) return {x: 0, y: 0};
        const point = new DOMPoint(event.clientX, event.clientY).matrixTransform(matrix.inverse());
        return {x: point.x, y: point.y};
    };
    const finish = (event, group) => {
        if (!drag || drag.pointerId !== event.pointerId) return;
        drag = null;
        group.classList.remove("dragging");
        if (group.hasPointerCapture(event.pointerId)) group.releasePointerCapture(event.pointerId);
    };

    nodeElements.forEach((group, nodeId) => {
        group.addEventListener("pointerdown", (event) => {
            if (event.button !== 0 || drag) return;
            const point = pointerPosition(event);
            const position = positions.get(nodeId);
            drag = {
                nodeId,
                pointerId: event.pointerId,
                offsetX: point.x - position.x,
                offsetY: point.y - position.y,
            };
            // Raise the node before capturing: re-inserting a captured element can release capture.
            group.parentNode.append(group);
            group.classList.add("dragging");
            group.setPointerCapture(event.pointerId);
            event.preventDefault();
        });
        group.addEventListener("pointermove", (event) => {
            if (!drag || drag.nodeId !== nodeId || drag.pointerId !== event.pointerId) return;
            const point = pointerPosition(event);
            const halfWidth = centered ? nodeWidth / 2 : 0;
            const halfHeight = centered ? nodeHeight / 2 : 0;
            const minX = centered ? halfWidth : 4;
            const minY = centered ? halfHeight : 4;
            const maxX = viewBox.width - (centered ? halfWidth : nodeWidth) - 4;
            const maxY = viewBox.height - (centered ? halfHeight : nodeHeight) - 4;
            const position = {
                x: Math.min(Math.max(minX, point.x - drag.offsetX), maxX),
                y: Math.min(Math.max(minY, point.y - drag.offsetY), maxY),
            };
            positions.set(nodeId, position);
            positionStore.set(nodeId, {...position});
            group.setAttribute("transform", `translate(${position.x} ${position.y})`);
            updateEdges();
        });
        group.addEventListener("pointerup", (event) => finish(event, group));
        group.addEventListener("pointercancel", (event) => finish(event, group));
        group.addEventListener("lostpointercapture", (event) => finish(event, group));
    });
}

function truncate(text, maxLength) {
    const value = String(text ?? "");
    return value.length > maxLength ? `${value.slice(0, maxLength - 1)}…` : value;
}

function renderAlgorithmProfile(profile) {
    const algorithm = profile || {
        name: "General Python execution",
        confidence: 0,
        evidence: [],
    };
    elements.algorithmDetectedName.textContent = algorithm.name;
    // The name is a guess from code patterns; its score is a ranking, not a probability, so no
    // percentage is shown as if it were one.
    const manual = algorithm.manual_applied ?? (algorithm.bindings?.mode && algorithm.bindings.mode !== "auto");
    elements.algorithmConfidence.textContent = manual ? "手動配對" : "自動推測";
    if (manual) delete elements.algorithmConfidence.dataset.term;
    else elements.algorithmConfidence.dataset.term = "guessed from the code";
    elements.algorithmConfidence.className = "confidence-badge";
    elements.algorithmEvidence.textContent = (algorithm.evidence || []).join(", ") || "未符合特定模式";
}

function renderCompactHeading(view) {
    const renderer = view?.renderer;
    const label = ["array", "cells"].includes(renderer) ? "陣列" : COMPACT_RENDERER_LABELS[renderer] || "資料";
    const parts = [label, view?.name].filter(Boolean);
    if (view?.ready && ["array", "cells"].includes(renderer)) {
        const length = view.length ?? view.total_length ?? view.captured_length ?? view.values?.length;
        if (Number.isInteger(length)) parts.push(`${length} 項`);
    }
    elements.algorithmName.textContent = parts.join(" · ");
    elements.algorithmName.title = parts.join(" · ");
}

function renderAlgorithm(visualization) {
    renderCompactHeading(visualization);
    elements.visualScaleInfo.hidden = true;
    elements.visualScaleInfo.textContent = "";
    const scroll = {left: elements.algorithmView.scrollLeft, top: elements.algorithmView.scrollTop};
    elements.algorithmView.replaceChildren();
    elements.algorithmView.className = "algorithm-canvas";
    // Which variable is drawn, so a reference to it (`row ↪ matrix[1]`) can light up its part.
    elements.algorithmView.dataset.view = visualization?.name || "";
    if (visualization?.pending) {
        renderAlgorithmWaiting(`重新執行以顯示 ${visualization.name}…`);
        return;
    }
    if (!visualization) {
        renderAlgorithmWaiting("此步尚無可顯示資料");
        return;
    }
    const context = {
        target: elements.algorithmView, result: state.result,
        step: state.result?.steps[state.currentStep], index: state.currentStep,
        focus: state.focus, follow: state.follow, bindings: state.bindings, goToStep: stepManually,
    };
    const renderers = {
        grid: renderGridAlgorithm,
        array: renderArrayAlgorithm,
        cells: renderCellsAlgorithm,
        graph: renderGraphAlgorithm,
        segment_tree: renderSegmentTreeAlgorithm,
        recursion_tree: renderRecursionTreeAlgorithm,
        call_tree: renderCallTreeAlgorithm,
        execution: renderExecutionAlgorithm,
    };
    const handled = window.DebuggerFocus?.render(visualization, context)
        || window.AlgorithmLenses?.render(visualization, context);
    if (!handled) {
        (renderers[visualization.renderer] || renderExecutionAlgorithm)(visualization);
        window.DebuggerFocus?.decorate(visualization, context);
    }
    if (elements.algorithmView.querySelector(".focus-operation")) {
        for (const [chip, term] of [[".focus-read-chip", "Reading"], [".focus-write-chip", "Written"]]) {
            if (elements.algorithmView.querySelector(chip)) {
                elements.algorithmView.querySelectorAll(`.algorithm-legend [data-term="${term}"]`).forEach((item) => item.remove());
            }
        }
        elements.algorithmView.querySelectorAll(".algorithm-legend:empty").forEach((item) => item.remove());
    }
    if (["array", "cells"].includes(visualization.renderer)) {
        // Paging can add a capture notice after the base renderer has hidden empty metadata.
        const meta = elements.algorithmView.querySelector(".algorithm-meta");
        const summary = meta?.querySelector(":scope > span:first-child");
        if (summary?.textContent.trim()) summary.hidden = false;
        if (meta) meta.hidden = ![...meta.children].some((item) => !item.hidden && item.textContent.trim());
    }
    if (!state.follow) {
        elements.algorithmView.scrollLeft = scroll.left;
        elements.algorithmView.scrollTop = scroll.top;
    }
}

function renderAlgorithmWaiting(message) {
    const waiting = document.createElement("div");
    waiting.className = "algorithm-waiting";
    waiting.textContent = message;
    elements.algorithmView.append(waiting);
}

function renderGridAlgorithm(view) {
    if (!view.ready) {
        renderAlgorithmWaiting("等待建立表格…");
        return;
    }
    const rows = view.rows || [];
    const columns = Math.max(0, ...rows.map((row) => row.length));
    const meta = document.createElement("div");
    meta.className = "algorithm-meta";
    const dimensions = document.createElement("span");
    dimensions.textContent = `${view.name || "grid"}, ${rows.length} × ${columns}${view.truncated ? ", clipped" : ""}${view.carried ? ", last known state" : ""}`;
    // Only the marks this step really has are explained.
    const marked = (cells) => (cells || []).some((row) => (Array.isArray(row) ? row.some(Boolean) : Boolean(row)));
    // The cells the code points at are drawn three ways, so each gets its own legend entry.
    const roles = new Set((view.active || []).map((cell) => cell.role));
    const legend = [
        ["visited", "Visited", marked(view.visited)],
        ["frontier", "Frontier", marked(view.frontier)],
        ["active", "Current", [...roles].some((role) => role !== "scan" && role !== "candidate")],
        ["scan", "Scanning", roles.has("scan")],
        ["candidate", "Neighbour being checked", roles.has("candidate")],
        ["written", "Written", marked(view.written)],
        ["wall", "Blocked", marked(view.walls)],
    ].filter(([, , shown]) => shown).map(([kind, label]) => [kind, label]);
    meta.append(dimensions);
    if (legend.length) meta.append(algorithmLegend(legend));
    // The cells the code holds, as numbers, and the queue in the order it will be taken.
    const details = [...(view.coordinates || [])];
    if (view.queue) details.push(`${view.queue.name}: ${view.queue.entries.join(" ") || "empty"}`);
    if (details.length) {
        const readouts = document.createElement("div");
        readouts.className = "algorithm-readouts grid-readouts";
        details.forEach((text) => readouts.append(textSpan(text, "algorithm-readout")));
        meta.append(readouts);
    }
    const written = new Set((view.written || []).map((cell) => `${cell.row}:${cell.column}`));

    const visited = new Set();
    (view.visited || []).forEach((row, rowIndex) => {
        row.forEach((cell, columnIndex) => {
            if (cell) visited.add(`${rowIndex}:${columnIndex}`);
        });
    });
    const frontier = new Set((view.frontier || []).map((cell) => `${cell.row}:${cell.column}`));
    const walls = new Set((view.walls || []).map((cell) => `${cell.row}:${cell.column}`));
    const active = new Map((view.active || []).map((cell) => [`${cell.row}:${cell.column}`, cell.role]));

    // Measure the space left under the legend, then pick the largest cell that fits it.
    elements.algorithmView.append(meta);
    const area = algorithmViewArea(meta);
    const gap = 3;
    const fitted = Math.floor(Math.min(
        (area.width - gap * (columns - 1)) / Math.max(1, columns),
        (area.height - gap * (rows.length - 1)) / Math.max(1, rows.length),
    ));
    const cellSize = Math.max(24, Math.min(80, fitted));

    // Shrink the text when the longest value would not fit inside a cell (for example a dp table).
    const longestText = Math.max(1, ...rows.flat().map((value) => gridCellText(value).length));
    const fontSize = Math.max(9, Math.min(cellSize * 0.38, (cellSize - 6) / (longestText * 0.62)));

    const grid = document.createElement("div");
    grid.className = "algorithm-grid";
    grid.style.setProperty("--cell", `${cellSize}px`);
    grid.style.setProperty("--cell-font", `${fontSize.toFixed(1)}px`);
    grid.style.gridTemplateColumns = `repeat(${columns}, ${cellSize}px)`;
    rows.forEach((row, rowIndex) => {
        row.forEach((value, columnIndex) => {
            const key = `${rowIndex}:${columnIndex}`;
            const cell = document.createElement("div");
            cell.className = "algorithm-cell";
            cell.dataset.row = String(rowIndex);
            if (walls.has(key) || String(value) === "#") cell.classList.add("wall");
            if (visited.has(key)) cell.classList.add("visited");
            if (frontier.has(key)) cell.classList.add("frontier");
            if (active.has(key)) cell.classList.add(active.get(key));
            if (written.has(key)) cell.classList.add("written");
            // Numbers beyond 2^53 print from their exact text twin.
            const exact = view.rows_text?.[rowIndex]?.[columnIndex] ?? value;
            cell.textContent = gridCellText(exact);
            cell.title = `row ${rowIndex}, column ${columnIndex}: ${value === "\0" ? "unset" : String(exact)}`;
            grid.append(cell);
        });
    });
    elements.algorithmView.append(grid);
}

// Booleans read as T/F so a visited table fits in its cells; `.` cells read as a dot.
// NUL is a C++ char cell nothing has written yet (a[i][0] of a 1-indexed grid): left blank.
function gridCellText(value) {
    if (value === true) return "T";
    if (value === false) return "F";
    if (value === "\0") return "";
    return String(value) === "." ? "·" : String(value);
}

function algorithmViewArea(meta = null) {
    const style = getComputedStyle(elements.algorithmView);
    const metaHeight = meta ? meta.offsetHeight + parseFloat(getComputedStyle(meta).marginBottom) : 0;
    return {
        width: elements.algorithmView.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight),
        height: elements.algorithmView.clientHeight - parseFloat(style.paddingTop) - parseFloat(style.paddingBottom) - metaHeight,
    };
}

function algorithmLegend(items) {
    const legend = document.createElement("div");
    legend.className = "algorithm-legend";
    items.forEach(([className, label]) => {
        const item = document.createElement("span");
        item.className = "legend-item";
        const swatch = document.createElement("span");
        swatch.className = `legend-swatch ${className}`;
        const text = document.createElement("span");
        text.textContent = {
            Reading: "讀取", Written: "變更", New: "新增", Visited: "已訪問", Frontier: "待處理", Current: "目前",
            Scanning: "掃描位置", "Neighbour being checked": "檢查中的鄰格", Blocked: "障礙",
        }[label] || label;
        item.dataset.term = label;
        item.append(swatch, text);
        legend.append(item);
    });
    return legend;
}

function renderArrayAlgorithm(view) {
    if (!view.ready) {
        renderAlgorithmWaiting("等待建立陣列…");
        return;
    }
    const values = view.values || [];
    // Entries the highlighted line pushed are blue on this step only.
    const added = new Set(view.added || []);
    // Labels print the exact digits: numbers beyond 2^53 reach the browser rounded.
    const texts = (view.values_text || values).map(String);
    // "Infinity" placeholders (INF = 1e9) are drawn apart and do not set the scale.
    const infinite = new Set(view.infinite || []);
    const finite = values.map(Number).filter((value, index) => !infinite.has(index) && Number.isFinite(value));
    const highest = Math.max(0, ...finite);
    const lowest = Math.min(0, ...finite);
    const markers = new Map();
    (view.markers || []).forEach((marker) => {
        if (!markers.has(marker.index)) markers.set(marker.index, []);
        markers.get(marker.index).push(marker);
    });
    const interval = view.interval || null;
    const written = new Set(view.written || []);

    const meta = indexedViewMeta(view, values.length);
    elements.algorithmView.append(meta);
    const area = algorithmViewArea(meta);
    const columnGap = 8;
    const chartPadding = {x: 36, y: 48};
    // Index label, marker row, and the gaps between them.
    const footSpace = 46;
    const columnWidth = Math.max(26, Math.min(72, Math.floor(
        (area.width - chartPadding.x - columnGap * (values.length - 1)) / Math.max(1, values.length),
    )));
    // A label wider than its column is turned on its side instead of overlapping its neighbours.
    const longest = Math.max(1, ...values.map((value, index) => (infinite.has(index) ? 1 : texts[index].length)));
    const vertical = longest * 8 > columnWidth;
    const labelRoom = vertical ? Math.min(150, longest * 8 + 6) : 20;
    const plotHeight = Math.max(80, area.height - chartPadding.y - footSpace);
    // Positive bars rise from the zero line and negative ones hang below it.
    const barRoom = Math.max(40, plotHeight - labelRoom * (lowest < 0 ? 2 : 1));
    const span = Math.max(1, highest - lowest);
    const upper = labelRoom + (barRoom * highest) / span;
    const lower = lowest < 0 ? (barRoom * -lowest) / span + labelRoom : 0;
    const barHeight = (value) => (value === 0 ? 0 : Math.max(3, (Math.abs(value) / span) * barRoom));

    const chart = document.createElement("div");
    chart.className = "array-visualizer";
    chart.classList.toggle("vertical-values", vertical);
    chart.style.setProperty("--column", `${columnWidth}px`);
    values.forEach((value, index) => {
        const column = document.createElement("div");
        column.className = "array-column";
        column.dataset.index = String(index);
        const indexMarkers = markers.get(index) || [];
        indexMarkers.forEach((marker) => column.classList.add(marker.role));
        // Marked indexes (for example the fixed `i` in three-sum) stay visible outside the window.
        if (interval && !indexMarkers.length && (index < interval.low || index > interval.high)) {
            column.classList.add("outside-bound");
        }
        if (written.has(index)) column.classList.add("written");
        if (added.has(index)) column.classList.add("added");
        const plot = document.createElement("div");
        plot.className = "array-plot";
        plot.style.height = `${upper + lower}px`;
        plot.style.setProperty("--zero", `${upper}px`);
        const label = document.createElement("span");
        label.className = "array-value";
        const bar = document.createElement("div");
        bar.className = "array-bar";
        const number = Number(value);
        if (infinite.has(index) || !Number.isFinite(number)) {
            // Shown as ∞ at a fixed height; the exact placeholder is in the tooltip.
            column.classList.add("infinite");
            label.textContent = "∞";
            label.title = texts[index];
            bar.style.height = `${Math.max(12, (upper - labelRoom) * 0.5)}px`;
            bar.style.bottom = `${lower}px`;
            label.style.bottom = `${lower + Math.max(12, (upper - labelRoom) * 0.5) + 4}px`;
        } else {
            const height = barHeight(number);
            label.textContent = texts[index];
            label.title = texts[index];
            bar.style.height = `${height}px`;
            if (number < 0) {
                column.classList.add("negative");
                bar.style.top = `${upper}px`;
                label.style.top = `${upper + height + 4}px`;
            } else {
                bar.style.bottom = `${lower}px`;
                label.style.bottom = `${lower + height + 4}px`;
            }
        }
        plot.append(bar, label);
        const indexNode = document.createElement("span");
        indexNode.className = "array-index";
        const itemLabel = view.labels?.[index];
        indexNode.textContent = itemLabel === undefined || itemLabel === null
            ? String(index)
            : `#${itemLabel}`;
        if (itemLabel !== undefined && itemLabel !== null) {
            indexNode.title = `sorted position ${index} · original index ${itemLabel}`;
        }
        column.append(plot, indexNode);
        if (indexMarkers.length) {
            const marker = document.createElement("span");
            marker.className = "array-marker";
            marker.textContent = indexMarkers.map((item) => item.label).join(",");
            column.append(marker);
        }
        chart.append(column);
    });
    elements.algorithmView.append(chart);
}

// Summary, read/write legend, and readouts shared by the bar and cell views.
function indexedViewMeta(view, count) {
    const meta = document.createElement("div");
    meta.className = "algorithm-meta";
    const summary = document.createElement("span");
    // A list too long to read whole says how much is drawn: `a, 0–49 of 80`.
    const partial = view.truncated || (view.length != null && view.length > count);
    summary.textContent = `${partial ? `已顯示 ${count}${view.length != null ? ` / ${view.length}` : ""} 項 · 其餘未擷取` : ""}${view.carried ? `${partial ? " · " : ""}沿用上次狀態` : ""}`;
    summary.hidden = !summary.textContent && !(view.beyond || []).length;
    if (view.carried) summary.dataset.term = "last known state";
    else if (view.truncated || view.length) summary.dataset.term = "clipped";
    (view.beyond || []).forEach((entry) => {
        summary.append(textSpan(`${entry.label} = ${entry.index} · 顯示範圍外`, "beyond-note"));
    });
    const details = document.createElement("div");
    details.className = "algorithm-meta-details";
    if (view.readouts?.length) {
        const readouts = document.createElement("div");
        readouts.className = "algorithm-readouts";
        view.readouts.filter((readout) => !isDisplayedArraySize(readout.label, readout, view)).forEach((readout) => {
            const item = document.createElement("span");
            item.className = "algorithm-readout";
            item.textContent = `${readout.label} = ${numberText(readout)}`;
            readouts.append(item);
        });
        if (readouts.childElementCount) details.append(readouts);
    }
    meta.append(summary, details);
    meta.hidden = summary.hidden && !details.childElementCount;
    return meta;
}

function renderCellsAlgorithm(view) {
    if (!view.ready) {
        renderAlgorithmWaiting("等待建立陣列…");
        return;
    }
    const values = view.values || [];
    const added = new Set(view.added || []);
    const markers = new Map();
    (view.markers || []).forEach((marker) => {
        if (!markers.has(marker.index)) markers.set(marker.index, []);
        markers.get(marker.index).push(marker);
    });
    const interval = view.interval || null;
    const written = new Set(view.written || []);

    const meta = indexedViewMeta(view, values.length);
    elements.algorithmView.append(meta);
    // Fit every cell on one row when there is room; long lists wrap onto more rows.
    const area = algorithmViewArea(meta);
    const gap = 4;
    const longest = Math.max(1, ...values.map((value) => String(value).length));
    const minimumWidth = Math.min(160, Math.max(44, longest * 9 + 16));
    const cellWidth = Math.max(minimumWidth, Math.min(96, Math.floor(
        (area.width - gap * (values.length - 1)) / Math.max(1, values.length),
    )));

    const row = document.createElement("div");
    row.className = "cells-view";
    row.style.setProperty("--cell-width", `${cellWidth}px`);
    values.forEach((value, index) => {
        const item = document.createElement("div");
        item.className = "cells-item";
        item.dataset.index = String(index);
        const indexMarkers = markers.get(index) || [];
        indexMarkers.forEach((marker) => item.classList.add(marker.role));
        if (interval && !indexMarkers.length && (index < interval.low || index > interval.high)) {
            item.classList.add("outside-bound");
        }
        if (written.has(index)) item.classList.add("written");
        if (added.has(index)) item.classList.add("added");
        const indexNode = document.createElement("span");
        indexNode.className = "cells-index";
        indexNode.textContent = String(index);
        const valueNode = document.createElement("span");
        valueNode.className = "cells-value";
        valueNode.textContent = String(value);
        valueNode.title = String(value);
        const markerNode = document.createElement("span");
        markerNode.className = "cells-marker";
        markerNode.textContent = indexMarkers.map((marker) => marker.label).join(",");
        item.append(indexNode, valueNode, markerNode);
        row.append(item);
    });
    elements.algorithmView.append(row);
}

// Edge direction picked in the graph view; "auto" follows the trace's guess.
function graphIsDirected(view) {
    if (state.graphDirection === "directed") return true;
    if (state.graphDirection === "undirected") return false;
    return Boolean(view.directed);
}

function graphDirectionPicker(view) {
    const picker = document.createElement("select");
    picker.className = "graph-direction-select";
    picker.setAttribute("aria-label", "Edge direction");
    picker.dataset.term = "Edge direction";
    picker.append(
        new Option(`auto (${view.directed ? "directed" : "undirected"})`, "auto"),
        new Option("directed", "directed"),
        new Option("undirected", "undirected"),
    );
    picker.value = state.graphDirection;
    picker.addEventListener("change", () => {
        state.graphDirection = picker.value;
        renderStep();
    });
    return picker;
}

function renderGraphAlgorithm(view) {
    if (!view.ready) {
        renderAlgorithmWaiting("等待建立圖…");
        return;
    }
    const nodes = view.nodes || [];
    const frontier = view.frontier?.items || [];
    const labels = view.labels?.values || {};
    // The queue (or stack) is listed above the graph in order, and its vertices get a dashed ring.
    const meta = document.createElement("div");
    meta.className = "algorithm-meta graph-meta";
    const summary = document.createElement("span");
    summary.className = "graph-frontier";
    const forest = view.layout === "forest";
    if (view.frontier) {
        // Whole entries when the queue holds pairs: `pq: (6, 2)  (8, 3)`.
        const entries = view.frontier.entries || view.frontier.items;
        const front = entries.length ? entries.join("  ") : "empty";
        summary.textContent = `${view.frontier.name}: ${front}`;
    } else if (forest) {
        summary.textContent = `${view.name}[v]: each arrow points to the parent; roots are on top`;
    } else {
        summary.textContent = `${view.name || "graph"}, ${nodes.length} vertices`;
    }
    if (view.edges_truncated || view.capture_truncated) {
        const note = document.createElement("span");
        note.className = "truncated-note";
        note.textContent = `${view.edges_truncated ? ` · drawing ${view.edges?.length || 0} of ${view.edges_total} captured edges` : ""}${view.capture_truncated ? " · adjacency partly captured" : ""}`;
        summary.append(note);
    }
    // Whether each edge was stored one way (arrows) or both ways is guessed from the whole
    // trace; a symmetric directed graph looks undirected, so the user can override the guess.
    const directed = forest || graphIsDirected(view);
    const edges = directed || !view.undirected ? view.edges || [] : view.undirected.map((position) => view.edges[position]);
    if (!forest && view.directed !== undefined) {
        summary.append(graphDirectionPicker(view));
    }
    if (view.pair_order) {
        // Which element of each adjacency pair was taken for the vertex; inferred, so said.
        const order = textSpan(` · pairs read as ${view.pair_order}`, "graph-direction");
        order.dataset.term = "pairs read as";
        summary.append(order);
    }
    const legend = forest ? [["active", "Current"]] : [["active", "Current"], ["visited", "Visited"]];
    if (view.checking) legend.push(["checking", "Edge being checked"]);
    // Per-vertex entries the highlighted line reads (`dis[n]`): ringed, and printed with their value.
    const reading = new Set((view.reading || []).map((entry) => entry.vertex));
    if (reading.size) legend.push(["reading", "Reading"]);
    // An answer path being built (`route`): its vertices and the edges between them, in order.
    const routeNodes = view.route ? [...view.route.items, ...(view.route.next ? [view.route.next] : [])] : [];
    const routeVertices = new Set(routeNodes);
    const routeEdges = new Set(routeNodes.slice(1).map((node, index) => [routeNodes[index], node].sort().join("|")));
    if (routeNodes.length) legend.push(["route", "Route"]);
    if (view.frontier) legend.push(["frontier", `In ${view.frontier.name}`]);
    meta.append(summary, algorithmLegend(legend));
    const readoutTexts = (view.reading || []).map((entry) => entry.text);
    if (view.route) readoutTexts.unshift(`${view.route.name}: ${view.route.items.join(" ")}`);
    if (readoutTexts.length) {
        const reads = document.createElement("div");
        reads.className = "algorithm-readouts grid-readouts";
        readoutTexts.forEach((text) => reads.append(textSpan(text, "algorithm-readout")));
        meta.append(reads);
    }
    elements.algorithmView.append(meta);
    // The viewBox matches the panel, so the graph fills it and nodes can be dragged to its edges.
    const area = algorithmViewArea(meta);
    const width = Math.max(320, Math.floor(area.width));
    const height = Math.max(160, Math.floor(area.height));
    const nodeRadius = 26;
    const centerX = width / 2;
    const centerY = height / 2;
    // An ellipse uses a wide panel better than a circle; 60px on each side leaves room for value labels.
    const radiusY = Math.max(40, height / 2 - nodeRadius - 16);
    const radiusX = Math.max(40, Math.min(width / 2 - nodeRadius - 60, radiusY * 2.2));
    const clampX = (x) => Math.min(Math.max(nodeRadius + 2, x), width - nodeRadius - 2);
    const clampY = (y) => Math.min(Math.max(nodeRadius + 2, y), height - nodeRadius - 2);
    const positions = new Map();
    // A forest uses its own parent arrows; a tree gets parent links from the backend.
    const parentLinks = forest
        ? view.edges || []
        : Object.entries(view.parents || {}).map(([child, parent]) => ({source: child, target: parent}));
    const treePositions = parentLinks.length ? layoutForest(nodes, parentLinks, width, height, nodeRadius) : new Map();
    nodes.forEach((node, index) => {
        const nodeId = String(node);
        const saved = state.algorithmGraphPositions.get(`${view.name || "graph"}:${nodeId}`);
        const angle = (Math.PI * 2 * index) / Math.max(1, nodes.length) - Math.PI / 2;
        const position = saved || treePositions.get(nodeId) || {
            x: centerX + Math.cos(angle) * radiusX,
            y: centerY + Math.sin(angle) * radiusY,
        };
        positions.set(nodeId, {x: clampX(position.x), y: clampY(position.y)});
    });
    const visited = new Set((view.visited || []).map(String));
    const queued = new Set(frontier.map(String));
    const svg = svgElement("svg", {class: "algorithm-graph-svg", viewBox: `0 0 ${width} ${height}`, width, height});
    if (directed) {
        const defs = svgElement("defs");
        const marker = svgElement("marker", {
            id: "graph-arrow", viewBox: "0 0 10 10", refX: "10", refY: "5",
            markerWidth: "7", markerHeight: "7", orient: "auto-start-reverse",
        });
        marker.append(svgElement("path", {class: "algorithm-graph-arrow", d: "M 0 0 L 10 5 L 0 10 z"}));
        defs.append(marker);
        svg.append(defs);
    }
    // Edges joining the same two vertices (a parallel edge, or a→b beside b→a) bend apart, so
    // each one and its weight stay visible; a lone edge is straight.
    const pairKey = (edge) => [String(edge.source), String(edge.target)].sort().join("|");
    const pairSizes = new Map();
    edges.forEach((edge) => pairSizes.set(pairKey(edge), (pairSizes.get(pairKey(edge)) || 0) + 1));
    const pairSeen = new Map();
    const edgeBend = (edge) => {
        const key = pairKey(edge);
        const position = pairSeen.get(key) || 0;
        pairSeen.set(key, position + 1);
        return (position - (pairSizes.get(key) - 1) / 2) * 28;
    };
    // The curve through a control point pushed `bend` px off the middle of the edge, measured
    // on the side fixed by the vertex order, so a→b and b→a bend to opposite sides.
    const edgeCurve = (edge, source, target, bend) => {
        const flip = String(edge.source) <= String(edge.target) ? 1 : -1;
        const dx = target.x - source.x;
        const dy = target.y - source.y;
        const length = Math.hypot(dx, dy) || 1;
        const normal = {x: (-dy / length) * flip, y: (dx / length) * flip};
        const control = {
            x: (source.x + target.x) / 2 + normal.x * bend * 2,
            y: (source.y + target.y) / 2 + normal.y * bend * 2,
        };
        return {control, normal};
    };
    // Directed edges stop at the target's rim so the arrowhead stays visible.
    const placeEdge = (path, edge, source, target, bend) => {
        const {control} = edgeCurve(edge, source, target, bend);
        const dx = target.x - control.x;
        const dy = target.y - control.y;
        const length = Math.hypot(dx, dy) || 1;
        const inset = directed ? nodeRadius + 3 : 0;
        const end = {x: target.x - (dx / length) * inset, y: target.y - (dy / length) * inset};
        path.setAttribute("d", `M ${source.x} ${source.y} Q ${control.x} ${control.y} ${end.x} ${end.y}`);
    };
    // A weight sits beside the middle of its edge, pushed off the line so both stay readable.
    const placeWeight = (text, edge, source, target, bend) => {
        const {control, normal} = edgeCurve(edge, source, target, bend);
        const side = bend < 0 ? -1 : 1;
        text.setAttribute("x", 0.25 * source.x + 0.5 * control.x + 0.25 * target.x + normal.x * 10 * side);
        text.setAttribute("y", 0.25 * source.y + 0.5 * control.y + 0.25 * target.y + normal.y * 10 * side);
    };
    const edgeElements = [];
    // The checked edge is one edge: matched by direction when drawn directed, and by weight,
    // so of two parallel edges (`1 → 3` weights 2 and 4) only the one being examined lights up.
    let checkedDrawn = false;
    const isChecked = (edge) => {
        const check = view.checking;
        if (!check || checkedDrawn) return false;
        const ends = directed
            ? String(edge.source) === String(check.source) && String(edge.target) === String(check.target)
            : pairKey(edge) === pairKey(check);
        return ends && (check.weight === undefined || String(edge.weight) === String(check.weight));
    };
    edges.forEach((edge) => {
        const source = positions.get(String(edge.source));
        const target = positions.get(String(edge.target));
        if (!source || !target) return;
        const bend = edgeBend(edge);
        const line = svgElement("path", {class: "algorithm-graph-edge"});
        // The edge from the current vertex to the neighbour the code is looking at.
        if (isChecked(edge)) {
            line.classList.add("checking");
            checkedDrawn = true;
        }
        if (routeEdges.has(pairKey(edge))) line.classList.add("on-route");
        if (directed) line.setAttribute("marker-end", "url(#graph-arrow)");
        placeEdge(line, edge, source, target, bend);
        svg.append(line);
        let weight = null;
        if (edge.weight !== undefined && edge.weight !== null) {
            weight = svgElement("text", {class: "algorithm-graph-weight"});
            weight.textContent = String(edge.weight);
            placeWeight(weight, edge, source, target, bend);
            svg.append(weight);
        }
        edgeElements.push({edge, line, weight, bend});
    });
    const nodeElements = new Map();
    nodes.forEach((node) => {
        const nodeId = String(node);
        const position = positions.get(nodeId);
        const classes = ["algorithm-graph-node"];
        if (visited.has(String(node))) classes.push("visited");
        if (String(view.current) === String(node)) classes.push("current");
        if (queued.has(nodeId)) classes.push("queued");
        if (reading.has(nodeId)) classes.push("reading");
        if (routeVertices.has(nodeId)) classes.push("on-route");
        const group = svgElement("g", {class: classes.join(" "), transform: `translate(${position.x} ${position.y})`});
        if (queued.has(nodeId)) group.append(svgElement("circle", {class: "queue-ring", r: String(nodeRadius + 5)}));
        if (reading.has(nodeId)) group.append(svgElement("circle", {class: "reading-ring", r: String(nodeRadius + 9)}));
        group.append(svgElement("circle", {r: String(nodeRadius)}));
        const label = svgElement("text");
        label.textContent = String(node);
        group.append(label);
        if (Object.hasOwn(labels, nodeId)) {
            // A per-vertex value such as dis[v], written beside the vertex.
            const value = svgElement("text", {class: "node-value", x: String(nodeRadius + 6), y: String(-nodeRadius + 6)});
            value.textContent = `${view.labels.name}=${view.labels.values_text?.[nodeId] ?? labels[nodeId]}`;
            group.append(value);
        }
        svg.append(group);
        nodeElements.set(nodeId, group);
    });
    const updateEdges = () => {
        edgeElements.forEach(({edge, line, weight, bend}) => {
            const source = positions.get(String(edge.source));
            const target = positions.get(String(edge.target));
            if (!source || !target) return;
            placeEdge(line, edge, source, target, bend);
            if (weight) placeWeight(weight, edge, source, target, bend);
        });
    };
    enableSvgNodeDragging({
        svg,
        nodeElements,
        positions,
        updateEdges,
        positionStore: {
            set(nodeId, position) {
                state.algorithmGraphPositions.set(`${view.name || "graph"}:${nodeId}`, position);
            },
        },
        nodeWidth: nodeRadius * 2,
        nodeHeight: nodeRadius * 2,
        centered: true,
    });
    elements.algorithmView.append(svg);
}

// Parent-pointer forest: roots on the top row, each subtree centred over its children.
function layoutForest(nodes, edges, width, height, nodeRadius) {
    const parentOf = new Map(edges.map((edge) => [String(edge.source), String(edge.target)]));
    const children = new Map(nodes.map((node) => [String(node), []]));
    parentOf.forEach((parent, child) => children.get(parent)?.push(child));
    const roots = nodes.map(String).filter((node) => !parentOf.has(node) || !children.has(parentOf.get(node)));
    const depth = new Map();
    const slots = new Map();
    let nextSlot = 0;
    const place = (node, level) => {
        if (depth.has(node)) return;
        depth.set(node, level);
        const kids = children.get(node) || [];
        kids.forEach((child) => place(child, level + 1));
        const placed = kids.filter((child) => slots.has(child));
        slots.set(node, placed.length
            ? (slots.get(placed[0]) + slots.get(placed[placed.length - 1])) / 2
            : nextSlot++);
    };
    roots.forEach((root) => place(root, 0));
    // Cycles cannot occur in a valid parent array, but never leave a vertex unplaced.
    nodes.map(String).forEach((node) => place(node, 0));
    const levels = Math.max(1, ...depth.values()) + 1;
    const gapX = Math.max(nodeRadius * 2 + 12, (width - nodeRadius * 2) / Math.max(1, nextSlot));
    const gapY = Math.min(110, (height - nodeRadius * 2 - 16) / Math.max(1, levels - 1));
    const left = (width - gapX * (nextSlot - 1)) / 2;
    const positions = new Map();
    slots.forEach((slot, node) => {
        positions.set(node, {x: left + slot * gapX, y: nodeRadius + 10 + depth.get(node) * gapY});
    });
    return positions;
}

const RECURSION_NODE = {height: 46, gapX: 18, gapY: 36, padding: 18, charWidth: 7.9};

// Lay out every call once per trace so nodes keep their place as the tree grows step by step.
function layoutRecursionTree(nodes) {
    const children = new Map();
    const roots = [];
    const ids = new Set(nodes.map((node) => node.id));
    nodes.forEach((node) => {
        if (!ids.has(node.parent)) roots.push(node);
        else children.set(node.parent, [...(children.get(node.parent) || []), node]);
    });
    const longest = Math.max(...nodes.map((node) => recursionNodeText(node).length));
    const width = Math.max(90, Math.min(300, Math.round(longest * RECURSION_NODE.charWidth + 24)));
    const positions = new Map();
    let leaves = 0;
    let maxDepth = 0;
    const place = (node, depth) => {
        maxDepth = Math.max(maxDepth, depth);
        const kids = children.get(node.id) || [];
        let x;
        if (!kids.length) {
            x = leaves * (width + RECURSION_NODE.gapX);
            leaves += 1;
        } else {
            kids.forEach((kid) => place(kid, depth + 1));
            x = (positions.get(kids[0].id).x + positions.get(kids[kids.length - 1].id).x) / 2;
        }
        positions.set(node.id, {x, y: depth * (RECURSION_NODE.height + RECURSION_NODE.gapY)});
    };
    roots.forEach((root) => place(root, 0));
    return {
        positions,
        nodeWidth: width,
        width: Math.max(width, leaves * (width + RECURSION_NODE.gapX) - RECURSION_NODE.gapX),
        height: (maxDepth + 1) * (RECURSION_NODE.height + RECURSION_NODE.gapY) - RECURSION_NODE.gapY,
    };
}

function recursionNodeText(node) {
    return node.order ? `#${node.order} ${node.label}` : node.label;
}

const SEGMENT_NODE = {height: 42, gapX: 10, levelGap: 34, padding: 16, charWidth: 8.4, baseHeight: 30};

// A segment tree: every node with its value and range, the running node, the calls on the
// stack, the nodes the line reads, and the original array under the leaves. Node positions
// come from the server (`layout`), computed once per trace.
function renderSegmentTreeAlgorithm(view) {
    const layout = (state.result?.algorithm?.views || []).find((item) => item.renderer === "segment_tree" && item.variable === view.name)?.layout;
    if (!layout || !view.ready) {
        renderAlgorithmWaiting("等待建立樹…");
        return;
    }
    const nodes = layout.nodes;
    const values = view.values || [];
    const rangeText = (node) => (node.l === node.r ? `${node.l}` : `${node.l}..${node.r}`);
    const longest = Math.max(
        3,
        ...nodes.map((node, position) => Math.max((values[position] ?? "…").length, rangeText(node).length)),
        ...(view.base?.values || []).map((value) => (value ?? "").length),
    );
    const nodeWidth = Math.ceil(longest * SEGMENT_NODE.charWidth + 18);
    const columnWidth = nodeWidth + SEGMENT_NODE.gapX;
    const levelHeight = SEGMENT_NODE.height + SEGMENT_NODE.levelGap;
    const pad = SEGMENT_NODE.padding;
    // Room left of the leaves for the original array's name.
    const gutter = view.base ? Math.ceil(view.base.name.length * SEGMENT_NODE.charWidth + 14) : 0;
    const treeHeight = layout.depth * levelHeight - SEGMENT_NODE.levelGap;
    const baseTop = treeHeight + 28;
    const contentWidth = gutter + layout.columns * columnWidth - SEGMENT_NODE.gapX + pad * 2;
    const contentHeight = (view.base ? baseTop + SEGMENT_NODE.baseHeight + 22 : treeHeight) + pad * 2;

    const meta = document.createElement("div");
    meta.className = "algorithm-meta is-sticky";
    const summary = document.createElement("span");
    summary.textContent = `${view.name}, ${nodes.length} nodes over [${layout.low}, ${layout.high}]${layout.truncated ? `, top ${layout.depth} levels` : ""}${view.carried ? ", last known state" : ""}`;
    meta.append(summary, algorithmLegend([
        ["active", "Running now"],
        ["on-stack", "On the call path"],
        ["reading", "Reading"],
        ["written", "Written"],
    ]));
    meta.style.width = `${Math.max(0, algorithmViewArea().width)}px`;
    elements.algorithmView.append(meta);

    const area = algorithmViewArea(meta);
    // Shrink a little to fit, but keep values readable; past 85% the panel scrolls.
    const scale = Math.max(0.85, Math.min(1, area.width / contentWidth, area.height / contentHeight));
    const svg = svgElement("svg", {
        class: "segment-tree-svg",
        viewBox: `0 0 ${contentWidth} ${contentHeight}`,
        width: Math.round(contentWidth * scale),
        height: Math.round(contentHeight * scale),
    });
    const position = (node) => ({x: pad + gutter + node.x * columnWidth, y: pad + node.depth * levelHeight});
    const byId = new Map(nodes.map((node) => [node.id, node]));
    const onPath = new Set(view.path || []);
    const reading = new Set(view.reading || []);
    const written = new Set((view.written || []).map((index) => nodes[index]?.id));
    const childOf = (id) => (layout.root === 0 ? [id * 2 + 1, id * 2 + 2] : [id * 2, id * 2 + 1]);

    nodes.forEach((node) => childOf(node.id).forEach((childId) => {
        const child = byId.get(childId);
        if (!child) return;
        const from = position(node);
        const to = position(child);
        svg.append(svgElement("line", {
            class: `segment-edge${onPath.has(node.id) && onPath.has(childId) ? " on-stack" : ""}`,
            x1: from.x + nodeWidth / 2, y1: from.y + SEGMENT_NODE.height,
            x2: to.x + nodeWidth / 2, y2: to.y,
        }));
    }));

    nodes.forEach((node, index) => {
        const {x, y} = position(node);
        const classes = ["segment-node"];
        if (node.id === view.current) classes.push("current");
        else if (onPath.has(node.id)) classes.push("on-stack");
        if (reading.has(node.id)) classes.push("reading");
        if (written.has(node.id)) classes.push("written");
        const group = svgElement("g", {class: classes.join(" "), transform: `translate(${x} ${y})`});
        group.append(svgElement("rect", {width: nodeWidth, height: SEGMENT_NODE.height, rx: 4}));
        const value = svgElement("text", {class: "segment-value", x: nodeWidth / 2, y: 18});
        value.textContent = values[index] ?? "…";
        const range = svgElement("text", {class: "segment-range", x: nodeWidth / 2, y: 34});
        range.textContent = rangeText(node);
        const title = svgElement("title");
        title.textContent = `${view.name}[${node.id}] = ${values[index] ?? "not read"} · range [${node.l}, ${node.r}]`;
        group.append(value, range, title);
        svg.append(group);
    });

    // The original array, one cell under each leaf.
    if (view.base) {
        const label = svgElement("text", {class: "segment-base-label", x: pad, y: pad + baseTop + 20});
        label.textContent = view.base.name;
        svg.append(label);
        nodes.filter((node) => node.l === node.r).forEach((leaf) => {
            const {x} = position(leaf);
            const cell = svgElement("g", {class: "segment-base", transform: `translate(${x} ${pad + baseTop})`});
            cell.append(svgElement("rect", {width: nodeWidth, height: SEGMENT_NODE.baseHeight, rx: 3}));
            const text = svgElement("text", {class: "segment-value", x: nodeWidth / 2, y: 20});
            text.textContent = view.base.values[leaf.l - layout.low] ?? "";
            cell.append(text);
            svg.append(cell);
        });
    }

    const wrapper = document.createElement("div");
    wrapper.className = "segment-tree";
    wrapper.append(svg);
    elements.algorithmView.append(wrapper);

    // Keep the running node in view when the tree is wider than the panel.
    const running = byId.get(view.current);
    if (running && contentWidth * scale > area.width) {
        elements.algorithmView.scrollLeft = (position(running).x + nodeWidth / 2) * scale - area.width / 2;
    }
}

function renderRecursionTreeAlgorithm(view) {
    const tree = state.result?.algorithm?.recursion_tree;
    const step = view.at_step ?? state.currentStep;
    const nodes = (tree?.nodes || []);
    const occurred = nodes.filter((node) => node.start_step <= step);
    const path = [];
    for (let id = view.current; id !== null && id !== undefined && nodes[id]; id = nodes[id].parent) path.push(nodes[id]);
    // An overview has a drawing budget; the focused view can inspect every captured call.
    const overview = occurred.length > 400;
    const selectedIds = new Set([...occurred.slice(0, 140), ...occurred.slice(-200), ...path.slice(0, 60)].map((node) => node.id));
    const visible = overview ? occurred.filter((node) => selectedIds.has(node.id)) : occurred;
    if (!visible.length) {
        renderAlgorithmWaiting("等待函式呼叫…");
        return;
    }
    if (!tree.layout && !overview) tree.layout = layoutRecursionTree(nodes.slice(0, 400));
    const layout = overview ? layoutRecursionTree(visible) : tree.layout;
    const {nodeWidth, width, height} = layout;
    const nodeHeight = RECURSION_NODE.height;
    const onStack = new Set();
    for (let id = view.current; id !== null && id !== undefined; id = nodes[id].parent) onStack.add(id);

    const meta = document.createElement("div");
    meta.className = "algorithm-meta is-sticky";
    const summary = document.createElement("span");
    summary.textContent = `${occurred.length} of ${nodes.length} calls${overview ? ` · overview draws ${visible.length}; enable Focus to inspect folded branches` : ""}${tree.truncated ? ", trace call budget reached" : ""}`;
    meta.append(summary, algorithmLegend([
        ["active", "Running now"],
        ["on-stack", "Waiting on a call"],
        ["returned", "Returned"],
    ]));
    // Pinned to the visible width, so the legend stays in view while the tree scrolls.
    meta.style.width = `${Math.max(0, algorithmViewArea().width)}px`;
    elements.algorithmView.append(meta);

    // Shrink large trees a little to fit, but keep labels readable; past 85% the panel scrolls.
    // The drawing surface is at least the panel's size, so nodes can be dragged anywhere in it.
    const minimumScale = 0.85;
    const area = algorithmViewArea(meta);
    const pad = RECURSION_NODE.padding;
    const contentWidth = width + pad * 2;
    const contentHeight = height + pad * 2;
    const scale = Math.max(minimumScale, Math.min(1, area.width / contentWidth, area.height / contentHeight));
    const surfaceWidth = Math.max(contentWidth, Math.floor(area.width / scale));
    const surfaceHeight = Math.max(contentHeight, Math.floor(area.height / scale));
    const offset = {x: pad + (surfaceWidth - contentWidth) / 2, y: pad};
    const svg = svgElement("svg", {
        class: "recursion-tree-svg",
        viewBox: `0 0 ${surfaceWidth} ${surfaceHeight}`,
        width: Math.round(surfaceWidth * scale),
        height: Math.round(surfaceHeight * scale),
    });

    // Dragged positions are stored relative to the layout, so they survive panel resizes.
    const positions = new Map();
    visible.forEach((node) => {
        const base = state.recursionPositions.get(node.id) || layout.positions.get(node.id);
        positions.set(node.id, {x: base.x + offset.x, y: base.y + offset.y});
    });

    const visibleIds = new Set(visible.map((node) => node.id));
    const edges = visible
        .filter((node) => visibleIds.has(node.parent))
        .map((node) => {
            const path = svgElement("path", {class: `recursion-edge${onStack.has(node.id) ? " on-stack" : ""}`});
            svg.append(path);
            return {node, path};
        });
    const updateEdges = () => {
        edges.forEach(({node, path}) => {
            const from = positions.get(node.parent);
            const to = positions.get(node.id);
            const startX = from.x + nodeWidth / 2;
            const startY = from.y + nodeHeight;
            const endX = to.x + nodeWidth / 2;
            const middleY = (startY + to.y) / 2;
            path.setAttribute("d", `M ${startX} ${startY} C ${startX} ${middleY}, ${endX} ${middleY}, ${endX} ${to.y}`);
        });
    };

    const maxChars = Math.floor((nodeWidth - 16) / RECURSION_NODE.charWidth);
    const nodeElements = new Map();
    visible.forEach((node) => {
        const position = positions.get(node.id);
        const returned = node.end_step !== null && node.end_step < step;
        const classes = ["recursion-node"];
        if (node.id === view.current) classes.push("current");
        else if (onStack.has(node.id)) classes.push("on-stack");
        else if (returned) classes.push("returned");
        const group = svgElement("g", {class: classes.join(" "), transform: `translate(${position.x} ${position.y})`});
        group.append(svgElement("rect", {width: nodeWidth, height: nodeHeight, rx: 4}));
        const label = svgElement("text", {class: "recursion-label", x: 10, y: node.return_value !== null && returned ? 18 : 27});
        if (node.order) {
            const order = svgElement("tspan", {class: "recursion-order"});
            order.textContent = `#${node.order} `;
            label.append(order);
        }
        label.append(truncate(node.label, maxChars - (node.order ? String(node.order).length + 2 : 0)));
        group.append(label);
        if (returned && node.return_value !== null) {
            const result = svgElement("text", {class: "recursion-return", x: 10, y: 36});
            result.textContent = truncate(`→ ${node.return_value}`, maxChars);
            group.append(result);
        }
        const title = svgElement("title");
        title.textContent = node.order ? `Call #${node.order}: ${node.title || node.label}` : (node.title || node.label);
        group.append(title);
        svg.append(group);
        nodeElements.set(node.id, group);
    });
    updateEdges();
    enableSvgNodeDragging({
        svg,
        nodeElements,
        positions,
        updateEdges,
        positionStore: {
            set(nodeId, position) {
                state.recursionPositions.set(nodeId, {x: position.x - offset.x, y: position.y - offset.y});
            },
        },
        nodeWidth,
        nodeHeight,
        centered: false,
    });

    const wrapper = document.createElement("div");
    wrapper.className = "recursion-tree";
    wrapper.append(svg);
    elements.algorithmView.append(wrapper);

    // Keep the running call in view when the tree is larger than the panel.
    const current = positions.get(view.current);
    if (current && scale === minimumScale) {
        elements.algorithmView.scrollLeft = current.x * scale - area.width / 2;
        elements.algorithmView.scrollTop = current.y * scale - area.height / 2;
    }
}

const CALL_CHAIN_NODE = {height: 44, gapX: 44, gapY: 36, padding: 16, charWidth: 8.4};

function renderCallTreeAlgorithm(view) {
    const frames = view.frames || [];
    if (!frames.length) {
        renderAlgorithmWaiting("等待函式呼叫…");
        return;
    }
    // Boxes are keyed by stack depth, so a box keeps its dragged place while that frame lives.
    const hidden = view.hidden || 0;
    const items = frames.map((frame, index) => ({
        key: `depth-${index === 0 ? 0 : index + hidden}`,
        label: `${frame.function}() · line ${frame.line}`,
        current: index === frames.length - 1,
    }));
    if (hidden) items.splice(1, 0, {key: "hidden", label: `… ${hidden} more calls`, current: false, hidden: true});

    const area = algorithmViewArea();
    const pad = CALL_CHAIN_NODE.padding;
    const longest = Math.max(...items.map((item) => item.label.length));
    const nodeWidth = Math.max(150, Math.round(longest * CALL_CHAIN_NODE.charWidth + 28));
    const nodeHeight = CALL_CHAIN_NODE.height;
    const perRow = Math.max(1, Math.floor((area.width - pad * 2 + CALL_CHAIN_NODE.gapX) / (nodeWidth + CALL_CHAIN_NODE.gapX)));
    const rows = Math.ceil(items.length / perRow);
    const contentWidth = (rows > 1 ? perRow : items.length) * (nodeWidth + CALL_CHAIN_NODE.gapX) - CALL_CHAIN_NODE.gapX;
    const contentHeight = rows * (nodeHeight + CALL_CHAIN_NODE.gapY) - CALL_CHAIN_NODE.gapY;
    const width = Math.max(Math.floor(area.width), contentWidth + pad * 2);
    const height = Math.max(Math.floor(area.height), contentHeight + pad * 2);
    const origin = {x: (width - contentWidth) / 2, y: Math.max(pad, (height - contentHeight) / 2)};

    // Rows run left-to-right, then right-to-left, so each arrow joins neighbours and a new row
    // starts directly below the end of the previous one.
    const positions = new Map();
    items.forEach((item, index) => {
        const saved = state.callChainPositions.get(item.key);
        const row = Math.floor(index / perRow);
        const column = row % 2 === 0 ? index % perRow : perRow - 1 - (index % perRow);
        const x = origin.x + column * (nodeWidth + CALL_CHAIN_NODE.gapX);
        const y = origin.y + Math.floor(index / perRow) * (nodeHeight + CALL_CHAIN_NODE.gapY);
        positions.set(item.key, saved
            ? {x: Math.min(Math.max(4, saved.x), width - nodeWidth - 4), y: Math.min(Math.max(4, saved.y), height - nodeHeight - 4)}
            : {x, y});
    });

    const svg = svgElement("svg", {class: "call-chain-svg", viewBox: `0 0 ${width} ${height}`, width, height});
    const defs = svgElement("defs");
    const marker = svgElement("marker", {id: "call-chain-arrow", viewBox: "0 0 10 10", refX: "9", refY: "5", markerWidth: "7", markerHeight: "7", orient: "auto-start-reverse"});
    marker.append(svgElement("path", {class: "call-chain-arrow-head", d: "M 0 0 L 10 5 L 0 10 z"}));
    defs.append(marker);
    svg.append(defs);

    const links = items.slice(1).map((item, index) => {
        const path = svgElement("path", {class: "call-chain-edge", "marker-end": "url(#call-chain-arrow)"});
        svg.append(path);
        return {from: items[index].key, to: item.key, path};
    });
    // Arrows leave the side of a box that faces the next one, so they stay readable after dragging.
    const updateEdges = () => {
        links.forEach(({from, to, path}) => {
            const a = positions.get(from);
            const b = positions.get(to);
            const ax = a.x + nodeWidth / 2;
            const ay = a.y + nodeHeight / 2;
            const bx = b.x + nodeWidth / 2;
            const by = b.y + nodeHeight / 2;
            let start;
            let end;
            if (Math.abs(bx - ax) * nodeHeight >= Math.abs(by - ay) * nodeWidth) {
                const direction = Math.sign(bx - ax) || 1;
                start = {x: ax + direction * nodeWidth / 2, y: ay};
                end = {x: bx - direction * nodeWidth / 2, y: by};
                const bend = Math.max(20, Math.abs(end.x - start.x) / 2) * direction;
                path.setAttribute("d", `M ${start.x} ${start.y} C ${start.x + bend} ${start.y}, ${end.x - bend} ${end.y}, ${end.x} ${end.y}`);
            } else {
                const direction = Math.sign(by - ay) || 1;
                start = {x: ax, y: ay + direction * nodeHeight / 2};
                end = {x: bx, y: by - direction * nodeHeight / 2};
                const bend = Math.max(16, Math.abs(end.y - start.y) / 2) * direction;
                path.setAttribute("d", `M ${start.x} ${start.y} C ${start.x} ${start.y + bend}, ${end.x} ${end.y - bend}, ${end.x} ${end.y}`);
            }
        });
    };

    const nodeElements = new Map();
    items.forEach((item) => {
        const position = positions.get(item.key);
        const classes = ["call-chain-node"];
        if (item.current) classes.push("current");
        if (item.hidden) classes.push("hidden-frames");
        const group = svgElement("g", {class: classes.join(" "), transform: `translate(${position.x} ${position.y})`});
        group.append(svgElement("rect", {width: nodeWidth, height: nodeHeight, rx: 4}));
        const label = svgElement("text", {x: nodeWidth / 2, y: nodeHeight / 2});
        label.textContent = item.label;
        group.append(label);
        svg.append(group);
        nodeElements.set(item.key, group);
    });
    updateEdges();
    enableSvgNodeDragging({
        svg,
        nodeElements,
        positions,
        updateEdges,
        positionStore: state.callChainPositions,
        nodeWidth,
        nodeHeight,
        centered: false,
    });
    elements.algorithmView.append(svg);
}

function renderExecutionAlgorithm(view) {
    const wrapper = document.createElement("div");
    wrapper.className = "execution-visualizer";
    const orbit = document.createElement("div");
    orbit.className = "execution-orbit";
    orbit.textContent = `${view.function || "<module>"}()\nline ${view.line ?? "—"}\n${view.event || "execution"}`;
    orbit.style.whiteSpace = "pre-line";
    wrapper.append(orbit);
    elements.algorithmView.append(wrapper);
}
