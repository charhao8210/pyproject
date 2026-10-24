// Page layout: resizable columns and panels, collapsing, display size, theme, saved preferences.

const STORAGE_PREFIX = "code-visual-debugger";

// Matches the resizer track in style.css; the minimums keep both columns usable.
const COLUMN_RESIZER_WIDTH = 14;
const COLUMN_MIN_WIDTH = {left: 300, right: 480};

// Panels in the right column never shrink below these heights while a row resizer is dragged.
const ROW_MIN_HEIGHT = {algorithm: 140, variables: 90, stdout: 70};

// The workspace can be dragged taller than the window (the page then scrolls), never below this.
const WORKSPACE_MIN_HEIGHT = 360;

// Display sizes offered in every panel header; 100% is the default.
const PANEL_ZOOMS = [50, 75, 90, 100, 110, 125, 150];

function setLeftColumnWidth(width) {
    const total = elements.workspace.clientWidth;
    const maxWidth = total - COLUMN_RESIZER_WIDTH - COLUMN_MIN_WIDTH.right;
    const clamped = Math.round(Math.min(Math.max(COLUMN_MIN_WIDTH.left, width), maxWidth));
    elements.workspace.style.setProperty("--left-width", `${clamped}px`);
}

function startColumnResize(event) {
    if (event.button !== 0) return;
    elements.columnResizer.setPointerCapture(event.pointerId);
    elements.columnResizer.classList.add("is-dragging");
    document.body.classList.add("is-resizing-columns");
    event.preventDefault();
}

function moveColumnResize(event) {
    if (!elements.columnResizer.hasPointerCapture(event.pointerId)) return;
    const left = elements.workspace.getBoundingClientRect().left;
    setLeftColumnWidth(event.clientX - left - COLUMN_RESIZER_WIDTH / 2);
}

function finishColumnResize(event) {
    if (elements.columnResizer.hasPointerCapture(event.pointerId)) {
        elements.columnResizer.releasePointerCapture(event.pointerId);
    }
    elements.columnResizer.classList.remove("is-dragging");
    document.body.classList.remove("is-resizing-columns");
}

function resizeColumnsWithKeyboard(event) {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    // Stop the document-level handler from also moving the trace a step.
    event.stopPropagation();
    const current = elements.leftColumn.getBoundingClientRect().width;
    setLeftColumnWidth(current + (event.key === "ArrowLeft" ? -24 : 24));
}

// A row resizer moves the boundary between the nearest open panels above and below it.
// While resizing, every open panel's height becomes its flex-grow (with a zero basis), so
// the panels keep exactly these heights and scale together when the window changes.
function rowResizeNeighbours(resizer) {
    const panels = [...elements.rightColumn.querySelectorAll(":scope > .panel")];
    const open = (panel) => !panel.classList.contains("is-collapsed");
    const above = panels.filter((panel) => resizer.compareDocumentPosition(panel) & Node.DOCUMENT_POSITION_PRECEDING);
    const below = panels.filter((panel) => resizer.compareDocumentPosition(panel) & Node.DOCUMENT_POSITION_FOLLOWING);
    return {above: above.reverse().find(open), below: below.find(open), panels: panels.filter(open)};
}

// The pointer's start and the panel heights when a drag began. Every move is measured from
// this start, so the boundary stays under the pointer and other panels never drift.
let rowDrag = null;

function measureRowSizes(resizer) {
    const {above, below, panels} = rowResizeNeighbours(resizer);
    // Measure every panel before writing any size: each write reflows the column. Borders sit
    // outside the zero flex basis, so only the inner height becomes the flex-grow.
    const innerHeight = (panel) => panel.getBoundingClientRect().height - (panel.offsetHeight - panel.clientHeight);
    return {above, below, panels, heights: panels.map(innerHeight)};
}

function setRowSize(panel, height) {
    panel.classList.add("has-row-size");
    // Unrounded, so the grow values add up to the column's free space exactly.
    panel.style.setProperty("--row-grow", String(height));
}

