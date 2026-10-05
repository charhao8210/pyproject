/* Run with Playwright available via NODE_PATH; uses an installed Chrome browser. */
const assert = require("node:assert/strict");
const path = require("node:path");
const {chromium} = require("playwright");

const fixtures = [
    {renderer: "heap", ready: true, name: "pq", order: "min", values: [1, 4, 2, 8, 7, 3, 6], top: 1, nodes: [1, 4, 2, 8, 7, 3, 6].map((value, index) => ({index, value, parent: index ? Math.floor((index - 1) / 2) : null, left: 2 * index + 1 < 7 ? 2 * index + 1 : null, right: 2 * index + 2 < 7 ? 2 * index + 2 : null}))},
    {renderer: "window", ready: true, name: "a", values: Array.from({length: 60}, (_, index) => index), bounds: {left: 42, right: 45, inclusive: true}, window: {left: 42, right: 45, empty: false}, markers: [{index: 42, label: "left"}, {index: 45, label: "right"}], aggregate: {name: "total", value: 174}, length: 80, truncated: true},
    {renderer: "monotonic", ready: true, name: "stack", values: [0, 2, 4], entries: [{position: 0, value: 0, index: 0, data_value: 1}, {position: 1, value: 2, index: 2, data_value: 3}, {position: 2, value: 4, index: 4, data_value: 8}], role: "stack", source_name: "a", source_values: [1, 2, 3, 9, 8], delta: {added: [4], removed: [3], evidence: "snapshot"}},
    {renderer: "fenwick", ready: true, name: "bit", values: [0, 1, 3, 3, 10, 5, 11, 7, 36], nodes: Array.from({length: 8}, (_, index) => ({index: index + 1, value: index + 1, low: index + 2 - ((index + 1) & -(index + 1)), high: index + 1})), current: 6, accesses: [6], markers: [{index: 6, label: "i"}], operation: {kind: "query", label: "Read (traced)", evidence: "trace", reads: [{name: "bit", index: 6, value: 11}]}},
    {renderer: "string_match", ready: true, name: "text", text: "ababababac", pattern: "ababac", prefix: [0, 0, 1, 2, 3, 0], prefix_name: "lps", i: 7, j: 3, alignment: 4, comparison: {left: "b", right: "b", equal: true}, operation: {label: "Compare (traced)", evidence: "trace", reads: [{name: "text", index: 7, value: "b"}, {name: "pattern", index: 3, value: "b"}]}},
    {renderer: "trie", ready: true, name: "root", nodes: [{id: "root", label: "root", path: "", terminal: false}, {id: "root/a", label: "a", path: "a", terminal: true}, {id: "root/a/b", label: "b", path: "ab", terminal: true}], edges: [{source: "root", target: "root/a", label: "a"}, {source: "root/a", target: "root/a/b", label: "b"}], current: "root/a", path: ["root", "root/a"]},
];

(async () => {
    const browser = await chromium.launch({channel: "chrome", headless: true});
    try {
        const page = await browser.newPage({viewport: {width: 360, height: 780}});
        const errors = [];
        page.on("pageerror", (error) => errors.push(error.message));
        await page.setContent('<html data-theme="dark"><body style="padding:16px"><div id="target" style="width:100%;max-width:100%;min-width:0"></div></body></html>');
        await page.addStyleTag({path: path.resolve("app/static/style.css")});
        await page.addStyleTag({path: path.resolve("app/static/lenses.css")});
        await page.addScriptTag({path: path.resolve("app/static/lenses.js")});
        const show = (view, options = {}) => page.evaluate(({view, options}) => window.AlgorithmLenses.render(view, {target: document.querySelector("#target"), focus: false, follow: true, ...options}), {view, options});
        for (const theme of ["dark", "light"]) {
            await page.evaluate((theme) => document.documentElement.dataset.theme = theme, theme);
            for (const view of fixtures) {
                assert.equal(await show(view), true, `${view.renderer} is handled`);
                assert.ok(await page.locator(".al-title").textContent());
                const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
                assert.equal(overflow, false, `${view.renderer} stays inside a 360px viewport in ${theme}`);
            }
        }
        await show(fixtures[0]);
        await page.locator('button.al-cell[data-index="2"]').click();
        assert.equal(await page.locator('.al-tree-node[data-index="2"]').getAttribute("aria-pressed"), "true");
        assert.match(await page.locator(".al-selection-detail").textContent(), /parent \[0\] = 1/);
        await page.locator('.al-tree-node[data-index="1"]').focus();
        await page.keyboard.press("Enter");
        assert.match(await page.locator(".al-selection-detail").textContent(), /\[1\] = 4/);

        await show(fixtures[1]);
        assert.equal(await page.locator('.al-cell[data-index="45"]').count(), 1, "follow finds current window");
        await page.getByRole("button", {name: "Previous captured a page", exact: true}).click();
        assert.equal(await page.locator('.al-cell[data-index="24"]').count(), 1, "captured value pages are navigable");
        assert.match(await page.locator(".al-status").textContent(), /Partial capture of 80/);

        await show(fixtures[4]);
        const aligned = await page.locator(".al-match-column").allTextContents();
        assert.ok(aligned.some((text) => text.includes("p0")), "pattern aligned at real text offset");
        assert.equal(await page.locator(".al-match-column.is-active").count(), 1);
        assert.match(await page.locator(".al-readouts").last().textContent(), /Comparisonb = b/);
        await show({...fixtures[4], i: null, j: null, alignment: null});
        assert.equal(await page.locator(".al-match-grid").count(), 0, "missing indices do not invent an alignment");

        await show(fixtures[5]);
        assert.equal(await page.locator(".al-trie-row").count(), 3);
        await page.locator('[data-trie-id="root/a"] > .al-trie-row > button').click();
        assert.equal(await page.locator(".al-trie-row").count(), 2, "trie branches fold");

        await show({renderer: "heap", ready: true, name: "safe", values: ['<img src=x onerror="window.injected=true">'], nodes: [{index: 0, value: '<img src=x onerror="window.injected=true">', parent: null}]});
        assert.equal(await page.locator("#target img").count(), 0, "captured text is not HTML");
        assert.equal(await page.evaluate(() => window.injected), undefined);
        assert.equal(await show({renderer: "window", ready: false}), true);
        assert.match(await page.locator(".al-note").textContent(), /Waiting/);
        assert.equal(await show({renderer: "unknown", ready: true}), false);
        assert.deepEqual(errors, [], "no browser runtime errors");
        if (process.env.LENSES_SCREENSHOT) {
            await show(fixtures[4]);
            await page.screenshot({path: process.env.LENSES_SCREENSHOT, fullPage: true});
        }
        console.log("Algorithm lens browser checks passed (6 modes, 360px, dark/light, navigation, keyboard, missing data, safe text).");
    } finally {
        await browser.close();
    }
})().catch((error) => {console.error(error); process.exitCode = 1;});
