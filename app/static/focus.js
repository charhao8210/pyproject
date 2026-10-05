/* Focused views use recorded trace states; no algorithm outcome is inferred from a return. */
"use strict";

(() => {
    const treeCache = new WeakMap();
    const scaleCache = new WeakMap();
    const pageCache = new WeakMap();
    const PAGE_SIZE = 24;
    const MAX_EXPANDED_CALLS = 96;
    const node = (tag, className = "", text = null) => {
        const item = document.createElement(tag);
        item.className = className;
        if (text !== null && text !== undefined) item.textContent = String(text);
        return item;
    };
    const own = (value, key) => value != null && Object.prototype.hasOwnProperty.call(value, key);
    const focused = (ctx) => ctx.focus !== false;
    const exact = (value) => {
        if (value === null) return "None";
        if (value === undefined) return "未擷取";
        if (typeof value === "object") {
            if (own(value, "value")) return String(value.value);
            if (value.type === "none") return "None";
            if (value.items) return `[${value.items.map(exact).join(", ")}]`;
            try { return JSON.stringify(value); } catch { return "…"; }
        }
        if (value === "\0") return "未設定";
        return String(value);
    };
    const clip = (text, size = 180) => {
        text = String(text ?? "");
        return text.length > size ? `${text.slice(0, size - 1)}…` : text;
    };
    function jump(ctx, index) {
        if (Number.isInteger(index) && typeof ctx.goToStep === "function") ctx.goToStep(index);
    }
    function upperBound(items, step, key = "start_step") {
        let low = 0;
        let high = items.length;
        while (low < high) {
            const middle = (low + high) >>> 1;
            if ((items[middle][key] ?? Infinity) <= step) low = middle + 1;
            else high = middle;
        }
        return low;
    }
    function treeIndex(tree) {
        if (treeCache.has(tree)) return treeCache.get(tree);
        const nodes = tree.nodes || [];
        const byId = new Map(nodes.map((call) => [call.id, call]));
        const children = new Map();
        const roots = [];
        const sizes = new Map(nodes.map((call) => [call.id, 1]));
        for (const call of nodes) {
            if (!byId.has(call.parent)) roots.push(call);
            else {
                if (!children.has(call.parent)) children.set(call.parent, []);
                children.get(call.parent).push(call);
            }
        }
        // Parents precede children in trace call order; this remains iterative for deep DFS.
        for (let index = nodes.length - 1; index >= 0; index--) {
            const call = nodes[index];
            if (byId.has(call.parent)) sizes.set(call.parent, sizes.get(call.parent) + sizes.get(call.id));
        }
        const cache = {nodes, byId, children, roots, sizes, expanded: new Map()};
        treeCache.set(tree, cache);
        return cache;
    }
    function callCard(call, ctx, step, current = false, depth = 0) {
        const returned = call.end_step !== null && call.end_step !== undefined && call.end_step < step;
        const card = node("article", `focus-call${current ? " is-current" : returned ? " is-returned" : " is-on-path"}`);
        card.dataset.callId = String(call.id);
        card.style.setProperty("--focus-depth", Math.min(depth, 7));
        const heading = node("div", "focus-call-heading");
        const label = node("button", "focus-call-title", call.title || call.label || `${call.function || "?"}()`);
        label.type = "button";
        label.title = `Go to call entry at step ${call.start_step + 1}`;
        label.addEventListener("click", () => jump(ctx, call.start_step));
        const status = node("span", "focus-call-status", current ? "Running now" : returned ? "Returned" : "On call path");
        heading.append(label, status);
        const detail = node("div", "focus-call-detail");
        const callNumber = call.order == null ? "Root" : `Call #${call.order}`;
        detail.append(node("span", "", `${callNumber} · entry ${call.start_step + 1}`));
        if (returned && call.return_value !== null && call.return_value !== undefined) {
            const result = node("span", "focus-call-return", `→ ${exact(call.return_value)}`);
            result.title = exact(call.return_value);
            detail.append(result);
        }
        if (call.end_step !== null && call.end_step !== undefined) {
            const end = node("button", "focus-call-end", `Last step ${call.end_step + 1}`);
            end.type = "button";
            end.title = "Go to the last recorded step of this call";
            end.addEventListener("click", () => jump(ctx, call.end_step));
            detail.append(end);
        }
        card.append(heading, detail);
        return card;
    }
    function completedSummary(calls, cache, ctx, step, depth, key) {
        if (!calls.length) return null;
        const count = calls.reduce((sum, call) => sum + (cache.sizes.get(call.id) || 1), 0);
        const wrapper = node("div", "focus-call-summary");
        wrapper.style.setProperty("--focus-depth", Math.min(depth, 7));
        const button = node("button", "focus-summary-toggle");
        button.type = "button";
        const page = cache.expanded.get(key);
        const open = page !== undefined;
        button.setAttribute("aria-expanded", String(open));
        button.textContent = `${open ? "▾" : "▸"} ${calls.length} completed ${calls.length === 1 ? "branch" : "branches"} · ${count} ${count === 1 ? "call" : "calls"}`;
        button.title = "Completed branches are folded; expand to inspect their recorded calls";
        button.addEventListener("click", () => {
            if (cache.expanded.has(key)) cache.expanded.delete(key);
            else cache.expanded.set(key, 0);
            renderRecursion(ctx.view, {...ctx, _expandedAncestors: undefined, _callBudget: undefined});
        });
        wrapper.append(button);
        if (!open) return wrapper;
        const offset = Math.min(page * PAGE_SIZE, Math.max(0, calls.length - 1));
        const contents = node("div", "focus-completed-calls");
        const selected = calls.slice(offset, offset + PAGE_SIZE);
        let drawn = 0;
        for (const call of selected) {
            if (ctx._callBudget.remaining <= 0) {
                contents.append(node("span", "focus-slice-note", "Expansion limit reached for this view; fold another branch or select a call entry to inspect it."));
                break;
            }
            ctx._callBudget.remaining--;
            contents.append(callCard(call, ctx, step, false, depth));
            drawn++;
            const childCalls = (cache.children.get(call.id) || []).filter((child) => child.end_step != null && child.end_step < step);
            if (childCalls.length) {
                // Each branch has its own disclosure; one open subtree cannot grow the canvas unboundedly.
                const nestedKey = `subtree:${call.id}`;
                if (drawn < MAX_EXPANDED_CALLS && !ctx._expandedAncestors?.has(call.id)) {
                    const ancestors = new Set(ctx._expandedAncestors || []);
                    ancestors.add(call.id);
                    if (ancestors.size < 8) contents.append(completedSummary(childCalls, cache, {...ctx, _expandedAncestors: ancestors}, step, depth + 1, nestedKey));
                    else contents.append(node("span", "focus-slice-note", `${cache.sizes.get(call.id) - 1} deeper calls · use call entry to inspect the path`));
                }
            }
        }
        if (calls.length > PAGE_SIZE) {
            const paging = node("div", "focus-call-paging");
            const previous = node("button", "focus-small-button", "Previous calls");
            const next = node("button", "focus-small-button", "Next calls");
            previous.type = next.type = "button";
            previous.disabled = offset === 0;
            next.disabled = offset + PAGE_SIZE >= calls.length;
            previous.addEventListener("click", () => { cache.expanded.set(key, Math.max(0, page - 1)); renderRecursion(ctx.view, {...ctx, _expandedAncestors: undefined, _callBudget: undefined}); });
            next.addEventListener("click", () => { cache.expanded.set(key, page + 1); renderRecursion(ctx.view, {...ctx, _expandedAncestors: undefined, _callBudget: undefined}); });
            paging.append(previous, node("span", "", `${offset + 1}–${Math.min(calls.length, offset + PAGE_SIZE)} of ${calls.length} branches`), next);
            contents.append(paging);
        }
        wrapper.append(contents);
        return wrapper;
    }
    function hiddenPathSummary(calls, cache, ctx, step) {
        const key = "hidden-path";
        const page = cache.expanded.get(key);
        const wrapper = node("div", "focus-call-summary");
        const toggle = node("button", "focus-summary-toggle", `${page === undefined ? "▸" : "▾"} ${calls.length} calls on this path folded`);
        toggle.type = "button";
        toggle.setAttribute("aria-expanded", String(page !== undefined));
        toggle.addEventListener("click", () => {
            if (page === undefined) cache.expanded.set(key, 0);
            else cache.expanded.delete(key);
            renderRecursion(ctx.view, ctx);
        });
        wrapper.append(toggle);
        if (page !== undefined) {
            const offset = Math.min(Math.max(0, calls.length - 1), page * PAGE_SIZE);
            const contents = node("div", "focus-completed-calls");
            for (const call of calls.slice(offset, offset + PAGE_SIZE)) contents.append(callCard(call, ctx, step));
            const previous = node("button", "focus-small-button", "Previous depth");
            const next = node("button", "focus-small-button", "Next depth");
            previous.type = next.type = "button";
            previous.disabled = offset === 0;
            next.disabled = offset + PAGE_SIZE >= calls.length;
            previous.addEventListener("click", () => { cache.expanded.set(key, Math.max(0, page - 1)); renderRecursion(ctx.view, ctx); });
            next.addEventListener("click", () => { cache.expanded.set(key, page + 1); renderRecursion(ctx.view, ctx); });
            const paging = node("div", "focus-call-paging");
            paging.append(previous, node("span", "", `Folded path ${offset + 1}–${Math.min(calls.length, offset + PAGE_SIZE)} of ${calls.length}`), next);
            contents.append(paging);
            wrapper.append(contents);
        }
        return wrapper;
    }
    function renderRecursion(view, context) {
        const ctx = {...context, view, _callBudget: {remaining: MAX_EXPANDED_CALLS}};
        const tree = ctx.result?.algorithm?.recursion_tree;
        if (!tree || !ctx.target) return false;
        const cache = treeIndex(tree);
        const at = view.at_step ?? ctx.index ?? 0;
        const visibleCount = upperBound(cache.nodes, at);
        ctx.target.replaceChildren();
        ctx.target.classList.add("has-focused-recursion");
        if (!visibleCount) {
            ctx.target.append(node("div", "algorithm-waiting", "Waiting for the first recorded function call…"));
            return true;
        }
        const current = cache.byId.get(view.current);
        let running = current;
        // A finished trace can have an empty stack; the last call's ancestors still provide orientation.
        if (!running || running.start_step > at) running = cache.nodes[visibleCount - 1];
        const path = [];
        const pathIds = new Set();
        while (running && !pathIds.has(running.id)) {
            path.push(running);
            pathIds.add(running.id);
            running = cache.byId.get(running.parent);
        }
        path.reverse();
        const meta = node("div", "algorithm-meta focus-recursion-meta");
        const text = node("div", "focus-meta-title", `${visibleCount.toLocaleString()} recorded calls · path depth ${Math.max(0, path.length - 1)}`);
        const note = node("span", "focus-slice-note", "Completed branches are folded. Select a call to inspect its entry or last step.");
        meta.append(text, note);
        if (tree.truncated) meta.append(node("span", "beyond-note", "Call capture limit reached; later calls are unavailable."));
        ctx.target.append(meta);
        const chain = node("div", "focus-call-path");
        chain.setAttribute("aria-label", "Root to current call path");
        for (let index = 0; index < path.length; index++) {
            if (path.length > 40 && index === 20) {
                chain.append(hiddenPathSummary(path.slice(20, path.length - 20), cache, ctx, at));
                index = path.length - 20;
            }
            const call = path[index];
            chain.append(callCard(call, ctx, at, call.id === current?.id, index));
            const children = cache.children.get(call.id) || [];
            const shownCount = upperBound(children, at);
            const complete = children.slice(0, shownCount).filter((child) => !pathIds.has(child.id) && child.end_step != null && child.end_step < at);
            const summary = completedSummary(complete, cache, ctx, at, index + 1, `siblings:${call.id}`);
            if (summary) chain.append(summary);
        }
        const otherRoots = cache.roots.filter((call) => !pathIds.has(call.id) && call.start_step <= at && call.end_step != null && call.end_step < at);
        if (otherRoots.length) chain.append(completedSummary(otherRoots, cache, ctx, at, 0, "roots"));
        ctx.target.append(chain);
        appendOperation(view, ctx);
        if (ctx.follow !== false) {
            const active = chain.querySelector(".is-current");
            if (active) followWithin(ctx.target, active);
        }
        return true;
    }
    function followWithin(target, item) {
        // Scroll the visualization pane only; a debugger step must never scroll the whole page.
        const targetBox = target.getBoundingClientRect();
        const itemBox = item.getBoundingClientRect();
        const pinned = target.querySelector(".focus-operation");
        const reserved = pinned ? pinned.getBoundingClientRect().height + 8 : 12;
        const availableHeight = Math.max(itemBox.height, target.clientHeight - reserved - 12);
        if (itemBox.top < targetBox.top + reserved || itemBox.bottom > targetBox.bottom - 12) {
            target.scrollTop += itemBox.top - targetBox.top - reserved - Math.max(0, (availableHeight - itemBox.height) / 2);
        }
        if (itemBox.left < targetBox.left + 12 || itemBox.right > targetBox.right - 12) {
            target.scrollLeft += itemBox.left - targetBox.left - Math.max(12, (target.clientWidth - itemBox.width) / 2);
        }
    }
    function entriesFor(view, ctx, kind) {
        const operation = view.operation || {};
        const recorded = Array.isArray(operation[kind]) ? operation[kind] : [];
        const named = ctx.step?.usage?.[kind]?.[view.name];
        const entries = [...recorded];
        if (named && !entries.length) {
            for (const cell of named.cells || []) entries.push({name: view.name, cell});
            for (const index of named.items || []) entries.push({name: view.name, index});
        }
        return entries;
    }
    function coordinate(entry) {
        if (Array.isArray(entry?.cell) && entry.cell.length >= 2) return entry.cell;
        if (Number.isInteger(entry?.row) && Number.isInteger(entry?.column)) return [entry.row, entry.column];
        if (Array.isArray(entry) && entry.length >= 2) return entry;
        return null;
    }
    function entryName(entry, fallback) {
        const base = entry.name || fallback || "value";
        const cell = coordinate(entry);
        if (cell) return `${base}[${cell[0]}][${cell[1]}]`;
        if (entry.index !== undefined) return `${base}[${entry.index}]`;
        if (entry.vertex !== undefined) return `${base}[${entry.vertex}]`;
        return base;
    }
    function operationWrites(view, ctx) {
        const writes = entriesFor(view, ctx, "writes");
        if (writes.length) return writes;
        if (view.renderer === "grid") return (view.written || []).map((cell) => ({name: view.name, cell: [cell.row, cell.column], after: view.rows_text?.[cell.row]?.[cell.column] ?? view.rows?.[cell.row]?.[cell.column]}));
        if (["array", "cells"].includes(view.renderer)) return (view.written || []).map((index) => ({name: view.name, index, after: view.values_text?.[index] ?? view.values?.[index]}));
        return [];
    }
    function appendOperation(view, ctx) {
        const operation = view.operation;
        const reads = entriesFor(view, ctx, "reads");
        const writes = operationWrites(view, ctx);
        const relevant = (key) => key === view.name || key.startsWith(`${view.name}[`);
        const formula = operation?.formula || Object.fromEntries(Object.entries(ctx.step?.usage?.formula || {}).filter(([key]) => relevant(key)));
        const formulas = typeof formula === "string" ? [["", formula]] : formula?.expression ? [[view.name || "", formula]] : Object.entries(formula || {});
        if (operation?.expression) formulas.unshift([writes.length === 1 ? entryName(writes[0], view.name) : view.name || "", {expression: operation.expression, substituted: operation.substituted}]);
        if (!operation?.label && !reads.length && !writes.length && !formulas.length && view.renderer !== "grid") return;
        const panel = node("details", "focus-operation debugger-focus-decoration");
        const targetStyle = getComputedStyle(ctx.target);
        panel.style.width = `${Math.max(100, ctx.target.clientWidth - parseFloat(targetStyle.paddingLeft || 0) - parseFloat(targetStyle.paddingRight || 0))}px`;
        panel.style.setProperty("--focus-detail-height", `${Math.max(80, Math.min(240, ctx.target.clientHeight - 70))}px`);
        const summary = node("summary", "focus-operation-summary");
        let primary = operation?.label || (view.renderer === "grid" ? `${view.name || "表格"} · 已擷取狀態` : "目前操作");
        if (writes.length) {
            const entry = writes[0];
            const suffix = own(entry, "before") && own(entry, "after") ? `${exact(entry.before)} → ${exact(entry.after)}` : own(entry, "after") ? exact(entry.after) : "已變更，值未擷取";
            primary = `${entryName(entry, view.name)}：${suffix}${writes.length > 1 ? ` · 另 ${writes.length - 1} 項變更` : ""}`;
        } else if (reads.length) {
            const entry = reads[0];
            primary = `讀取 ${entryName(entry, view.name)}${own(entry, "value") ? ` = ${exact(entry.value)}` : " · 值未擷取"}${reads.length > 1 ? ` · 另 ${reads.length - 1} 項` : ""}`;
        }
        const primaryText = node("span", "focus-operation-primary", clip(primary, 180));
        primaryText.title = `${primary} · 展開查看讀寫與公式`;
        summary.append(primaryText);
        const range = node("span", "focus-operation-range");
        range.hidden = true;
        const body = node("div", "focus-operation-body");
        const label = operation?.label || (writes.length ? "變更" : reads.length ? "讀取" : "已擷取狀態");
        body.append(node("strong", "focus-operation-title", label), range);
        if (operation?.evidence === "snapshot") body.append(node("span", "focus-slice-note", "依擷取狀態比較"));
        const chips = node("div", "focus-operation-chips");
        for (const entry of writes.slice(0, 80)) {
            const suffix = own(entry, "before") && own(entry, "after") ? `${exact(entry.before)} → ${exact(entry.after)}` : own(entry, "after") ? exact(entry.after) : "已變更，值未擷取";
            const chip = node("span", "focus-write-chip", `${entryName(entry, view.name)}：${suffix}`);
            chip.title = `${entryName(entry, view.name)}：${suffix}`;
            chips.append(chip);
        }
        if (writes.length > 80) chips.append(node("span", "focus-slice-note", `另 ${writes.length - 80} 項變更`));
        for (const entry of reads.slice(0, 80)) {
            const suffix = own(entry, "value") ? ` = ${exact(entry.value)}` : " · 值未擷取";
            chips.append(node("span", "focus-read-chip", `${entryName(entry, view.name)}${suffix}`));
        }
        if (reads.length > 80) chips.append(node("span", "focus-slice-note", `另 ${reads.length - 80} 項讀取`));
        if (chips.childElementCount) body.append(chips);
        for (const [name, value] of formulas.slice(0, 6)) {
            const expression = typeof value === "string" ? value : value?.expression;
            if (!expression) continue;
            const substituted = value?.substituted;
            const text = `${name ? `${name} ← ` : ""}${expression}${substituted && substituted !== expression ? ` = ${substituted}` : ""}`;
            const line = node("code", "focus-formula", text);
            line.title = text;
            body.append(line);
        }
        if (operation?.candidate && own(operation.candidate, "value")) {
            const text = `候選值：${operation.candidate.expression || operation.expression || "value"} = ${exact(operation.candidate.value)}`;
            const candidate = node("code", "focus-formula focus-candidate", text);
            candidate.title = text;
            body.append(candidate);
        }
        if (operation?.source) {
            const source = node("details", "focus-operation-source");
            source.append(node("summary", "", `程式碼${ctx.step?.line ? ` · 第 ${ctx.step.line} 行` : ""}`), node("code", "", operation.source));
            body.append(source);
        }
        panel.append(summary, body);
        const meta = ctx.target.querySelector(".algorithm-meta");
        if (meta) meta.insertAdjacentElement("afterend", panel);
        else ctx.target.prepend(panel);
    }
    function decorateGrid(view, ctx) {
        const grid = ctx.target.querySelector(".algorithm-grid");
        if (!grid) return;
        ctx.target.querySelectorAll(".focus-grid-navigation, .focus-grid-slice, .focus-reading-key").forEach((item) => item.remove());
        const originalRows = view.rows || [];
        const rows = focused(ctx) ? view.captured_rows || originalRows : originalRows;
        const width = Math.max(0, ...rows.map((row) => row.length));
        if (!rows.length || !width) return;
        const reading = new Set(entriesFor(view, ctx, "reads").filter((entry) => !entry.name || entry.name === view.name).map(coordinate).filter(Boolean).map((cell) => cell.join(":")));
        const writing = new Set(operationWrites(view, ctx).filter((entry) => !entry.name || entry.name === view.name).map(coordinate).filter(Boolean).map((cell) => cell.join(":")));
        const active = new Map((view.active || []).map((entry) => [coordinate(entry)?.join(":"), entry.role]));
        const frontier = new Set((view.frontier || []).map(coordinate).filter(Boolean).map((cell) => cell.join(":")));
        const walls = new Set((view.walls || []).map(coordinate).filter(Boolean).map((cell) => cell.join(":")));
        const anchors = [...writing].map((key) => key.split(":").map(Number));
        if (!anchors.length && view.current_cell) {
            const current = coordinate(view.current_cell);
            if (current) anchors.push(current);
        }
        if (!anchors.length) anchors.push(...(view.active || []).filter((entry) => entry.role === "active" || entry.role === "current").map(coordinate).filter(Boolean));
        if (!anchors.length) anchors.push(...[...reading].map((key) => key.split(":").map(Number)));
        if (!anchors.length) anchors.push(...(view.active || []).map(coordinate).filter(Boolean));
        const rowOffset = view.row_offset ?? view.origin?.row ?? 0;
        const columnOffset = view.column_offset ?? view.origin?.column ?? 0;
        let rowStart = 0;
        let rowEnd = rows.length;
        let columnStart = 0;
        let columnEnd = width;
        let sliceState = null;
        if (focused(ctx) && (rows.length > 14 || width > 18)) {
            if (ctx.result && typeof ctx.result === "object") {
                if (!pageCache.has(ctx.result)) pageCache.set(ctx.result, new Map());
                const cache = pageCache.get(ctx.result);
                const key = `grid:${view.name || ""}`;
                if (!cache.has(key)) cache.set(key, {row: 0, column: 0, step: null});
                sliceState = cache.get(key);
            } else sliceState = {row: 0, column: 0, step: null};
            if (sliceState.step === null || (sliceState.step !== ctx.index && ctx.follow !== false)) {
                const anchor = anchors[0] || [rowOffset, columnOffset];
                sliceState.row = anchor[0] - rowOffset - 6;
                sliceState.column = anchor[1] - columnOffset - 8;
            }
            sliceState.step = ctx.index;
            sliceState.row = Math.max(0, Math.min(Math.max(0, rows.length - 14), sliceState.row));
            sliceState.column = Math.max(0, Math.min(Math.max(0, width - 18), sliceState.column));
            rowStart = sliceState.row;
            columnStart = sliceState.column;
            rowEnd = Math.min(rows.length, rowStart + 14);
            columnEnd = Math.min(width, columnStart + 18);
        }
        const oldCells = [...grid.querySelectorAll(".algorithm-cell")];
        const cells = new Map();
        let index = 0;
        if (oldCells[0]?.dataset.column !== undefined) {
            for (const cell of oldCells) cells.set(`${Number(cell.dataset.row) - rowOffset}:${Number(cell.dataset.column) - columnOffset}`, cell);
        } else {
            for (let row = 0; row < originalRows.length; row++) {
                for (let column = 0; column < originalRows[row].length; column++) cells.set(`${row}:${column}`, oldCells[index++]);
            }
        }
        grid.replaceChildren();
        grid.classList.add("focus-grid");
        grid.setAttribute("role", "grid");
        grid.setAttribute("aria-label", `${view.name || "Grid"}, absolute row and column indexes`);
        grid.setAttribute("aria-rowcount", String(rows.length));
        grid.setAttribute("aria-colcount", String(width));
        const shownColumns = columnEnd - columnStart;
        const contextRange = ctx.target.querySelector(".focus-operation-range");
        if (contextRange) {
            contextRange.hidden = false;
            contextRange.textContent = `列 ${rowStart + rowOffset}–${rowEnd - 1 + rowOffset} · 欄 ${columnStart + columnOffset}–${columnEnd - 1 + columnOffset}${anchors[0] ? ` · 目前 (${anchors[0].join(", ")})` : ""}`;
            contextRange.title = contextRange.textContent;
        }
        const availableWidth = Math.max(250, ctx.target.clientWidth - 74);
        const size = Math.max(32, Math.min(64, Math.floor((availableWidth - shownColumns * 3) / shownColumns)));
        grid.style.setProperty("--cell", `${size}px`);
        const texts = rows.slice(rowStart, rowEnd).flatMap((row, position) => row.slice(columnStart, columnEnd).map((value, column) => exact(view.rows_text?.[position + rowStart]?.[column + columnStart] ?? value)));
        const longest = Math.max(1, ...texts.map((text) => text.length));
        grid.style.setProperty("--cell-font", `${Math.max(9, Math.min(size * .32, (size - 6) / (longest * .62)))}px`);
        grid.style.gridTemplateColumns = `32px repeat(${shownColumns}, ${size}px)`;
        grid.append(node("span", "focus-grid-axis focus-grid-corner", "r / c"));
        for (let column = columnStart; column < columnEnd; column++) {
            const axis = node("span", "focus-grid-axis", column + columnOffset);
            axis.setAttribute("role", "columnheader");
            grid.append(axis);
        }
        for (let row = rowStart; row < rowEnd; row++) {
            const axis = node("span", "focus-grid-axis", row + rowOffset);
            axis.setAttribute("role", "rowheader");
            grid.append(axis);
            for (let column = columnStart; column < columnEnd; column++) {
                const key = `${row}:${column}`;
                const absolute = `${row + rowOffset}:${column + columnOffset}`;
                const cell = cells.get(key) || node("div", "algorithm-cell", column < rows[row].length ? exact(view.captured_rows_text?.[row]?.[column] ?? view.rows_text?.[row]?.[column] ?? rows[row][column]) : "—");
                if (!cell.title && column < rows[row].length) cell.title = `row ${row + rowOffset}, column ${column + columnOffset}: ${exact(view.captured_rows_text?.[row]?.[column] ?? view.rows_text?.[row]?.[column] ?? rows[row][column])}`;
                cell.dataset.row = String(row + rowOffset);
                cell.dataset.column = String(column + columnOffset);
                cell.setAttribute("role", "gridcell");
                cell.setAttribute("aria-rowindex", String(row + rowOffset + 1));
                cell.setAttribute("aria-colindex", String(column + columnOffset + 1));
                cell.classList.toggle("focus-reading", reading.has(absolute));
                cell.classList.toggle("written", writing.has(absolute) || cell.classList.contains("written"));
                if (active.get(absolute)) cell.classList.add(active.get(absolute));
                if (coordinate(view.current_cell)?.join(":") === absolute) cell.classList.add("active");
                if (frontier.has(absolute)) cell.classList.add("frontier");
                if (walls.has(absolute) || rows[row][column] === "#") cell.classList.add("wall");
                if (view.visited?.[row]?.[column]) cell.classList.add("visited");
                cell.setAttribute("aria-label", cell.title || `${view.name}[${row + rowOffset}][${column + columnOffset}] = ${cell.textContent}`);
                grid.append(cell);
            }
        }
        if (rowStart || columnStart || rowEnd < rows.length || columnEnd < width) {
            const hiddenReads = [...reading].filter((key) => {
                const [row, column] = key.split(":").map(Number);
                return row < rowStart + rowOffset || row >= rowEnd + rowOffset || column < columnStart + columnOffset || column >= columnEnd + columnOffset;
            }).length;
            const note = node("div", "focus-slice-note focus-grid-slice debugger-focus-decoration", `列 ${rowStart + rowOffset}–${rowEnd - 1 + rowOffset} · 欄 ${columnStart + columnOffset}–${columnEnd - 1 + columnOffset} / ${rows.length} × ${width}${hiddenReads ? ` · 另 ${hiddenReads} 項讀取在範圍外` : ""}`);
            grid.insertAdjacentElement("beforebegin", note);
            if (sliceState) {
                const paging = node("div", "focus-grid-navigation debugger-focus-decoration");
                for (const [label, field, delta, unavailable] of [["上一組列", "row", -14, rowStart === 0], ["下一組列", "row", 14, rowEnd >= rows.length], ["上一組欄", "column", -18, columnStart === 0], ["下一組欄", "column", 18, columnEnd >= width]]) {
                    const button = node("button", "focus-small-button", label);
                    button.type = "button";
                    button.disabled = unavailable;
                    button.addEventListener("click", () => { sliceState[field] += delta; decorateGrid(view, ctx); });
                    paging.append(button);
                }
                grid.insertAdjacentElement("afterend", paging);
            }
        }
        if (anchors.length && (anchors[0][0] < rowOffset || anchors[0][1] < columnOffset || anchors[0][0] >= rowOffset + rows.length || anchors[0][1] >= columnOffset + width)) {
            grid.insertAdjacentElement("beforebegin", node("div", "beyond-note focus-grid-slice debugger-focus-decoration", `座標 (${anchors[0].join(", ")}) 未擷取`));
        } else if (anchors.length && (anchors[0][0] < rowStart + rowOffset || anchors[0][1] < columnStart + columnOffset || anchors[0][0] >= rowEnd + rowOffset || anchors[0][1] >= columnEnd + columnOffset)) {
            grid.insertAdjacentElement("beforebegin", node("div", "focus-slice-note focus-grid-slice debugger-focus-decoration", `座標 (${anchors[0].join(", ")}) 在範圍外 · 開啟跟隨可定位`));
        }
        if (focused(ctx) && view.captured_rows) {
            const summary = ctx.target.querySelector(".algorithm-meta > span:first-child");
            if (summary) summary.textContent = `${view.name || "表格"} · ${rows.length} × ${width}${view.full_height || view.full_width ? ` / ${view.full_height ?? rows.length} × ${view.full_width ?? width}（已擷取）` : ""}${view.carried ? " · 沿用上次狀態" : ""}`;
        } else if (view.captured_rows) {
            const capturedWidth = Math.max(0, ...view.captured_rows.map((row) => row.length));
            const summary = ctx.target.querySelector(".algorithm-meta > span:first-child");
            if (summary) summary.textContent = `${view.name || "表格"} · ${rows.length} × ${width} / ${view.captured_rows.length} × ${capturedWidth}（已擷取）${view.full_height || view.full_width ? ` · 共 ${view.full_height ?? view.captured_rows.length} × ${view.full_width ?? capturedWidth}` : ""}${view.carried ? " · 沿用上次狀態" : ""}`;
        }
        if (ctx.follow !== false && anchors.length) {
            const [row, column] = anchors[0];
            const active = grid.querySelector(`[data-row="${row}"][data-column="${column}"]`);
            if (active) followWithin(ctx.target, active);
        }
    }
    function traceBounds(view, result) {
        if (!result || typeof result !== "object") return null;
        if (!scaleCache.has(result)) scaleCache.set(result, new Map());
        const cached = scaleCache.get(result);
        const key = view.name || "";
        if (cached.has(key)) return cached.get(key);
        let low = 0;
        let high = 0;
        const seen = new Set();
        for (const step of result.steps || []) {
            for (const model of [step.visualization, ...Object.values(step.views || {})]) {
                if (!model || model.name !== view.name || model.renderer !== "array" || seen.has(model)) continue;
                seen.add(model);
                const infinite = new Set(model.infinite || []);
                (model.captured_values || model.values || []).forEach((value, index) => {
                    const number = Number(value);
                    if (!infinite.has(index) && Number.isFinite(number)) { low = Math.min(low, number); high = Math.max(high, number); }
                });
            }
        }
        const bounds = high || low ? {low, high} : null;
        cached.set(key, bounds);
        return bounds;
    }
    function arrayPageState(view, ctx) {
        if (!ctx.result || typeof ctx.result !== "object") return {page: 0, step: ctx.index};
        if (!pageCache.has(ctx.result)) pageCache.set(ctx.result, new Map());
        const cache = pageCache.get(ctx.result);
        const key = `${view.renderer}:${view.name}`;
        if (!cache.has(key)) cache.set(key, {page: 0, step: null});
        const state = cache.get(key);
        if (state.step !== ctx.index && ctx.follow !== false) {
            const writes = operationWrites(view, ctx).filter((entry) => !entry.name || entry.name === view.name).map((entry) => entry.index);
            const markers = [...(view.markers || []), ...(view.beyond || [])].map((entry) => entry.index);
            const reads = entriesFor(view, ctx, "reads").filter((entry) => !entry.name || entry.name === view.name).map((entry) => entry.index);
            const anchor = [...writes, ...reads, ...markers].find((index) => Number.isInteger(index) && index >= 0);
            if (anchor !== undefined) state.page = Math.floor(anchor / PAGE_SIZE);
        }
        state.step = ctx.index;
        return state;
    }
    function renderArrayPage(view, ctx, chart) {
        const values = view.captured_values || view.values || [];
        const capturedTexts = view.captured_values_text || [];
        const oldTexts = view.values_text || [];
        const texts = values.map((value, index) => capturedTexts[index] ?? oldTexts[index] ?? value);
        const state = arrayPageState(view, ctx);
        state.page = Math.max(0, Math.min(Math.ceil(values.length / PAGE_SIZE) - 1, state.page));
        const start = state.page * PAGE_SIZE;
        const end = Math.min(values.length, start + PAGE_SIZE);
        const markers = new Map();
        for (const marker of [...(view.markers || []), ...(view.beyond || [])]) {
            if (!markers.has(marker.index)) markers.set(marker.index, []);
            markers.get(marker.index).push(marker);
        }
        const written = new Set([...(view.written || []), ...operationWrites(view, ctx).filter((entry) => !entry.name || entry.name === view.name).map((entry) => entry.index)]);
        const reading = new Set(entriesFor(view, ctx, "reads").filter((entry) => !entry.name || entry.name === view.name).map((entry) => entry.index));
        const added = new Set(view.added || []);
        const infinite = new Set(view.infinite || []);
        const finite = values.map(Number).filter(Number.isFinite);
        const bounds = traceBounds(view, ctx.result) || {low: Math.min(0, ...finite), high: Math.max(1, ...finite)};
        const count = end - start;
        const width = Math.max(28, Math.min(72, Math.floor((Math.max(250, ctx.target.clientWidth - 65) - (count - 1) * 8) / Math.max(1, count))));
        const longest = Math.max(1, ...texts.slice(start, end).map((value) => exact(value).length));
        const vertical = longest * 8 > width;
        const labelRoom = vertical ? Math.min(150, longest * 8 + 6) : 22;
        const plotRoom = Math.max(90, Math.min(350, ctx.target.clientHeight - 160));
        const barRoom = Math.max(40, plotRoom - labelRoom * (bounds.low < 0 ? 2 : 1));
        const magnitude = Math.max(Number.MIN_VALUE, Math.abs(bounds.low), Math.abs(bounds.high));
        const span = Math.max(Number.EPSILON, bounds.high / magnitude - bounds.low / magnitude);
        const upper = labelRoom + barRoom * (bounds.high / magnitude) / span;
        const lower = bounds.low < 0 ? barRoom * (-bounds.low / magnitude) / span + labelRoom : 0;
        const isBars = view.renderer === "array";
        chart.replaceChildren();
        chart.classList.toggle("vertical-values", vertical && isBars);
        chart.classList.add("focus-paged-array");
        chart.style.setProperty("--column", `${width}px`);
        chart.style.setProperty("--cell-width", `${Math.max(44, Math.min(140, longest * 9 + 16))}px`);
        for (let index = start; index < end; index++) {
            const item = node("div", isBars ? "array-column" : "cells-item");
            item.dataset.index = String(index);
            const atMarkers = markers.get(index) || [];
            for (const marker of atMarkers) if (marker.role) item.classList.add(marker.role);
            if (written.has(index)) item.classList.add("written");
            if (reading.has(index)) item.classList.add("focus-reading");
            if (added.has(index)) item.classList.add("added");
            const interval = view.sorting?.range || view.interval;
            const knownInterval = interval && (interval !== view.sorting?.range || interval.inclusive != null);
            if (knownInterval && !atMarkers.length && (index < interval.low || (interval.inclusive === false ? index >= interval.high : index > interval.high))) item.classList.add("outside-bound");
            if (view.sorting?.pivot?.index === index) item.classList.add("focus-pivot");
            if (isBars) {
                const plot = node("div", "array-plot");
                plot.style.height = `${upper + lower}px`;
                plot.style.setProperty("--zero", `${upper}px`);
                const bar = node("div", "array-bar");
                const label = node("span", "array-value", exact(texts[index]));
                const value = Number(values[index]);
                const infinity = infinite.has(index) || !Number.isFinite(value);
                const height = infinity ? Math.max(12, (upper - labelRoom) * .5) : value === 0 ? 0 : Math.max(3, (Math.abs(value) / magnitude) / span * barRoom);
                bar.style.height = `${height}px`;
                if (infinity) { item.classList.add("infinite"); label.textContent = "∞"; }
                if (value < 0 && !infinity) { item.classList.add("negative"); bar.style.top = `${upper}px`; label.style.top = `${upper + height + 4}px`; }
                else { bar.style.bottom = `${lower}px`; label.style.bottom = `${lower + height + 4}px`; }
                label.title = exact(texts[index]);
                plot.append(bar, label);
                const originalIndex = view.captured_labels?.[index] ?? view.labels?.[index];
                const indexLabel = node("span", "array-index", originalIndex == null ? index : `#${originalIndex}`);
                if (originalIndex != null) indexLabel.title = `sorted position ${index} · original index ${originalIndex}`;
                item.append(plot, indexLabel);
                if (atMarkers.length) item.append(node("span", "array-marker", atMarkers.map((marker) => marker.label).join(",")));
            } else {
                const value = node("span", "cells-value", exact(texts[index]));
                value.title = exact(texts[index]);
                item.append(node("span", "cells-index", index), value, node("span", "cells-marker", atMarkers.map((marker) => marker.label).join(",")));
            }
            chart.append(item);
        }
        const summary = ctx.target.querySelector(".algorithm-meta > span:first-child");
        const total = view.length ?? view.total_length ?? view.captured_length ?? values.length;
        if (summary) summary.textContent = `${view.name || "陣列"} · 索引 ${start}–${end - 1} · 已擷取 ${values.length}${total > values.length ? ` / ${total} 項（其餘未擷取）` : " 項"}${view.carried ? " · 沿用上次狀態" : ""}`;
        ctx.target.querySelectorAll(".focus-array-paging").forEach((item) => item.remove());
        const paging = node("div", "focus-array-paging debugger-focus-decoration");
        const previous = node("button", "focus-small-button", "上一頁");
        const next = node("button", "focus-small-button", "下一頁");
        previous.type = next.type = "button";
        previous.disabled = state.page === 0;
        next.disabled = end >= values.length;
        previous.addEventListener("click", () => { state.page--; renderArrayPage(view, ctx, chart); });
        next.addEventListener("click", () => { state.page++; renderArrayPage(view, ctx, chart); });
        const pageText = node("span", "focus-slice-note", `${state.page + 1} / ${Math.ceil(values.length / PAGE_SIZE)} 頁`);
        paging.append(previous, pageText, next);
        const offPage = [...new Set([...reading, ...written, ...markers.keys()])].filter((index) => Number.isInteger(index) && (index < start || index >= end));
        if (offPage.length) paging.append(node("span", "focus-slice-note", `標記在本頁外：${offPage.slice(0, 10).join(", ")}${offPage.length > 10 ? "…" : ""}`));
        chart.insertAdjacentElement("afterend", paging);
    }
    function decorateArray(view, ctx) {
        const chart = ctx.target.querySelector(".array-visualizer, .cells-view");
        if (!chart) return;
        const captured = view.captured_values || view.values || [];
        if (focused(ctx) && captured.length > PAGE_SIZE) renderArrayPage(view, ctx, chart);
        const values = view.values || [];
        if (!focused(ctx) && captured.length > values.length) {
            const summary = ctx.target.querySelector(".algorithm-meta > span:first-child");
            const total = view.length ?? view.total_length ?? captured.length;
            if (summary) summary.textContent = `${view.name || "陣列"} · 索引 0–${values.length - 1} · 已擷取 ${captured.length}${total > captured.length ? ` / ${total}` : ""} 項 · 開啟聚焦可翻頁${view.carried ? " · 沿用上次狀態" : ""}`;
        }
        const columns = [...chart.querySelectorAll(".array-column, .cells-item")];
        const operation = view.operation || {};
        const reads = entriesFor(view, ctx, "reads").filter((entry) => !entry.name || entry.name === view.name);
        const readIndexes = new Set(reads.map((entry) => entry.index).filter(Number.isInteger));
        const written = new Set(operationWrites(view, ctx).filter((entry) => !entry.name || entry.name === view.name).map((entry) => entry.index).filter(Number.isInteger));
        columns.forEach((column) => {
            const index = Number(column.dataset.index);
            column.classList.toggle("focus-reading", readIndexes.has(index));
            if (written.has(index)) column.classList.add("written");
        });
        const bounds = view.renderer === "array" ? traceBounds(view, ctx.result) : null;
        if (bounds && values.length && !chart.classList.contains("focus-paged-array")) {
            const meta = ctx.target.querySelector(".algorithm-meta");
            const longest = Math.max(1, ...(view.values_text || values).map((value) => exact(value).length));
            const labelRoom = chart.classList.contains("vertical-values") ? Math.min(150, longest * 8 + 6) : 22;
            const plotRoom = Math.max(90, Math.min(420, ctx.target.clientHeight - (meta?.offsetHeight || 0) - 110));
            const barRoom = Math.max(40, plotRoom - labelRoom * (bounds.low < 0 ? 2 : 1));
            const magnitude = Math.max(Number.MIN_VALUE, Math.abs(bounds.low), Math.abs(bounds.high));
            const span = Math.max(Number.EPSILON, bounds.high / magnitude - bounds.low / magnitude);
            const upper = labelRoom + barRoom * (bounds.high / magnitude) / span;
            const lower = bounds.low < 0 ? barRoom * (-bounds.low / magnitude) / span + labelRoom : 0;
            const infinite = new Set(view.infinite || []);
            columns.forEach((column, index) => {
                const plot = column.querySelector(".array-plot");
                const bar = column.querySelector(".array-bar");
                const label = column.querySelector(".array-value");
                if (!plot || !bar || !label) return;
                const value = Number(values[index]);
                const height = infinite.has(index) || !Number.isFinite(value) ? Math.max(12, (upper - labelRoom) * .5) : value === 0 ? 0 : Math.max(3, (Math.abs(value) / magnitude) / span * barRoom);
                plot.style.height = `${upper + lower}px`;
                plot.style.setProperty("--zero", `${upper}px`);
                bar.style.height = `${height}px`;
                bar.style.top = bar.style.bottom = label.style.top = label.style.bottom = "";
                if (value < 0 && !infinite.has(index)) { bar.style.top = `${upper}px`; label.style.top = `${upper + height + 4}px`; }
                else { bar.style.bottom = `${lower}px`; label.style.bottom = `${lower + height + 4}px`; }
            });
        }
        const interval = view.sorting?.range || view.interval;
        const phase = view.phase || operation.phase;
        if (interval || phase) {
            const intervalText = !interval ? "" : interval.inclusive == null && interval === view.sorting?.range ? `邊界 ${interval.left_name || "left"}=${interval.low}, ${interval.right_name || "right"}=${interval.high}` : `區間 [${interval.low}, ${interval.high}${interval.inclusive === false ? ")" : "]"}`;
            const info = node("div", "focus-range-note debugger-focus-decoration", `${phase ? `${typeof phase === "string" ? phase : phase.label || ""} · ` : ""}${intervalText}`.replace(/ · $/, ""));
            const operationBody = ctx.target.querySelector(".focus-operation-body");
            if (operationBody) operationBody.append(info);
            else chart.insertAdjacentElement("beforebegin", info);
            if (interval === view.sorting?.range && interval.inclusive == null) columns.forEach((column) => column.classList.remove("outside-bound"));
            else if (interval) columns.forEach((column) => {
                const index = Number(column.dataset.index);
                const marked = (view.markers || []).some((marker) => marker.index === index);
                if (!marked && (index < interval.low || (interval.inclusive === false ? index >= interval.high : index > interval.high))) column.classList.add("outside-bound");
            });
        }
        const sorting = view.sorting;
        if (sorting) {
            const details = node("div", "focus-sorting-state debugger-focus-decoration");
            if (sorting.pivot) {
                const pivot = sorting.pivot;
                details.append(node("span", "focus-pivot-note", `${pivot.name || "pivot"} = ${exact(pivot.value)}${pivot.index !== null && pivot.index !== undefined ? ` · 索引 ${pivot.index}` : ""}`));
                const pivotColumn = chart.querySelector(`[data-index="${Number(pivot.index)}"]`);
                if (pivot.index != null && pivotColumn) {
                    pivotColumn.classList.add("focus-pivot");
                    const marker = pivotColumn.querySelector(".array-marker, .cells-marker");
                    if (marker && !marker.textContent.includes(pivot.name || "pivot")) marker.append(` ${pivot.name || "pivot"}`);
                    else if (!marker) pivotColumn.append(node("span", "array-marker", pivot.name || "pivot"));
                }
            }
            if (sorting.temporary) {
                const buffer = sorting.temporary;
                const disclosure = node("details", "focus-frontier-details");
                disclosure.append(node("summary", "", `${buffer.name || "暫存"} · 已擷取 ${(buffer.values || []).length}${buffer.length ? ` / ${buffer.length}` : ""} 項`));
                const cells = node("div", "focus-buffer-values");
                (buffer.values || []).slice(0, 80).forEach((value, index) => {
                    const cell = node("span", "focus-buffer-cell", `${index}: ${exact(value)}`);
                    cell.title = `${buffer.name || "buffer"}[${index}] = ${exact(value)}`;
                    cells.append(cell);
                });
                if (buffer.truncated || (buffer.values || []).length > 80) cells.append(node("span", "focus-slice-note", "其餘暫存值未顯示"));
                disclosure.append(cells);
                details.append(disclosure);
            }
            if (details.childElementCount) {
                const operationBody = ctx.target.querySelector(".focus-operation-body");
                if (operationBody) operationBody.append(details);
                else chart.insertAdjacentElement("beforebegin", details);
            }
        }
        if (focused(ctx) && columns.length > 64 && !chart.classList.contains("focus-paged-array")) {
            const active = [...written, ...readIndexes, ...(view.markers || []).map((marker) => marker.index)].find(Number.isInteger) ?? 0;
            const start = Math.max(0, Math.min(columns.length - 48, active - 23));
            const end = Math.min(columns.length, start + 48);
            columns.forEach((column, index) => { column.hidden = index < start || index >= end; });
            chart.insertAdjacentElement("beforebegin", node("div", "focus-slice-note debugger-focus-decoration", `索引 ${start}–${end - 1} / 已擷取 ${columns.length} 項 · 關閉聚焦可看全部`));
        }
        if (bounds) {
            const scaleText = `全程尺度 ${exact(bounds.low)}…${exact(bounds.high)}`;
            chart.title = scaleText;
            const scaleInfo = document.getElementById("visual-scale-info");
            if (scaleInfo) {
                scaleInfo.textContent = scaleText;
                scaleInfo.hidden = false;
            }
        }
        if (ctx.follow !== false) {
            const anchor = chart.querySelector(".written:not([hidden]), .active:not([hidden]), .focus-reading:not([hidden])");
            if (anchor) followWithin(ctx.target, anchor);
        }
    }
    function compactFrontier(view, ctx) {
        const frontier = view.frontier;
        const summary = ctx.target.querySelector(".graph-frontier");
        if (!frontier || !summary) return;
        const entries = frontier.entries || frontier.items || [];
        const scope = {...(ctx.step?.globals || {}), ...(ctx.step?.locals || {})};
        const type = scope[frontier.name]?.container || scope[frontier.name]?.container_type || "";
        const isStack = type === "stack" || /^(st|stack)$/i.test(frontier.name || "");
        const isQueue = type === "queue" || /^(q|queue|que|frontier)$/i.test(frontier.name || "");
        const top = entries.length ? entries[isStack ? entries.length - 1 : 0] : "empty";
        const position = isStack ? "top" : isQueue ? "front" : "first captured";
        const count = frontier.count ?? frontier.length;
        const countText = Number.isInteger(count) ? `${count} items${count > entries.length ? ` · ${entries.length} captured` : ""}` : `${entries.length} captured`;
        const kept = [...summary.childNodes].filter((child) => child.nodeType !== 3);
        summary.replaceChildren(document.createTextNode(`${frontier.name}: ${position} ${clip(top, 100)} · ${countText} `), ...kept);
        summary.classList.add("focus-frontier-summary");
        const details = node("details", "focus-frontier-details debugger-focus-decoration");
        details.append(node("summary", "", "Inspect captured frontier order"));
        const items = node("ol", "focus-frontier-items");
        entries.forEach((entry) => items.append(node("li", "", entry)));
        if (!entries.length) items.append(node("li", "", "Empty"));
        details.append(items);
        summary.closest(".algorithm-meta")?.append(details);
    }
    function graphEdges(view, ctx) {
        const forest = view.layout === "forest";
        const direction = ctx.target.querySelector(".graph-direction-select")?.value;
        const directed = forest || direction === "directed" || (direction !== "undirected" && Boolean(view.directed));
        return directed || !view.undirected ? view.edges || [] : view.undirected.map((position) => view.edges[position]).filter(Boolean);
    }
    function decorateGraph(view, ctx) {
        const svg = ctx.target.querySelector(".algorithm-graph-svg");
        if (!svg) return;
        compactFrontier(view, ctx);
        const forest = view.layout === "forest";
        const nodes = view.nodes || [];
        const groups = [...svg.querySelectorAll(".algorithm-graph-node")];
        const edges = graphEdges(view, ctx);
        const nodeIds = new Set(nodes.map(String));
        const seeds = new Set();
        if (view.current !== null && view.current !== undefined) seeds.add(String(view.current));
        for (const entry of view.reading || []) seeds.add(String(entry.vertex));
        for (const entry of [...entriesFor(view, ctx, "reads"), ...entriesFor(view, ctx, "writes")]) {
            const vertex = entry.vertex ?? entry.index;
            if (vertex !== null && vertex !== undefined && nodeIds.has(String(vertex))) seeds.add(String(vertex));
        }
        if (view.checking) { seeds.add(String(view.checking.source)); seeds.add(String(view.checking.target)); }
        const route = [...(view.route?.items || []), ...(view.route?.next != null ? [view.route.next] : [])].map(String);
        const visible = new Set([...seeds, ...route]);
        const findPath = [];
        if (forest && seeds.size) {
            const parent = new Map((view.edges || []).map((edge) => [String(edge.source), String(edge.target)]));
            for (const start of seeds) {
                const seen = new Set();
                let current = start;
                while (nodeIds.has(current) && !seen.has(current)) {
                    seen.add(current);
                    visible.add(current);
                    if (start === String(view.current)) findPath.push(current);
                    const next = parent.get(current);
                    if (next == null || next === current) break;
                    current = next;
                }
            }
        } else {
            edges.forEach((edge) => {
                if (seeds.has(String(edge.source)) || seeds.has(String(edge.target))) { visible.add(String(edge.source)); visible.add(String(edge.target)); }
            });
        }
        groups.forEach((group, index) => {
            const id = String(nodes[index]);
            group.dataset.vertex = id;
            group.classList.toggle("focus-muted", focused(ctx) && visible.size > 0 && !visible.has(id));
            group.classList.toggle("focus-find-path", forest && findPath.includes(id));
            group.setAttribute("tabindex", "0");
            group.setAttribute("aria-label", `Vertex ${id}${view.labels && own(view.labels.values, id) ? `, ${view.labels.name} ${view.labels.values_text?.[id] ?? view.labels.values[id]}` : ""}`);
        });
        const paths = [...svg.querySelectorAll(".algorithm-graph-edge")];
        const drawnEdges = edges.filter((edge) => nodeIds.has(String(edge.source)) && nodeIds.has(String(edge.target)));
        paths.forEach((path, index) => {
            const edge = drawnEdges[index];
            if (!edge) return;
            const keep = visible.has(String(edge.source)) && visible.has(String(edge.target));
            path.classList.toggle("focus-muted", focused(ctx) && visible.size > 0 && !keep && !path.classList.contains("on-route"));
            path.dataset.source = String(edge.source);
            path.dataset.target = String(edge.target);
        });
        const weights = [...svg.querySelectorAll(".algorithm-graph-weight")];
        const weighted = drawnEdges.filter((edge) => edge.weight !== null && edge.weight !== undefined);
        weights.forEach((weight, index) => {
            const edge = weighted[index];
            if (edge) weight.classList.toggle("focus-muted", focused(ctx) && visible.size > 0 && !(visible.has(String(edge.source)) && visible.has(String(edge.target))));
        });
        if (forest && findPath.length) {
            const note = node("div", "focus-range-note debugger-focus-decoration", `Current parent chain: ${findPath.join(" → ")}`);
            note.title = "Parent pointers in the captured state; this is not an inferred sequence of find operations";
            const meta = ctx.target.querySelector(".algorithm-meta");
            if (meta) meta.append(note);
        }
        const teaching = view.teaching;
        if (teaching) {
            const meta = ctx.target.querySelector(".algorithm-meta");
            const vertexModels = [teaching.layers, teaching.indegree].filter(Boolean);
            groups.forEach((group, index) => {
                const id = String(nodes[index]);
                let labelIndex = 0;
                for (const model of vertexModels) {
                    if (!own(model.values, id) || model.name === view.labels?.name) continue;
                    const value = model.values_text?.[id] ?? model.values[id];
                    const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
                    label.setAttribute("class", "focus-vertex-state debugger-focus-decoration");
                    label.setAttribute("x", "0");
                    label.setAttribute("y", String(42 + labelIndex * 14));
                    label.textContent = `${model.name}=${exact(value)}`;
                    group.append(label);
                    group.setAttribute("aria-label", `${group.getAttribute("aria-label")}, ${model.name} ${exact(value)}`);
                    labelIndex++;
                }
            });
            for (const [key, label] of [["layers", "Recorded level / distance values"], ["indegree", "Recorded indegrees"], ["output", "Recorded output order"]]) {
                const model = teaching[key];
                if (!model) continue;
                const disclosure = node("details", "focus-frontier-details debugger-focus-decoration");
                disclosure.append(node("summary", "", `${label} · ${model.name || key}`));
                const items = node("div", "focus-buffer-values");
                const entries = Array.isArray(model.values) ? model.values.map((value, index) => [index, value]) : Object.entries(model.values || {});
                for (const [index, value] of entries.slice(0, 100)) items.append(node("span", "focus-buffer-cell", `${index}: ${exact(model.values_text?.[index] ?? value)}`));
                if (entries.length > 100) items.append(node("span", "focus-slice-note", `+${entries.length - 100} further captured values`));
                disclosure.append(items);
                meta?.append(disclosure);
            }
        }
        if (focused(ctx) && visible.size && visible.size < nodes.length) {
            ctx.target.querySelector(".algorithm-meta")?.append(node("span", "focus-slice-note debugger-focus-decoration", `${nodes.length - visible.size} unrelated vertices dimmed · hover a vertex to inspect`));
        }
        if (ctx.follow !== false && view.current != null) {
            const current = groups.find((group) => group.dataset.vertex === String(view.current));
            if (current) followWithin(ctx.target, current);
        }
    }
    function boundValue(ctx, role) {
        const binding = ctx.bindings?.[role];
        const name = typeof binding === "string" ? binding : binding?.name;
        if (!name) return null;
        const value = ctx.step?.locals?.[name] ?? ctx.step?.globals?.[name];
        return value?.value ?? null;
    }
    function decorateSegment(view, ctx) {
        const svg = ctx.target.querySelector(".segment-tree-svg");
        const layout = (ctx.result?.algorithm?.views || []).find((item) => item.renderer === "segment_tree" && item.variable === view.name)?.layout;
        if (!svg || !layout) return;
        const query = view.query || (Number.isInteger(boundValue(ctx, "query_left")) && Number.isInteger(boundValue(ctx, "query_right")) ? {low: boundValue(ctx, "query_left"), high: boundValue(ctx, "query_right")} : null);
        const path = new Set([...(view.path || []), ...(view.reading || []), ...(view.written || []).map((index) => layout.nodes[index]?.id)]);
        if (view.current != null) path.add(view.current);
        const nodes = [...svg.querySelectorAll(".segment-node")];
        const visible = new Set(path);
        const childrenOf = (id) => layout.root === 0 ? [id * 2 + 1, id * 2 + 2] : [id * 2, id * 2 + 1];
        for (const id of path) childrenOf(id).forEach((child) => visible.add(child));
        let lazy = view.lazy;
        if (!lazy && ctx.bindings?.lazy) {
            const name = typeof ctx.bindings.lazy === "string" ? ctx.bindings.lazy : ctx.bindings.lazy.name;
            const serialized = ctx.step?.locals?.[name] ?? ctx.step?.globals?.[name];
            if (serialized?.items) lazy = {name, values: serialized.items.map(exact), indexing: "node"};
        }
        nodes.forEach((group, position) => {
            const record = layout.nodes[position];
            if (!record) return;
            group.dataset.nodeId = String(record.id);
            group.classList.toggle("focus-muted", focused(ctx) && path.size > 0 && !visible.has(record.id));
            let overlap = "";
            if (query && Number.isFinite(query.low) && Number.isFinite(query.high)) {
                overlap = query.low > query.high || record.r < query.low || record.l > query.high ? "no-overlap" : query.low <= record.l && record.r <= query.high ? "full-overlap" : "partial-overlap";
                group.classList.add(`focus-${overlap}`);
                const title = group.querySelector("title");
                if (title) title.textContent += ` · ${overlap.replace(/-/g, " ")} with [${query.low}, ${query.high}]`;
            }
            if (lazy) {
                const value = Array.isArray(lazy.values) ? lazy.values[lazy.indexing === "layout" ? position : record.id] : lazy.values?.[record.id];
                if (value !== undefined && value !== null) {
                    const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
                    label.setAttribute("class", "focus-lazy-label");
                    const rect = group.querySelector("rect");
                    label.setAttribute("x", rect ? Number(rect.getAttribute("width")) / 2 : 40);
                    label.setAttribute("y", "-5");
                    label.textContent = `${lazy.name || "lazy"}=${exact(value)}`;
                    group.append(label);
                    const title = group.querySelector("title");
                    if (title) title.textContent += ` · ${lazy.name || "lazy"}[${record.id}] = ${exact(value)}`;
                }
            }
        });
        const byId = new Map(layout.nodes.map((entry) => [entry.id, entry]));
        const edgeRecords = layout.nodes.flatMap((record) => childrenOf(record.id).filter((id) => byId.has(id)).map((id) => [record.id, id]));
        [...svg.querySelectorAll(".segment-edge")].forEach((edge, position) => {
            const ends = edgeRecords[position];
            if (ends) edge.classList.toggle("focus-muted", focused(ctx) && path.size > 0 && !(visible.has(ends[0]) && visible.has(ends[1])));
        });
        const meta = ctx.target.querySelector(".algorithm-meta");
        if (query) meta?.append(node("div", "focus-range-note debugger-focus-decoration", `Query [${query.low}, ${query.high}] · solid: full coverage · dashed: partial · dim border: no overlap`));
        if (lazy) meta?.append(node("span", "focus-slice-note debugger-focus-decoration", `Captured ${lazy.name || "lazy"} tags shown above nodes`));
        if (focused(ctx) && path.size) {
            compactSegmentTree(svg, layout, nodes, visible, path, ctx);
            const dimmed = layout.nodes.filter((entry) => !visible.has(entry.id)).length;
            if (dimmed) meta?.append(node("span", "focus-slice-note debugger-focus-decoration", `${dimmed} captured nodes folded · Focus off shows the whole tree`));
        }
        if (ctx.follow !== false) {
            const current = svg.querySelector(".segment-node.current");
            if (current) followWithin(ctx.target, current);
        }
    }
    function compactSegmentTree(svg, layout, groups, visible, path, ctx) {
        const byId = new Map(layout.nodes.map((record) => [record.id, record]));
        const parentOf = (id) => layout.root === 0 ? Math.floor((id - 1) / 2) : Math.floor(id / 2);
        const childrenOf = (id) => layout.root === 0 ? [id * 2 + 1, id * 2 + 2] : [id * 2, id * 2 + 1];
        // A read/written node can live off the call path; retain its real ancestors too.
        for (const selected of [...visible]) {
            let id = selected;
            const seen = new Set();
            while (byId.has(id) && id !== layout.root && !seen.has(id)) {
                seen.add(id);
                id = parentOf(id);
                if (byId.has(id)) visible.add(id);
            }
        }
        const selected = layout.nodes.filter((record) => visible.has(record.id));
        if (!selected.length) return;
        const positions = new Map();
        let slot = 0;
        const widths = groups.map((group) => Number(group.querySelector("rect")?.getAttribute("width") || 80));
        const indexById = new Map(layout.nodes.map((record, index) => [record.id, index]));
        const nodeWidth = Math.max(140, ...widths, ...groups.map((group) => (group.querySelector(".focus-lazy-label")?.textContent.length || 0) * 6 + 12));
        const gapX = nodeWidth + 18;
        const gapY = viewHasLazy(groups) ? 102 : 88;
        // Iterative postorder avoids recursion even for manually supplied deep layouts.
        const pending = [{id: layout.root, visited: false}];
        const traversed = new Set();
        while (pending.length) {
            const item = pending.pop();
            if (!visible.has(item.id) || !byId.has(item.id)) continue;
            const children = childrenOf(item.id).filter((id) => visible.has(id) && byId.has(id));
            if (!item.visited && !traversed.has(item.id)) {
                traversed.add(item.id);
                pending.push({id: item.id, visited: true});
                for (let index = children.length - 1; index >= 0; index--) pending.push({id: children[index], visited: false});
            } else {
                const placed = children.map((id) => positions.get(id)).filter(Boolean);
                const x = placed.length ? (placed[0].x + placed[placed.length - 1].x) / 2 : slot++ * gapX + 80;
                positions.set(item.id, {x, y: 28 + byId.get(item.id).depth * gapY});
            }
        }
        groups.forEach((group, index) => {
            const record = layout.nodes[index];
            const position = positions.get(record.id);
            group.classList.toggle("focus-segment-hidden", !position);
            if (position) group.setAttribute("transform", `translate(${position.x} ${position.y})`);
        });
        const edgeRecords = layout.nodes.flatMap((record) => childrenOf(record.id).filter((id) => byId.has(id)).map((id) => [record.id, id]));
        [...svg.querySelectorAll(".segment-edge")].forEach((edge, index) => {
            const ends = edgeRecords[index];
            if (!ends) return;
            const from = positions.get(ends[0]);
            const to = positions.get(ends[1]);
            edge.classList.toggle("focus-segment-hidden", !from || !to);
            if (from && to) {
                const sourceIndex = indexById.get(ends[0]);
                const targetIndex = indexById.get(ends[1]);
                edge.setAttribute("x1", String(from.x + widths[sourceIndex] / 2));
                edge.setAttribute("y1", String(from.y + 42));
                edge.setAttribute("x2", String(to.x + widths[targetIndex] / 2));
                edge.setAttribute("y2", String(to.y));
            }
        });
        // Base cells remain available in the complete tree; compact mode keeps only leaf values.
        svg.querySelectorAll(".segment-base, .segment-base-label").forEach((item) => item.classList.add("focus-segment-hidden"));
        const subtreeSizes = new Map(layout.nodes.map((record) => [record.id, 1]));
        for (const record of [...layout.nodes].sort((left, right) => right.depth - left.depth)) {
            const parent = parentOf(record.id);
            if (record.id !== layout.root && subtreeSizes.has(parent)) subtreeSizes.set(parent, subtreeSizes.get(parent) + subtreeSizes.get(record.id));
        }
        for (const record of selected) {
            const hiddenChildren = childrenOf(record.id).filter((id) => byId.has(id) && !visible.has(id));
            const count = hiddenChildren.reduce((sum, id) => sum + (subtreeSizes.get(id) || 1), 0);
            if (!count) continue;
            const position = positions.get(record.id);
            const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
            label.setAttribute("class", "focus-segment-folded debugger-focus-decoration");
            label.setAttribute("x", String(position.x + widths[indexById.get(record.id)] / 2));
            label.setAttribute("y", String(position.y + 60));
            label.textContent = `+${count} captured nodes folded`;
            svg.append(label);
        }
        const contentWidth = Math.max(nodeWidth + 160, slot * gapX - 18 + 160);
        const contentHeight = Math.max(...selected.map((record) => record.depth)) * gapY + 105;
        svg.setAttribute("viewBox", `0 0 ${contentWidth} ${contentHeight}`);
        svg.setAttribute("width", String(contentWidth));
        svg.setAttribute("height", String(contentHeight));
        svg.classList.add("focus-compact-segment");
        ctx.target.scrollLeft = Math.max(0, ctx.target.scrollLeft);
    }
    function viewHasLazy(groups) { return groups.some((group) => group.querySelector(".focus-lazy-label")); }
    function decorate(view, ctx) {
        if (!ctx.target || !view?.ready) return;
        if (ctx.target.querySelector(".focus-decoration-marker")) return;
        ctx.target.classList.toggle("focus-enabled", focused(ctx));
        // The caller replaces the renderer DOM each step. Removing our annotations also makes
        // a repeated decoration safe without duplicating operation/frontier summaries.
        ctx.target.querySelectorAll(".debugger-focus-decoration").forEach((item) => item.remove());
        appendOperation(view, ctx);
        if (view.renderer === "grid") decorateGrid(view, ctx);
        else if (view.renderer === "array" || view.renderer === "cells") decorateArray(view, ctx);
        else if (view.renderer === "graph" || view.renderer === "dsu") decorateGraph(view, ctx);
        else if (view.renderer === "segment_tree") decorateSegment(view, ctx);
        const marker = node("span", "focus-decoration-marker");
        marker.hidden = true;
        ctx.target.append(marker);
    }
    window.DebuggerFocus = {
        render(view, ctx) {
            ctx.target?.classList.remove("has-focused-recursion");
            if (view?.renderer === "recursion_tree" && focused(ctx)) return renderRecursion(view, ctx);
            return false;
        },
        decorate,
    };
})();
