/* Requires a running app: DEBUGGER_URL=http://127.0.0.1:8765, Playwright via NODE_PATH. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const {chromium} = require("playwright");
const url = process.env.DEBUGGER_URL || "http://127.0.0.1:8765";

(async () => {
    const browser = await chromium.launch({channel: "chrome", headless: true});
    try {
        const page = await browser.newPage({viewport: {width: 1440, height: 900}});
        const errors = [];
        page.on("pageerror", (error) => errors.push(error.message));
        await page.goto(url);
        await page.waitForFunction(() => document.querySelectorAll("#example-select option").length > 10);
        async function run() {
            const response = page.waitForResponse((response) => response.url().endsWith("/api/debug") && response.request().method() === "POST");
            await page.locator("#run-button").click();
            const result = await response;
            assert.equal(result.status(), 200, await result.text());
            const payload = await result.json();
            assert.equal(payload.status, "completed");
            await page.waitForFunction(() => document.querySelector("#run-button").disabled === false);
            return payload;
        }
        for (const [sample, renderer] of [
            ["sample8_heap.py", "heap"], ["sample9_sliding_window.py", "window"],
            ["sample10_monotonic_stack.py", "monotonic"], ["sample11_fenwick.py", "fenwick"],
            ["sample12_kmp.py", "string_match"], ["sample13_trie.py", "trie"],
        ]) {
            await page.locator("#example-select").selectOption(sample);
            const payload = await run();
            const entry = payload.algorithm.views.find((view) => view.renderer === renderer);
            assert.ok(entry, `${renderer} is available`);
            const index = payload.steps.findIndex((step) => step.views[entry.id]?.ready && step.views[entry.id]?.operation?.writes?.length);
            const target = index >= 0 ? index : payload.steps.findIndex((step) => step.views[entry.id]?.ready);
            await page.locator("#view-select").selectOption(renderer);
            await page.evaluate((index) => goToStep(index), target);
            assert.ok(await page.locator(".al-title").textContent(), `${renderer} renders in the actual app`);
            for (const width of [1440, 390]) {
                await page.setViewportSize({width, height: 900});
                assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, `${renderer} width ${width}`);
            }
        }
        await page.setViewportSize({width: 1440, height: 900});
        await page.locator("#edit-button").click();
        await page.locator("#code-editor").fill("def dfs(n):\n    if n == 0:\n        return 1\n    return dfs(n-1) + dfs(n-1)\nprint(dfs(8))");
        const dfs = await run();
        await page.locator("#view-select").selectOption("recursion_tree");
        const deep = dfs.steps.findIndex((step) => step.views.recursion_tree.current > 400 && step.event === "call");
        await page.evaluate((index) => goToStep(index), deep);
        assert.ok(await page.locator(".focus-call.is-current").count());
        await page.locator("#step-mode").selectOption("call");
        const expected = await page.evaluate(() => navigationTarget(1));
        await page.locator("#next-button").click();
        assert.equal(await page.evaluate(() => state.currentStep), expected);
        const end = await page.evaluate(() => currentCallEnd());
        assert.ok(Number.isInteger(end));
        await page.locator("#call-end-button").click();
        assert.equal(await page.evaluate(() => state.currentStep), end);
        await page.locator("#focus-toggle").uncheck();
        assert.ok(await page.locator(".recursion-node").count() <= 400);
        await page.locator("#focus-toggle").check();
        await page.locator("#edit-button").click();
        await page.locator("#code-editor").fill("table = [[0]*75 for _ in range(70)]\nr=65\nc=70\ntable[r-1][c]=2\ntable[r][c-1]=3\ntable[r][c]=table[r-1][c]+table[r][c-1]\nprint(table[r][c])");
        await page.locator("#visual-settings > summary").click();
        await page.locator("#capture-items").selectOption("100");
        await run();
        await page.locator("#visual-settings > summary").click();
        await page.locator("#binding-mode").selectOption("dp");
        await page.locator('select[data-role="primary"]').selectOption("table");
        await page.locator('select[data-role="row"]').selectOption("r");
        await page.locator('select[data-role="column"]').selectOption("c");
        const pairedResponse = page.waitForResponse((response) => response.url().endsWith("/api/debug"));
        await page.locator("#apply-bindings").click();
        const paired = await (await pairedResponse).json();
        assert.equal(paired.status, "completed");
        await page.waitForFunction(() => document.querySelector("#run-button").disabled === false);
        assert.equal(paired.algorithm.kind, "dynamic_programming");
        await page.locator("#view-select").selectOption("auto");
        const write = paired.steps.findIndex((step) => step.line === 6 && step.event === "line");
        await page.evaluate((index) => goToStep(index), write);
        assert.match(await page.locator("#algorithm-confidence").textContent(), /手動配對/);
        assert.match(await page.locator("#algorithm-view").textContent(), /5/);
        assert.ok(await page.locator('.algorithm-cell[data-row="65"][data-column="70"]').count());
        await page.locator("#visual-settings > summary").click();
        const operationSummary = page.locator(".focus-operation > summary");
        await operationSummary.focus();
        await page.keyboard.press("Space");
        assert.equal(await page.locator(".focus-operation").getAttribute("open"), "");
        assert.equal(await page.locator("#play-button").getAttribute("aria-pressed"), "false");
        await page.keyboard.press("Space");
        assert.equal(await page.locator(".focus-operation").getAttribute("open"), null);
        fs.mkdirSync(".pytest_cache", {recursive: true});
        await page.screenshot({path: path.resolve(".pytest_cache/debugger-dp-desktop.png")});
        await page.locator("#theme-button").click();
        await page.setViewportSize({width: 390, height: 844});
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
        await page.screenshot({path: path.resolve(".pytest_cache/debugger-dp-mobile.png"), fullPage: true});
        assert.deepEqual(errors, []);
        console.log("Integrated debugger browser checks passed: six modes, DFS >400, event/skip navigation, manual DP beyond old limits, desktop/mobile/themes.");
    } finally { await browser.close(); }
})().catch((error) => {console.error(error); process.exitCode = 1;});
