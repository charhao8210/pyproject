/* Requires the app on DEBUGGER_URL (default :8765) and Playwright via NODE_PATH. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const {chromium} = require("playwright");

(async () => {
    const browser = await chromium.launch({channel: "chrome", headless: true});
    try {
        const page = await browser.newPage({viewport: {width: 1440, height: 900}});
        const errors = [];
        page.on("pageerror", (error) => errors.push(error.message));
        await page.goto(process.env.DEBUGGER_URL || "http://127.0.0.1:8765/");
        const run = async () => {
            const response = page.waitForResponse((item) => item.url().endsWith("/api/debug"));
            await page.locator("#run-button").click();
            const payload = await (await response).json();
            await page.waitForFunction(() => !document.querySelector("#run-button").disabled);
            assert.equal(payload.status, "completed");
            return payload;
        };
        await page.locator("#language-select").selectOption("cpp");
        const payload = await run();
        const step = payload.steps.findIndex((item) => item.line === 14 && item.visualization?.operation?.reads?.some((read) => read.name === "a" && read.index === 1 && read.value === 4));
        assert.ok(step >= 0, "the screenshot's actual read exists in the C++ trace");
        await page.evaluate((index) => goToStep(index), step);
        await page.locator('[data-panel="variables"] .panel-toggle').click();
        await page.locator('[data-panel="stdout"] .panel-toggle').click();
        assert.equal(await page.locator("#algorithm-name").textContent(), "陣列 · a · 6 項");
        assert.match(await page.locator(".focus-operation-primary").textContent(), /讀取 a\[1\] = 4/);
        assert.equal(await page.locator("#algorithm-inputs").isVisible(), false, "n is already represented by the array's size");
        assert.equal(await page.locator(".algorithm-meta").isVisible(), false, "full arrays do not repeat their title or read legend");
        assert.equal(await page.locator("#algorithm-detected-name").isVisible(), false);
        assert.equal(await page.locator("#event-label").isVisible(), false, "ordinary line events do not add redundant text");
        assert.equal(await page.locator("#step-label").textContent(), `${step + 1} / ${payload.steps.length}`);
        assert.equal(await page.locator(".variables-panel .usage-legend").isVisible(), false);
        assert.equal(await page.locator(".variables-panel .panel-toggle").getAttribute("aria-expanded"), "false");
        await page.locator("#visual-settings > summary").click();
        assert.equal(await page.locator("#algorithm-detected-name").isVisible(), true);
        assert.equal(await page.locator("#visual-scale-info").isVisible(), true);
        assert.match(await page.locator("#visual-scale-info").textContent(), /0…8/);
        await page.keyboard.press("Escape");
        assert.equal(await page.locator("#visual-settings").getAttribute("open"), null);
        assert.equal(await page.locator("#visual-settings > summary").evaluate((item) => item === document.activeElement), true);
        await page.locator("#visual-settings > summary").click();
        await page.locator("#algorithm-name").click();
        assert.equal(await page.locator("#visual-settings").getAttribute("open"), null, "outside click closes settings");
        fs.mkdirSync(".pytest_cache", {recursive: true});
        await page.screenshot({path: path.resolve(".pytest_cache/compact-ui-desktop.png")});
        for (const width of [390, 360]) {
            await page.setViewportSize({width, height: 844});
            await page.waitForFunction(() => {
                const viewer = document.querySelector("#source-viewer").getBoundingClientRect();
                const line = document.querySelector(".source-line.current").getBoundingClientRect();
                return line.top >= viewer.top && line.bottom <= viewer.bottom;
            });
            for (const theme of ["dark", "light"]) {
                await page.evaluate((value) => setTheme(value), theme);
                await page.locator("#visual-settings > summary").click();
                assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, `${width}px ${theme}: settings stay within the page`);
                const settingBounds = await page.locator(".binding-form").boundingBox();
                const timelineBounds = await page.locator(".timeline").boundingBox();
                assert.ok(settingBounds.y >= 0 && settingBounds.y + settingBounds.height < timelineBounds.y, "mobile settings remain above the timeline");
                await page.keyboard.press("Escape");
                assert.equal(await page.locator(".focus-operation-primary").isVisible(), true);
                const bounds = await page.locator(".focus-operation-primary").boundingBox();
                assert.ok(bounds.x >= 0 && bounds.x + bounds.width <= width + 1);
            }
        }
        await page.screenshot({path: path.resolve(".pytest_cache/compact-ui-mobile.png"), fullPage: true});
        await page.locator('[data-panel="source"] .panel-toggle').click();
        assert.equal(await page.locator('[data-panel="stdin"] .panel-toggle').isVisible(), true, "collapsing source preserves the mobile input panel");
        assert.ok((await page.locator(".stdin-panel").boundingBox()).height > 40);
        await page.locator('[data-panel="stdin"] .panel-toggle').click();
        await page.locator('[data-panel="stdin"] .panel-toggle').click();
        assert.equal(await page.locator("#stdin-editor").isVisible(), true);
        await page.locator('[data-panel="source"] .panel-toggle').click();
        await page.locator("#language-select").selectOption("python");
        await page.locator("#code-editor").fill("n = int(input())\ntarget = int(input())\na = [i + 1 for i in range(n)]\nanswer = a[target - 1]\nprint(answer)");
        await page.locator("#stdin-editor").fill("6\n6");
        const search = await run();
        const arrayStep = search.steps.findIndex((item) => item.line === 4 && item.visualization?.ready);
        assert.ok(arrayStep >= 0);
        await page.evaluate((index) => goToStep(index), arrayStep);
        assert.match(await page.locator("#algorithm-inputs").textContent(), /target = 6/, "a meaningful target equal to array size remains visible");
        await page.locator("#edit-button").click();
        await page.locator("#code-editor").fill("n = 80\na = list(range(n))\nprint(a[70])");
        await page.locator("#stdin-editor").fill("");
        const partial = await run();
        await page.evaluate((index) => goToStep(index), partial.steps.findIndex((item) => item.line === 3));
        assert.equal(await page.locator(".algorithm-meta").isVisible(), true);
        assert.match(await page.locator(".algorithm-meta").textContent(), /未擷取/, "capture limits remain visible after metadata deduplication");
        assert.deepEqual(errors, []);
        console.log("Compact UI browser checks passed: actual C++ read, metadata deduplication, settings/Escape/focus, collapsed controls, 360/390px themes, preserved target and capture notices.");
    } finally { await browser.close(); }
})().catch((error) => {console.error(error); process.exitCode = 1;});
