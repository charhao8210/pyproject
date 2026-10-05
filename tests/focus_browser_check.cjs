/* Run with Playwright available via NODE_PATH; uses installed Chrome, no app server required. */
const assert = require("node:assert/strict");
const path = require("node:path");
const {chromium} = require("playwright");

(async () => {
    const browser = await chromium.launch({channel: "chrome", headless: true});
    try {
        const page = await browser.newPage({viewport: {width: 860, height: 760}});
        const errors = [];
        page.on("pageerror", (error) => errors.push(error.message));
        await page.setContent('<html data-theme="dark"><body style="padding:16px"><div id="target" class="algorithm-canvas" style="height:610px;width:100%;min-width:0"></div><details id="settings"><summary>設定</summary><span id="visual-scale-info" hidden></span></details></body></html>');
        await page.addStyleTag({path: path.resolve("app/static/style.css")});
        await page.addStyleTag({path: path.resolve("app/static/focus.css")});
        await page.addScriptTag({path: path.resolve("app/static/focus.js")});
        await page.evaluate(() => {
            const make = (tag, cls, text) => {
                const element = document.createElement(tag);
                element.className = cls || "";
                if (text !== undefined) element.textContent = String(text);
                return element;
            };
            const svg = (tag, cls, attributes = {}) => {
                const element = document.createElementNS("http://www.w3.org/2000/svg", tag);
                element.setAttribute("class", cls || "");
                for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, value);
                return element;
            };
            window.jumps = [];
            window.fixtureResults = new Map();
            window.showFocusFixture = (view, options = {}) => {
                const target = document.querySelector("#target");
                target.replaceChildren();
                const scaleInfo = document.querySelector("#visual-scale-info");
                scaleInfo.textContent = "";
                scaleInfo.hidden = true;
                const key = options.key || view.name || view.renderer;
                if (!fixtureResults.has(key)) fixtureResults.set(key, options.result || {steps: [{visualization: view}], algorithm: {views: []}});
                const result = fixtureResults.get(key);
                const ctx = {target, view, result, step: options.step || {line: 6, usage: {}}, index: options.index ?? 0, focus: options.focus ?? true, follow: options.follow ?? true, bindings: options.bindings || {}, goToStep(index) { jumps.push(index); }};
                window.lastContext = ctx;
                if (DebuggerFocus.render(view, ctx)) return true;
                const meta = make("div", "algorithm-meta");
                meta.append(make("span", view.renderer === "graph" ? "graph-frontier" : "", "Original summary"), make("div", "algorithm-legend"));
                target.append(meta);
                if (view.renderer === "grid") {
                    const grid = make("div", "algorithm-grid");
                    (view.rows || []).forEach((row, rowIndex) => row.forEach((value, column) => {
                        const cell = make("div", "algorithm-cell", value);
                        cell.dataset.row = String(rowIndex);
                        cell.title = `row ${rowIndex}, column ${column}: ${value}`;
                        grid.append(cell);
                    }));
                    target.append(grid);
                } else if (view.renderer === "array" || view.renderer === "cells") {
                    const chart = make("div", view.renderer === "array" ? "array-visualizer" : "cells-view");
                    (view.values || []).forEach((value, index) => {
                        const item = make("div", view.renderer === "array" ? "array-column" : "cells-item");
                        item.dataset.index = String(index);
                        const plot = make("div", "array-plot");
                        plot.append(make("div", "array-bar"), make("span", "array-value", value));
                        item.append(plot);
                        chart.append(item);
                    });
                    target.append(chart);
                } else if (view.renderer === "graph") {
                    if (view.frontier) meta.firstChild.textContent = `${view.frontier.name}: ${(view.frontier.entries || view.frontier.items).join(" ")}`;
                    const graph = svg("svg", "algorithm-graph-svg", {viewBox: "0 0 700 350", width: 700, height: 350});
                    (view.edges || []).forEach((edge, index) => {
                        graph.append(svg("path", "algorithm-graph-edge", {d: `M ${index * 60 + 50} 100 L ${index * 60 + 100} 150`}));
                        if (edge.weight != null) graph.append(svg("text", "algorithm-graph-weight"));
                    });
                    (view.nodes || []).forEach((id, index) => {
                        const group = svg("g", `algorithm-graph-node${String(id) === String(view.current) ? " current" : ""}`, {transform: `translate(${60 + index * 100} 150)`});
                        group.append(svg("circle", "", {r: 26}));
                        const text = svg("text");
                        text.textContent = id;
                        group.append(text);
                        graph.append(group);
                    });
                    target.append(graph);
                } else if (view.renderer === "segment_tree") {
                    const layout = result.algorithm.views[0].layout;
                    const graph = svg("svg", "segment-tree-svg", {viewBox: "0 0 800 420", width: 800, height: 420});
                    layout.nodes.forEach((record) => [record.id * 2, record.id * 2 + 1].filter((id) => layout.nodes.some((item) => item.id === id)).forEach(() => graph.append(svg("line", "segment-edge"))));
                    layout.nodes.forEach((record, index) => {
                        const group = svg("g", `segment-node${record.id === view.current ? " current" : ""}`, {transform: `translate(${record.x * 75} ${record.depth * 80 + 20})`});
                        group.append(svg("rect", "", {width: 65, height: 42}));
                        const title = svg("title");
                        title.textContent = `${view.name}[${record.id}] = ${view.values[index]}`;
                        group.append(title);
                        graph.append(group);
                    });
                    target.append(graph);
                }
                DebuggerFocus.decorate(view, ctx);
                return false;
            };
        });
        const show = (view, options = {}) => page.evaluate(({view, options}) => showFocusFixture(view, options), {view, options});

        const deepNodes = Array.from({length: 1002}, (_, id) => ({id, order: id || null, parent: id ? id - 1 : null, function: "dfs", label: `dfs(${id})`, title: `dfs(depth=${id})`, params: ["depth"], start_step: id, end_step: null, return_value: null}));
        const deepView = {renderer: "recursion_tree", ready: true, current: 1001, at_step: 1001};
        assert.equal(await show(deepView, {key: "deep", index: 1001, result: {steps: [], algorithm: {recursion_tree: {nodes: deepNodes, truncated: false}}}}), true);
        assert.equal(await page.locator(".focus-call").count(), 40, "a 1002-call stack shows outer and inner calls, with bounded DOM");
        assert.match(await page.locator(".focus-summary-toggle").textContent(), /962 calls on this path folded/);
        assert.match(await page.locator(".is-current .focus-call-title").textContent(), /depth=1001/);
        await page.locator(".focus-summary-toggle").click();
        assert.equal(await page.locator(".focus-call").count(), 64, "folded path expands by one page");
        await page.locator('.focus-call[data-call-id="20"] .focus-call-title').click();
        assert.equal(await page.evaluate(() => jumps.at(-1)), 20, "call labels jump to real entries");

        const branchNodes = [{id: 0, parent: null, label: "main()", title: "main()", start_step: 0, end_step: null, return_value: null}, ...Array.from({length: 600}, (_, index) => ({id: index + 1, order: index + 1, parent: 0, label: `dfs(${index})`, title: `dfs(candidate=${index})`, start_step: index * 2 + 1, end_step: index * 2 + 2, return_value: String(index)}))];
        await show({renderer: "recursion_tree", ready: true, current: 0, at_step: 1201}, {key: "branches", index: 1201, result: {steps: [], algorithm: {recursion_tree: {nodes: branchNodes}}}});
        assert.equal(await page.locator(".focus-call").count(), 1);
        assert.match(await page.locator(".focus-summary-toggle").textContent(), /600 completed branches · 600 calls/);
        await page.locator(".focus-summary-toggle").click();
        assert.equal(await page.locator(".focus-call").count(), 25);
        await page.getByRole("button", {name: "Next calls", exact: true}).click();
        assert.equal(await page.locator('.focus-call[data-call-id="25"]').count(), 1);
        assert.match(await page.locator('.focus-call[data-call-id="25"] .focus-call-return').textContent(), /24/);
        await page.locator('.focus-call[data-call-id="25"] .focus-call-end').click();
        assert.equal(await page.evaluate(() => jumps.at(-1)), 50);

        const rows = Array.from({length: 80}, (_, row) => Array.from({length: 80}, (_, column) => row * 1000 + column));
        const dp = {renderer: "grid", ready: true, name: "dp", rows: rows.slice(0, 30).map((row) => row.slice(0, 40)), captured_rows: rows, full_height: 100, full_width: 120, current_cell: {row: 65, column: 70}, written: [], active: [], operation: {kind: "transition", label: "DP state update", evidence: "trace", reads: [{name: "dp", cell: [65, 69], value: 65069}, {name: "dp", cell: [64, 70], value: 64070}], writes: [{name: "dp", cell: [65, 70], before: 0, after: 65070}], expression: "dp[i][j-1] + 1", substituted: "65069 + 1", candidate: {expression: "dp[i][j-1] + 1", value: 65070}, source: "dp[i][j] = dp[i][j-1] + 1"}};
        await show(dp);
        assert.equal(await page.locator('.algorithm-cell[data-row="65"][data-column="70"]').textContent(), "65070", "focus reaches captured data beyond the legacy grid");
        assert.equal(await page.locator(".algorithm-cell").count(), 14 * 18);
        assert.equal(await page.locator(".algorithm-cell.focus-reading").count(), 2);
        assert.equal(await page.locator(".algorithm-cell.written").count(), 1);
        assert.equal(await page.locator(".focus-reading-key").count(), 0, "reading dependencies are represented by the operation and cell highlights");
        assert.match(await page.locator(".focus-formula").first().textContent(), /65069 \+ 1/);
        assert.match(await page.locator(".focus-candidate").textContent(), /候選值：.*65070/);
        assert.equal(await page.locator(".focus-candidate").isVisible(), false, "candidate remains in folded details by default");
        assert.equal(await page.locator(".focus-candidate-summary").count(), 0, "candidate does not add a second summary");
        assert.match(await page.locator(".focus-write-chip").textContent(), /0 → 65070/);
        await page.evaluate(() => DebuggerFocus.decorate(lastContext.view, lastContext));
        assert.equal(await page.locator(".focus-operation").count(), 1, "repeated decoration is idempotent");
        await page.getByRole("button", {name: "上一組欄", exact: true}).click();
        assert.equal(await page.locator('.algorithm-cell[data-row="65"][data-column="44"]').textContent(), "65044", "grid pages use actual absolute coordinates and values");
        await show(dp, {index: 1, follow: false});
        assert.equal(await page.locator('.algorithm-cell[data-row="65"][data-column="44"]').count(), 1, "grid Follow off retains manual slice");
        await show(dp, {index: 2, follow: true});
        assert.equal(await page.locator('.algorithm-cell[data-row="65"][data-column="70"]').count(), 1, "grid Follow on returns to recorded coordinate");
        await show({...dp, current_cell: {row: 180, column: 190}, operation: undefined});
        assert.match(await page.locator(".beyond-note").textContent(), /未擷取/);
        await show(dp, {focus: false});
        assert.equal(await page.locator(".algorithm-cell").count(), 30 * 40, "Focus off retains full legacy captured grid");

        const captured = Array.from({length: 120}, (_, index) => index - 50);
        const array = {renderer: "array", ready: true, name: "a", values: captured.slice(0, 60), captured_values: captured, captured_length: 120, length: 200, markers: [{index: 87, label: "i", role: "active"}], written: [87], operation: {label: "Recorded array update", reads: [{name: "a", index: 86, value: 36}], writes: [{name: "a", index: 87, before: 36, after: 37}]}};
        await show(array, {key: "paged-array", index: 1});
        assert.equal(await page.locator(".array-column").count(), 24);
        assert.equal(await page.locator('.array-column[data-index="87"].written').count(), 1);
        assert.equal(await page.locator('.array-column[data-index="86"].focus-reading').count(), 1);
        assert.match(await page.locator(".algorithm-meta").textContent(), /其餘未擷取/);
        assert.equal(await page.locator(".algorithm-meta").textContent().then((text) => /Scale|尺度/.test(text)), false, "scale does not clutter the default metadata");
        assert.equal(await page.locator("#visual-scale-info").textContent(), "全程尺度 -50…69");
        assert.equal(await page.locator(".array-visualizer").getAttribute("title"), "全程尺度 -50…69");
        await page.getByRole("button", {name: "上一頁", exact: true}).click();
        assert.equal(await page.locator('.array-column[data-index="48"]').count(), 1);
        assert.match(await page.locator(".focus-array-paging").textContent(), /標記在本頁外：86, 87/, "hidden operation coordinates remain disclosed after manual paging");
        await show(array, {key: "paged-array", index: 2, follow: false});
        assert.equal(await page.locator('.array-column[data-index="48"]').count(), 1, "Follow off retains manual page");
        await show(array, {key: "paged-array", index: 3, follow: true});
        assert.equal(await page.locator('.array-column[data-index="87"]').count(), 1, "Follow on returns to actual active index");
        const bigText = Array.from({length: 120}, (_, index) => String(index));
        bigText[87] = "9007199254740993123";
        await show({...array, renderer: "cells", name: "exact", captured_values_text: bigText});
        assert.equal(await page.locator('.cells-item[data-index="87"] .cells-value').textContent(), "9007199254740993123");
        await show({...array, name: "sort", interval: {low: 70, high: 100}, sorting: {pivot: {name: "pivot", value: 37, index: 87}, range: {low: 70, high: 100, inclusive: null, left_name: "lo", right_name: "hi"}, temporary: {name: "merged", values: [1, 2, 4], length: 3}}});
        assert.equal(await page.locator('.array-column[data-index="87"].focus-pivot').count(), 1);
        assert.match(await page.locator(".focus-range-note").textContent(), /邊界 lo=70, hi=100/);
        assert.equal(await page.locator(".focus-range-note").isVisible(), false, "sorting details stay folded by default");
        assert.equal(await page.locator(".outside-bound").count(), 0, "unknown sorting interval convention does not imply inclusive shading");
        assert.equal(await page.locator(".focus-buffer-cell").count(), 3, "recorded merge buffer has its own disclosure");
        await show({renderer: "array", ready: true, name: "small-floats", values: [.001, .002], markers: [], written: []});
        const smallHeights = await page.locator(".array-bar").evaluateAll((bars) => bars.map((bar) => Number.parseFloat(bar.style.height)));
        assert.ok(Math.abs(smallHeights[1] / smallHeights[0] - 2) < .01, "small finite floats use the full stable scale");
        await show({renderer: "array", ready: true, name: "extreme-floats", values: [-1e308, 1e308], captured_values: Array.from({length: 30}, (_, index) => index % 2 ? 1e308 : -1e308), markers: [], written: []});
        const extremeHeights = await page.locator(".array-bar").evaluateAll((bars) => bars.map((bar) => Number.parseFloat(bar.style.height)));
        assert.ok(extremeHeights.every((height) => Number.isFinite(height) && height > 0), "finite extreme floats do not overflow bar scaling");

        const readingArray = {renderer: "array", ready: true, name: "read", values: [1, 4], markers: [], written: [], operation: {reads: [{name: "a", index: 1, value: 4}]}};
        await show(readingArray);
        assert.equal(await page.locator(".focus-operation-primary").textContent(), "讀取 a[1] = 4", "read summary uses the recorded value");
        await show({...readingArray, name: "unknown-read", operation: {reads: [{name: "a", index: 1}]}});
        assert.equal(await page.locator(".focus-operation-primary").textContent(), "讀取 a[1] · 值未擷取", "missing operation values are not inferred from the current array snapshot");
        await show({...readingArray, name: "unknown-write", operation: {writes: [{name: "a", index: 1, before: 4}]}});
        assert.equal(await page.locator(".focus-operation-primary").textContent(), "a[1]：已變更，值未擷取", "missing write results are explicit");
        await show({...array, name: "carried-array", carried: true});
        assert.match(await page.locator(".algorithm-meta").textContent(), /沿用上次狀態/, "carried data remains distinguishable from a fresh capture");

        const fullExpression = "dp[i][j-1] + ".repeat(60) + "1";
        const exactCandidate = "900719925474099312345678901234567890";
        await show({...dp, name: "full-formula", operation: {...dp.operation, expression: fullExpression, candidate: {expression: fullExpression, value: exactCandidate}}});
        assert.equal(await page.locator(".focus-candidate").isVisible(), false);
        assert.equal(await page.locator(".focus-candidate").textContent(), `候選值：${fullExpression} = ${exactCandidate}`, "complete candidate expression and exact text remain in details");
        assert.equal(await page.locator(".focus-formula").first().textContent(), `dp[65][70] ← ${fullExpression} = 65069 + 1`, "long formulas are not truncated in the disclosure");
        await page.locator(".focus-operation-summary").click();
        assert.equal(await page.locator(".focus-candidate").isVisible(), true);

        const graph = {renderer: "graph", ready: true, name: "adj", nodes: [0, 1, 2, 3, 4, 5], edges: [{source: 0, target: 1, weight: 2}, {source: 1, target: 2, weight: 1}, {source: 3, target: 4, weight: 5}], current: 0, reading: [{vertex: 1}], route: {name: "path", items: [0, 1]}, frontier: {name: "q", items: Array.from({length: 40}, (_, index) => index), count: 40}};
        await show(graph);
        assert.equal(await page.locator(".algorithm-graph-node.focus-muted").count(), 3);
        assert.equal(await page.locator(".algorithm-graph-edge.focus-muted").count(), 1);
        assert.match(await page.locator(".graph-frontier").textContent(), /front 0 · 40 items/);
        assert.equal(await page.locator(".focus-frontier-items li").count(), 40);
        assert.equal(await page.locator(".algorithm-graph-node[tabindex='0']").count(), 6);
        await show({...graph, teaching: {layers: {name: "dist", values: {0: 0, 1: 2, 2: 3}}, indegree: {name: "indegree", values: {0: 0, 1: 1}}, output: {name: "order", values: [0, 1]}}});
        assert.equal(await page.locator(".focus-vertex-state").count(), 5);
        assert.ok((await page.locator(".focus-frontier-details").allTextContents()).some((text) => /level \/ distance/.test(text)), "a distance array is not described as an inferred BFS layer");
        const forest = {...graph, name: "parent", layout: "forest", edges: [{source: 1, target: 0}, {source: 2, target: 1}, {source: 4, target: 3}], current: 2, reading: [], route: undefined, frontier: undefined, operation: {label: "Parent change", evidence: "snapshot", writes: [{name: "parent", index: 2, before: 1, after: 0}]}};
        await show(forest);
        assert.match(await page.locator(".focus-range-note").textContent(), /2 → 1 → 0/);
        assert.match(await page.locator(".focus-write-chip").textContent(), /1 → 0/);
        assert.equal(await page.locator(".algorithm-graph-node.focus-find-path").count(), 3);

        const segmentNodes = [];
        const visit = (id, low, high, depth) => {
            segmentNodes.push({id, l: low, r: high, depth, x: (low + high) / 2});
            if (low < high) { const middle = (low + high) >>> 1; visit(id * 2, low, middle, depth + 1); visit(id * 2 + 1, middle + 1, high, depth + 1); }
        };
        visit(1, 0, 7, 0);
        const segment = {renderer: "segment_tree", ready: true, name: "tree", current: 4, path: [1, 2, 4], reading: [8], written: [], values: segmentNodes.map((record) => String(record.id)), query: {low: 2, high: 4}, lazy: {name: "pending", values: {1: "0", 2: "7", 4: "9007199254740993"}}};
        await show(segment, {result: {steps: [], algorithm: {views: [{renderer: "segment_tree", variable: "tree", layout: {nodes: segmentNodes, root: 1}}]}}});
        assert.equal(await page.locator(".focus-lazy-label").count(), 3);
        assert.equal(await page.locator('.segment-node[data-node-id="4"] .focus-lazy-label').textContent(), "pending=9007199254740993");
        assert.ok(await page.locator(".segment-node.focus-full-overlap").count());
        assert.ok(await page.locator(".segment-node.focus-partial-overlap").count());
        assert.ok(await page.locator(".segment-node.focus-no-overlap").count());
        assert.ok(await page.locator(".segment-node.focus-muted").count());
        assert.ok(await page.locator(".segment-node.focus-segment-hidden").count(), "irrelevant segment subtrees are folded from the compact layout");
        assert.ok(await page.locator(".focus-segment-folded").count(), "folded subtree counts remain visible");

        for (const width of [860, 360]) {
            await page.setViewportSize({width, height: 780});
            for (const paneHeight of [200, 240]) {
                await page.evaluate((height) => document.querySelector("#target").style.height = `${height}px`, paneHeight);
                await show(dp, {index: 100 + paneHeight + width});
                assert.equal(await page.locator(".focus-operation[open]").count(), 0, "operation starts as a compact disclosure");
                assert.match(await page.locator(".focus-operation-primary").textContent(), /dp\[65\]\[70\]：0 → 65070/);
                assert.equal(await page.locator(".focus-candidate-summary").count(), 0);
                assert.equal(await page.locator(".focus-candidate").isVisible(), false);
                assert.match(await page.locator(".focus-operation-range").textContent(), /列.*欄.*目前 \(65, 70\)/);
                assert.equal(await page.locator(".focus-operation-range").isVisible(), false, "grid range is available in details");
                const bounds = await page.evaluate(() => {
                    const target = document.querySelector("#target").getBoundingClientRect();
                    const summary = document.querySelector(".focus-operation").getBoundingClientRect();
                    const cell = document.querySelector('.algorithm-cell[data-row="65"][data-column="70"]').getBoundingClientRect();
                    return {target: {top: target.top, bottom: target.bottom, left: target.left, right: target.right}, summary: {top: summary.top, bottom: summary.bottom, left: summary.left, right: summary.right, height: summary.height}, cell: {top: cell.top, bottom: cell.bottom}};
                });
                assert.ok(bounds.summary.height <= 36, `${width}px / ${paneHeight}px pane keeps the summary to one line`);
                assert.ok(bounds.summary.top >= bounds.target.top - 1 && bounds.summary.bottom < bounds.target.bottom, "summary stays visible after follow scroll");
                assert.ok(bounds.summary.left >= bounds.target.left - 1 && bounds.summary.right <= bounds.target.right + 1, "summary stays visible after horizontal follow scroll");
                assert.ok(bounds.cell.top >= bounds.summary.bottom + 3 && bounds.cell.bottom <= bounds.target.bottom, "current DP cell stays visible below the compact summary");
                assert.equal(await page.locator(".focus-formula").first().isVisible(), false, "full formula is folded by default");
                await page.locator(".focus-operation-summary").click();
                assert.equal(await page.locator(".focus-formula").first().isVisible(), true, "full formula is available on demand");
                assert.equal(await page.locator(".focus-candidate").isVisible(), true, "candidate is visible after expanding the details");
                assert.equal(await page.locator(".focus-candidate").textContent(), "候選值：dp[i][j-1] + 1 = 65070");
                assert.equal(await page.locator(".focus-operation-range").isVisible(), true);
                assert.equal(await page.locator(".focus-read-chip").count(), 2, "complete dependencies remain available");
                await page.locator(".focus-operation-summary").focus();
                await page.keyboard.press("Enter");
                assert.equal(await page.locator(".focus-operation[open]").count(), 0);
                await page.keyboard.press("Space");
                assert.equal(await page.locator(".focus-operation[open]").count(), 1, "native details remain operable from the keyboard");
                await page.keyboard.press("Enter");
                assert.equal(await page.locator(".focus-operation[open]").count(), 0);
            }
        }
        await page.evaluate(() => document.querySelector("#target").style.height = "610px");

        for (const theme of ["dark", "light"]) {
            await page.evaluate((theme) => document.documentElement.dataset.theme = theme, theme);
            await page.setViewportSize({width: 360, height: 780});
            await show(dp);
            assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, `grid stays inside page at 360px in ${theme}`);
            await show(array, {key: "paged-array", index: 4});
            assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, `array scrolls within pane at 360px in ${theme}`);
            await show({renderer: "recursion_tree", ready: true, current: 0, at_step: 1201}, {key: "branches", index: 1201});
            assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, `recursion stays inside page at 360px in ${theme}`);
        }
        await show({...dp, name: "safe", operation: {label: '<img src=x onerror="window.injected=true">', writes: [{name: "safe", cell: [65, 70], before: 0, after: "<script>alert(1)</script>"}]}});
        assert.equal(await page.locator("#target img, #target script").count(), 0, "trace text remains text");
        assert.equal(await page.evaluate(() => window.injected), undefined);
        assert.deepEqual(errors, [], "no browser runtime errors");
        console.log("Focus browser checks passed (deep DFS, 600 calls, DP 200/240px panes, one-line summaries, folded full formulas/candidates, missing values, paging/exact text/follow, scale settings, graph/DSU, segment lazy/query, 360px dark/light, keyboard, safe text).");
    } finally {
        await browser.close();
    }
})().catch((error) => {console.error(error); process.exitCode = 1;});