function moveRowBoundary(sizes, delta) {
    const {above, below, panels, heights} = sizes;
    if (!above || !below) return;
    const aboveHeight = heights[panels.indexOf(above)];
    const total = aboveHeight + heights[panels.indexOf(below)];
    const minimum = (panel) => ROW_MIN_HEIGHT[panel.dataset.panel] || 80;
    const next = Math.min(Math.max(minimum(above), aboveHeight + delta), total - minimum(below));
    panels.forEach((panel, index) => {
        setRowSize(panel, panel === above ? next : panel === below ? total - next : heights[index]);
    });
}

function startRowResize(event) {
    if (event.button !== 0) return;
    const resizer = event.currentTarget;
    resizer.setPointerCapture(event.pointerId);
    resizer.classList.add("is-dragging");
    rowDrag = {startY: event.clientY, sizes: measureRowSizes(resizer)};
    document.body.classList.add("is-resizing-rows");
    event.preventDefault();
}

function moveRowResize(event) {
    const resizer = event.currentTarget;
    if (!rowDrag || !resizer.hasPointerCapture(event.pointerId)) return;
    moveRowBoundary(rowDrag.sizes, event.clientY - rowDrag.startY);
}

function finishRowResize(event) {
    const resizer = event.currentTarget;
    if (resizer.hasPointerCapture(event.pointerId)) resizer.releasePointerCapture(event.pointerId);
    resizer.classList.remove("is-dragging");
    document.body.classList.remove("is-resizing-rows");
    rowDrag = null;
}

function resetRowSizes() {
    elements.rightColumn.querySelectorAll(":scope > .panel").forEach((panel) => {
        panel.classList.remove("has-row-size");
        panel.style.removeProperty("--row-grow");
    });
}

function resizeRowsWithKeyboard(event) {
    if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
    event.preventDefault();
    event.stopPropagation();
    moveRowBoundary(measureRowSizes(event.currentTarget), event.key === "ArrowUp" ? -24 : 24);
}

// A resizer shows only when it has an open panel directly above it and one somewhere below;
// that keeps one handle per boundary when a panel in the middle is collapsed.
function updateRowResizers() {
    elements.rowResizers.forEach((resizer) => {
        const previous = resizer.previousElementSibling;
        const {below} = rowResizeNeighbours(resizer);
        resizer.hidden = !(previous && !previous.classList.contains("is-collapsed") && below);
    });
}

// The workspace resizer sets the height of both columns together; without it the workspace
// fills the window. Panels keep their shares, so a taller workspace gives each one more room.
function setWorkspaceHeight(height) {
    if (height === null) {
        elements.workspace.style.removeProperty("--workspace-height");
        elements.workspace.classList.remove("has-custom-height");
        return;
    }
    elements.workspace.style.setProperty("--workspace-height", `${Math.round(Math.max(WORKSPACE_MIN_HEIGHT, height))}px`);
    elements.workspace.classList.add("has-custom-height");
}

function startWorkspaceResize(event) {
    if (event.button !== 0) return;
    const resizer = event.currentTarget;
    resizer.setPointerCapture(event.pointerId);
    resizer.classList.add("is-dragging");
    rowDrag = {startY: event.clientY, height: elements.workspace.getBoundingClientRect().height};
    document.body.classList.add("is-resizing-rows");
    event.preventDefault();
}

function moveWorkspaceResize(event) {
    if (!rowDrag || !event.currentTarget.hasPointerCapture(event.pointerId)) return;
    setWorkspaceHeight(rowDrag.height + event.clientY - rowDrag.startY);
}

function resizeWorkspaceWithKeyboard(event) {
    if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
    event.preventDefault();
    event.stopPropagation();
    setWorkspaceHeight(elements.workspace.getBoundingClientRect().height + (event.key === "ArrowUp" ? -48 : 48));
}

function readPreference(name, fallback) {
    try {
        const value = localStorage.getItem(`${STORAGE_PREFIX}:${name}`);
        return value === null ? fallback : JSON.parse(value);
    } catch (_error) {
        return fallback;
    }
}

function writePreference(name, value) {
    try {
        localStorage.setItem(`${STORAGE_PREFIX}:${name}`, JSON.stringify(value));
    } catch (_error) {
        // Storage can be unavailable in privacy-restricted browser contexts.
    }
}

function currentTheme() {
    return document.documentElement.dataset.theme === "light" ? "light" : "dark";
}

function setTheme(theme, persist = true) {
    document.documentElement.dataset.theme = theme;
    elements.themeButton.textContent = theme === "dark" ? "☀" : "☾";
    elements.themeButton.title = theme === "dark" ? "切換淺色主題" : "切換深色主題";
    elements.themeButton.setAttribute("aria-label", elements.themeButton.title);
    // The theme is read before app.js loads, so it is stored as a plain string.
    if (persist) {
        try {
            localStorage.setItem(`${STORAGE_PREFIX}:theme`, theme);
        } catch (_error) {
            // Storage can be unavailable in privacy-restricted browser contexts.
        }
    }
}

function setupPanelToggles() {
    const saved = readPreference("panels", {});
    elements.collapsiblePanels.forEach((panel) => {
        panel.querySelector(".panel-toggle").addEventListener("click", () => {
            setPanelExpanded(panel, panel.classList.contains("is-collapsed"));
            // Input values move to Variables while the algorithm panel is hidden.
            if (state.result?.steps.length) renderStep();
            writePreference("panels", Object.fromEntries(elements.collapsiblePanels.map((item) => [
                item.dataset.panel,
                !item.classList.contains("is-collapsed"),
            ])));
        });
        setPanelExpanded(panel, saved?.[panel.dataset.panel] !== false);
    });
}

function setPanelExpanded(panel, expanded) {
    const button = panel.querySelector(".panel-toggle");
    document.getElementById(button.getAttribute("aria-controls")).hidden = !expanded;
    panel.classList.toggle("is-collapsed", !expanded);
    button.textContent = expanded ? "▼" : "▶";
    const panelName = {source: "程式碼", stdin: "輸入", algorithm: "資料", variables: "變數", stdout: "輸出"}[panel.dataset.panel];
    button.title = `${expanded ? "收合" : "展開"}${panelName}`;
    button.setAttribute("aria-label", button.title);
    if (!expanded && panel === elements.algorithmPanel) elements.visualSettings.open = false;
    button.setAttribute("aria-expanded", String(expanded));

    const columnCollapsed = (column) => [...column.querySelectorAll("[data-panel]")]
        .every((item) => item.classList.contains("is-collapsed"));
    elements.workspace.classList.toggle("left-collapsed", columnCollapsed(elements.leftColumn));
    elements.workspace.classList.toggle("right-collapsed", columnCollapsed(elements.rightColumn));
    updateRowResizers();
}

// Each panel header gets a display-size menu that zooms the panel's body (not its header).
// Below 100% more of the code, table, or graph fits; the visualization is redrawn at that size.
function setupPanelZooms() {
    const saved = readPreference("panel-zoom", {});
    elements.collapsiblePanels.forEach((panel) => {
        const toggle = panel.querySelector(".panel-toggle");
        const select = document.createElement("select");
        select.className = "panel-zoom";
        select.title = "顯示大小";
        select.setAttribute("aria-label", "顯示大小");
        select.append(...PANEL_ZOOMS.map((zoom) => new Option(`${zoom}%`, String(zoom))));
        const zoom = Number(saved?.[panel.dataset.panel]);
        select.value = String(PANEL_ZOOMS.includes(zoom) ? zoom : 100);
        select.addEventListener("change", () => {
            setPanelZoom(panel, Number(select.value));
            writePreference("panel-zoom", Object.fromEntries(elements.collapsiblePanels.map((item) => [
                item.dataset.panel,
                Number(item.querySelector(".panel-zoom").value),
            ])));
            if (state.result?.steps.length) renderStep();
        });
        toggle.before(select);
        setPanelZoom(panel, Number(select.value));
    });
}

function setPanelZoom(panel, zoom) {
    const body = document.getElementById(panel.querySelector(".panel-toggle").getAttribute("aria-controls"));
    if (zoom === 100) body.style.removeProperty("zoom");
    else body.style.zoom = String(zoom / 100);
}
