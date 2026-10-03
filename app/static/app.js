"use strict";

const CPP_SAMPLE = `#include <iostream>
using namespace std;

int main() {
    int n;
    cin >> n;
    int a[20] = {};

    for (int i = 0; i < n; ++i) cin >> a[i];

    for (int i = 0; i < n; ++i) {
        for (int j = 0; j + 1 < n - i; ++j) {
            if (a[j] > a[j + 1]) {
                int temp = a[j];
                a[j] = a[j + 1];
                a[j + 1] = temp;
            }
        }
    }

    for (int i = 0; i < n; ++i) cout << a[i] << (i + 1 == n ? '\\n' : ' ');
    return 0;
}`;

const CPP_SAMPLE_STDIN = `6
5 1 4 2 8 3`;

const state = {
    result: null,
    currentStep: 0,
    language: "python",
    drafts: {
        python: null,
        cpp: CPP_SAMPLE,
    },
    stdinDrafts: {
        python: null,
        cpp: CPP_SAMPLE_STDIN,
    },
    objectLabels: new Map(),
    objectTypes: new Map(),
    algorithmGraphPositions: new Map(),
    recursionPositions: new Map(),
    callChainPositions: new Map(),
    playback: {
        timer: null,
        speed: 1,
    },
    // The view the user picked; it is kept across runs and applied whenever the new trace offers it.
    view: {
        renderer: "auto",
        variable: null,
    },
};

const RENDERER_LABELS = {
    grid: "Grid",
    array: "Bars",
    cells: "Cells",
    graph: "Graph",
    dsu: "Union-find forest",
    recursion_tree: "Recursion tree",
    call_tree: "Call chain",
    execution: "Current line",
};

const STORAGE_PREFIX = "code-visual-debugger";
// At 1× speed, autoplay advances this many steps per second.
const PLAYBACK_STEPS_PER_SECOND = 2;
const PLAYBACK_SPEEDS = [0.25, 0.5, 1, 1.5, 1.75, 2];
// Matches the resizer track in style.css; the minimums keep both columns usable.
const COLUMN_RESIZER_WIDTH = 14;
const COLUMN_MIN_WIDTH = {left: 300, right: 480};
// Panels in the right column never shrink below these heights while a row resizer is dragged.
const ROW_MIN_HEIGHT = {algorithm: 140, variables: 90, stdout: 70};

const elements = {
    runButton: document.querySelector("#run-button"),
    editButton: document.querySelector("#edit-button"),
    languageSelect: document.querySelector("#language-select"),
    editorWrap: document.querySelector("#editor-wrap"),
    editor: document.querySelector("#code-editor"),
    editorHighlight: document.querySelector("#editor-highlight"),
    editorGutter: document.querySelector("#editor-gutter"),
    columnResizer: document.querySelector("#column-resizer"),
    rowResizers: [...document.querySelectorAll(".row-resizer")],
    stdinEditor: document.querySelector("#stdin-editor"),
    stdinCount: document.querySelector("#stdin-count"),
    sourceViewer: document.querySelector("#source-viewer"),
    variables: document.querySelector("#variables"),
    stdout: document.querySelector("#stdout"),
    workspace: document.querySelector("#workspace"),
    leftColumn: document.querySelector("#left-column"),
    rightColumn: document.querySelector("#right-column"),
    algorithmPanel: document.querySelector(".algorithm-panel"),
    collapsiblePanels: [...document.querySelectorAll("[data-panel]")],
    themeButton: document.querySelector("#theme-button"),
    playButton: document.querySelector("#play-button"),
    speedSelect: document.querySelector("#speed-select"),
    location: document.querySelector("#current-location"),
    functionName: document.querySelector("#function-name"),
    status: document.querySelector("#run-status"),
    message: document.querySelector("#message"),
    slider: document.querySelector("#step-slider"),
    stepLabel: document.querySelector("#step-label"),
    eventLabel: document.querySelector("#event-label"),
    algorithmName: document.querySelector("#algorithm-name"),
    algorithmConfidence: document.querySelector("#algorithm-confidence"),
    algorithmEvidence: document.querySelector("#algorithm-evidence"),
    algorithmView: document.querySelector("#algorithm-view"),
    algorithmInputs: document.querySelector("#algorithm-inputs"),
    viewSelect: document.querySelector("#view-select"),
    viewVariableSelect: document.querySelector("#view-variable-select"),
    loopStartButton: document.querySelector("#loop-start-button"),
    previousButton: document.querySelector("#previous-button"),
    nextButton: document.querySelector("#next-button"),
    loopEndButton: document.querySelector("#loop-end-button"),
};

const containerTypes = new Set(["list", "tuple", "dict", "set", "frozenset", "object"]);
const SVG_NS = "http://www.w3.org/2000/svg";

elements.runButton.addEventListener("click", runCode);
elements.editButton.addEventListener("click", showEditor);
elements.languageSelect.addEventListener("change", changeLanguage);
elements.themeButton.addEventListener("click", () => setTheme(currentTheme() === "dark" ? "light" : "dark"));
elements.viewSelect.addEventListener("change", (event) => chooseView(event.target.value, null));
elements.viewVariableSelect.addEventListener("change", (event) => chooseView(state.view.renderer, event.target.value));
elements.playButton.addEventListener("click", togglePlayback);
elements.speedSelect.addEventListener("change", (event) => setPlaybackSpeed(Number(event.target.value)));
// Skip the innermost loop around the current line (`step.loop` comes from the backend).
elements.loopStartButton.addEventListener("click", () => jumpOutOfLoop("before"));
elements.previousButton.addEventListener("click", () => stepManually(state.currentStep - 1));
elements.nextButton.addEventListener("click", () => stepManually(state.currentStep + 1));
elements.loopEndButton.addEventListener("click", () => jumpOutOfLoop("after"));
elements.slider.addEventListener("input", (event) => stepManually(Number(event.target.value)));
elements.stdinEditor.addEventListener("input", () => {
    updateStdinCount();
    saveDrafts();
});

elements.editor.addEventListener("keydown", (event) => {
    if (event.key !== "Tab") return;
    event.preventDefault();
    const start = elements.editor.selectionStart;
    const end = elements.editor.selectionEnd;
    elements.editor.setRangeText("    ", start, end, "end");
    renderEditorHighlight();
});
elements.editor.addEventListener("input", () => {
    // Line numbers in an old error no longer match once the code is edited.
    if (state.editorErrors?.length) state.editorErrors = [];
    renderEditorHighlight();
    saveDrafts();
});
// The caret's line number is bold in the gutter, so follow every caret move, not only edits.
document.addEventListener("selectionchange", () => {
    if (document.activeElement === elements.editor) renderEditorGutter();
});
elements.editor.addEventListener("scroll", syncEditorHighlightScroll);
elements.columnResizer.addEventListener("pointerdown", startColumnResize);
elements.columnResizer.addEventListener("pointermove", moveColumnResize);
elements.columnResizer.addEventListener("pointerup", finishColumnResize);
elements.columnResizer.addEventListener("pointercancel", finishColumnResize);
elements.columnResizer.addEventListener("dblclick", () => elements.workspace.style.removeProperty("--left-width"));
elements.columnResizer.addEventListener("keydown", resizeColumnsWithKeyboard);
elements.rowResizers.forEach((resizer) => {
    resizer.addEventListener("pointerdown", startRowResize);
    resizer.addEventListener("pointermove", moveRowResize);
    resizer.addEventListener("pointerup", finishRowResize);
    resizer.addEventListener("pointercancel", finishRowResize);
    resizer.addEventListener("dblclick", resetRowSizes);
    resizer.addEventListener("keydown", resizeRowsWithKeyboard);
});

document.addEventListener("keydown", (event) => {
    if (!state.result || [elements.editor, elements.stdinEditor].includes(document.activeElement)) return;
    if (event.key === "ArrowLeft") {
        event.preventDefault();
        stepManually(state.currentStep - 1);
    } else if (event.key === "ArrowRight") {
        event.preventDefault();
        stepManually(state.currentStep + 1);
    } else if (event.key === " " && !event.target.closest("button, select, input")) {
        event.preventDefault();
        togglePlayback();
    }
});

// Visualizations are sized to their panels, so redraw them when a panel changes size.
let resizeFrame = 0;
const panelResizeObserver = new ResizeObserver(() => {
    cancelAnimationFrame(resizeFrame);
    resizeFrame = requestAnimationFrame(() => {
        const step = state.result?.steps[state.currentStep];
        if (!step) return;
        renderAlgorithm(currentVisualization(step));
    });
});
panelResizeObserver.observe(elements.algorithmPanel);

updateStdinCount();
renderEditorHighlight();
setTheme(currentTheme(), false);
restorePlaybackSpeed();
setupPanelToggles();
state.drafts.python = elements.editor.value;
state.stdinDrafts.python = elements.stdinEditor.value;
restoreDrafts();

// The code and stdin of both languages, and the chosen language, survive a page reload.
function saveDrafts() {
    state.drafts[state.language] = elements.editor.value;
    state.stdinDrafts[state.language] = elements.stdinEditor.value;
    writePreference("drafts", {language: state.language, code: state.drafts, stdin: state.stdinDrafts});
}

function restoreDrafts() {
    const saved = readPreference("drafts", null);
    if (!saved || typeof saved !== "object") return;
    ["python", "cpp"].forEach((language) => {
        if (typeof saved.code?.[language] === "string") state.drafts[language] = saved.code[language];
        if (typeof saved.stdin?.[language] === "string") state.stdinDrafts[language] = saved.stdin[language];
    });
    if (saved.language in state.drafts) state.language = saved.language;
    elements.languageSelect.value = state.language;
    elements.editor.value = state.drafts[state.language];
    elements.stdinEditor.value = state.stdinDrafts[state.language];
    updateStdinCount();
    renderEditorHighlight();
}

function changeLanguage(event) {
    const nextLanguage = event.target.value;
    if (nextLanguage === state.language) return;

    state.drafts[state.language] = elements.editor.value;
    state.stdinDrafts[state.language] = elements.stdinEditor.value;
    state.language = nextLanguage;
    elements.editor.value = state.drafts[nextLanguage];
    elements.stdinEditor.value = state.stdinDrafts[nextLanguage];
    saveDrafts();
    updateStdinCount();
    renderEditorHighlight();
    resetTraceView();
    showEditor();
    elements.editor.focus();
}

function resetTraceView() {
    stopPlayback();
    state.result = null;
    state.currentStep = 0;
    elements.slider.min = "0";
    elements.slider.max = "0";
    elements.slider.value = "0";
    elements.slider.disabled = true;
    updateTimelineButtons();
    elements.location.textContent = "Not running";
    elements.functionName.textContent = "—";
    elements.stepLabel.textContent = "No trace";
    elements.eventLabel.textContent = "—";
    elements.variables.className = "panel-body empty-state";
    elements.variables.textContent = "Run the program to inspect variables.";
    elements.stdout.innerHTML = '<span class="output-placeholder">Program output appears here.</span>';
    elements.algorithmName.textContent = "Algorithm";
    elements.algorithmConfidence.textContent = "Not analyzed";
    elements.algorithmEvidence.textContent = "Run code to detect its structure";
    elements.algorithmView.className = "algorithm-canvas empty-state";
    elements.algorithmView.textContent = "Run the program to see its data structure drawn here.";
    elements.algorithmInputs.replaceChildren();
    elements.algorithmInputs.hidden = true;
    configureViewSelects();
    setMessage("");
    setStatus("idle", "Ready");
}

function availableViews() {
    return state.result?.algorithm?.views || [];
}

// The picked view, if this trace offers that renderer; otherwise null, which means automatic.
function effectiveView() {
    if (state.view.renderer === "auto") return null;
    const sameRenderer = availableViews().filter((view) => view.renderer === state.view.renderer);
    return sameRenderer.find((view) => view.variable === state.view.variable) || sameRenderer[0] || null;
}

function currentVisualization(step) {
    const view = effectiveView();
    if (!view) return step.visualization;
    return step.views?.[view.id] || {renderer: view.renderer, ready: false};
}

function configureViewSelects() {
    const renderers = [...new Set(availableViews().map((view) => view.renderer))];
    const autoRenderer = state.result?.algorithm?.auto_renderer || state.result?.algorithm?.renderer;
    const autoLabel = autoRenderer ? `Auto (${RENDERER_LABELS[autoRenderer] || autoRenderer})` : "Auto";
    elements.viewSelect.replaceChildren(
        new Option(autoLabel, "auto"),
        ...renderers.map((renderer) => new Option(RENDERER_LABELS[renderer] || renderer, renderer)),
    );
    elements.viewSelect.disabled = !renderers.length;
    updateViewSelects();
}

function updateViewSelects() {
    const view = effectiveView();
    elements.viewSelect.value = view ? view.renderer : "auto";
    const variables = view?.variable
        ? availableViews().filter((item) => item.renderer === view.renderer).map((item) => item.variable)
        : [];
    elements.viewVariableSelect.replaceChildren(...variables.map((name) => new Option(name, name)));
    elements.viewVariableSelect.hidden = !variables.length;
    if (view?.variable) elements.viewVariableSelect.value = view.variable;
}

function chooseView(renderer, variable) {
    state.view = {renderer, variable};
    updateViewSelects();
    if (state.result?.steps.length) renderStep();
}

function renderEditorHighlight() {
    const fragment = document.createDocumentFragment();
    SyntaxHighlighter.appendTokens(fragment, SyntaxHighlighter.tokenize(elements.editor.value, state.language));
    // A trailing newline only gets a line box when something follows it, so the colored layer
    // would be one line shorter than the textarea and drift out of alignment when scrolled.
    fragment.append(" ");
    // Error bands sit behind the text and scroll with it, one per rejected line.
    const lineHeight = parseFloat(getComputedStyle(elements.editorHighlight).lineHeight) || 26;
    const paddingTop = parseFloat(getComputedStyle(elements.editorHighlight).paddingTop) || 0;
    (state.editorErrors || []).forEach((issue) => {
        const band = document.createElement("span");
        band.className = "editor-error-line";
        band.style.top = `${paddingTop + (issue.line - 1) * lineHeight}px`;
        band.style.height = `${lineHeight}px`;
        band.title = issue.message;
        fragment.append(band);
    });
    elements.editorHighlight.replaceChildren(fragment);
    renderEditorGutter();
    syncEditorHighlightScroll();
}

function renderEditorGutter() {
    const value = elements.editor.value;
    const lineCount = value.split("\n").length;
    const caretLine = value.slice(0, elements.editor.selectionStart).split("\n").length;
    const errorLines = new Set((state.editorErrors || []).map((issue) => issue.line));
    const numbers = elements.editorGutter.children;
    while (numbers.length > lineCount) numbers[numbers.length - 1].remove();
    while (numbers.length < lineCount) {
        const number = document.createElement("span");
        number.className = "editor-line-number";
        number.textContent = String(numbers.length + 1);
        elements.editorGutter.append(number);
    }
    [...numbers].forEach((number, index) => {
        number.classList.toggle("current", index + 1 === caretLine);
        number.classList.toggle("error", errorLines.has(index + 1));
    });
    elements.editorGutter.scrollTop = elements.editor.scrollTop;
}

function syncEditorHighlightScroll() {
    elements.editorHighlight.scrollTop = elements.editor.scrollTop;
    elements.editorHighlight.scrollLeft = elements.editor.scrollLeft;
    elements.editorGutter.scrollTop = elements.editor.scrollTop;
}

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

function freezeRowSizes(panels) {
    // Measure every panel before writing any size: each write reflows the column.
    const heights = panels.map((panel) => panel.getBoundingClientRect().height);
    panels.forEach((panel, index) => setRowSize(panel, heights[index]));
}

function setRowSize(panel, height) {
    panel.classList.add("has-row-size");
    panel.style.setProperty("--row-grow", String(Math.round(height)));
}

function moveRowBoundary(resizer, delta) {
    const {above, below, panels} = rowResizeNeighbours(resizer);
    if (!above || !below) return;
    freezeRowSizes(panels);
    const aboveHeight = above.getBoundingClientRect().height;
    const total = aboveHeight + below.getBoundingClientRect().height;
    const minimum = (panel) => ROW_MIN_HEIGHT[panel.dataset.panel] || 80;
    const next = Math.min(Math.max(minimum(above), aboveHeight + delta), total - minimum(below));
    setRowSize(above, next);
    setRowSize(below, total - next);
}

function startRowResize(event) {
    if (event.button !== 0) return;
    const resizer = event.currentTarget;
    resizer.setPointerCapture(event.pointerId);
    resizer.classList.add("is-dragging");
    resizer.dataset.lastY = String(event.clientY);
    document.body.classList.add("is-resizing-rows");
    event.preventDefault();
}

function moveRowResize(event) {
    const resizer = event.currentTarget;
    if (!resizer.hasPointerCapture(event.pointerId)) return;
    moveRowBoundary(resizer, event.clientY - Number(resizer.dataset.lastY));
    resizer.dataset.lastY = String(event.clientY);
}

function finishRowResize(event) {
    const resizer = event.currentTarget;
    if (resizer.hasPointerCapture(event.pointerId)) resizer.releasePointerCapture(event.pointerId);
    resizer.classList.remove("is-dragging");
    document.body.classList.remove("is-resizing-rows");
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
    moveRowBoundary(event.currentTarget, event.key === "ArrowUp" ? -24 : 24);
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
    elements.themeButton.textContent = theme === "dark" ? "Light theme" : "Dark theme";
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
    button.textContent = expanded ? "Hide" : "Show";
    button.setAttribute("aria-expanded", String(expanded));

    const columnCollapsed = (column) => [...column.querySelectorAll("[data-panel]")]
        .every((item) => item.classList.contains("is-collapsed"));
    elements.workspace.classList.toggle("left-collapsed", columnCollapsed(elements.leftColumn));
    elements.workspace.classList.toggle("right-collapsed", columnCollapsed(elements.rightColumn));
    updateRowResizers();
}

function restorePlaybackSpeed() {
    const speed = Number(readPreference("speed", 1));
    setPlaybackSpeed(PLAYBACK_SPEEDS.includes(speed) ? speed : 1, false);
}

function setPlaybackSpeed(speed, persist = true) {
    state.playback.speed = speed;
    elements.speedSelect.value = String(speed);
    if (persist) writePreference("speed", speed);
}

function togglePlayback() {
    if (state.playback.timer) stopPlayback();
    else startPlayback();
}

function startPlayback() {
    if (!state.result?.steps.length) return;
    if (state.currentStep >= state.result.steps.length - 1) goToStep(0);
    scheduleNextPlaybackStep();
    updatePlayButton();
}

function scheduleNextPlaybackStep() {
    // Each tick reads the current speed, so changing it mid-playback applies on the next step.
    const delay = 1000 / (PLAYBACK_STEPS_PER_SECOND * state.playback.speed);
    state.playback.timer = window.setTimeout(() => {
        goToStep(state.currentStep + 1);
        if (state.currentStep >= state.result.steps.length - 1) stopPlayback();
        else scheduleNextPlaybackStep();
    }, delay);
}

function stopPlayback() {
    window.clearTimeout(state.playback.timer);
    state.playback.timer = null;
    updatePlayButton();
}

function updatePlayButton() {
    const playing = Boolean(state.playback.timer);
    elements.playButton.setAttribute("aria-pressed", String(playing));
    elements.playButton.querySelector(".play-icon").textContent = playing ? "❚❚" : "▶";
    elements.playButton.querySelector(".play-label").textContent = playing ? "Pause" : "Play";
}

function stepManually(index) {
    stopPlayback();
    goToStep(index);
}

async function runCode() {
    const code = elements.editor.value;
    const stdin = elements.stdinEditor.value;
    stopPlayback();
    setMessage("");
    setEditorErrors([]);
    setStatus("running", "Running");
    elements.runButton.disabled = true;
    elements.languageSelect.disabled = true;

    try {
        const response = await fetch("/api/debug", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({code, stdin, language: state.language}),
        });
        const payload = await response.json();
        if (!response.ok) {
            // Syntax and compile errors cannot run, so point at the rejected lines in the editor.
            // The previous run's trace no longer matches this code, so clear it.
            resetTraceView();
            if (payload?.detail?.issues?.length) {
                showEditor();
                setEditorErrors(payload.detail.issues);
            }
            throw new Error(apiErrorMessage(payload));
        }

        state.result = payload;
        state.currentStep = payload.status === "completed" ? 0 : Math.max(0, payload.steps.length - 1);
        state.algorithmGraphPositions.clear();
        state.recursionPositions.clear();
        state.callChainPositions.clear();
        indexObjects(payload.steps);
        renderAlgorithmProfile(payload.algorithm);
        configureViewSelects();
        showViewer();
        configureTimeline();

        if (payload.steps.length > 0) {
            renderStep();
        } else {
            renderEmptyTrace();
        }

        if (payload.status === "completed") {
            setStatus("success", `${payload.steps.length} steps`);
        } else if (payload.status === "exception") {
            setStatus("error", payload.error?.type || "Exception");
        } else if (payload.status === "timeout") {
            setStatus("error", "TLE · trace saved");
        } else {
            setStatus("error", "TLE · step limit");
        }
    } catch (error) {
        setStatus("error", "Cannot run");
        setMessage(error instanceof Error ? error.message : String(error));
    } finally {
        elements.runButton.disabled = false;
        elements.languageSelect.disabled = false;
    }
}

function updateStdinCount() {
    const length = elements.stdinEditor.value.length;
    elements.stdinCount.textContent = `${length} char${length === 1 ? "" : "s"}`;
}

function apiErrorMessage(payload) {
    const detail = payload?.detail;
    if (typeof detail === "string") return detail;
    if (detail?.issues?.length) {
        const lines = detail.issues.map((issue) => {
            const location = issue.line ? `Line ${issue.line}: ` : "";
            return `${location}${issue.message}`;
        });
        return [detail.message, ...lines].filter(Boolean).join("\n");
    }
    if (Array.isArray(detail)) {
        return detail.map((item) => item.msg).join("\n");
    }
    return "The debugger could not run this program.";
}

function setStatus(kind, text) {
    elements.status.className = `status-pill ${kind}`;
    elements.status.innerHTML = '<span class="status-dot"></span>';
    elements.status.append(document.createTextNode(text));
}

function setMessage(text, kind = "error") {
    elements.message.textContent = text;
    elements.message.classList.toggle("hidden", !text);
    elements.message.classList.toggle("is-tle", kind === "tle");
}

// Lines the compiler or syntax check rejected; drawn in the editor until the code changes.
function setEditorErrors(issues) {
    state.editorErrors = (issues || []).filter((issue) => Number.isInteger(issue.line));
    renderEditorHighlight();
}

function showViewer() {
    elements.editorWrap.classList.add("hidden");
    elements.sourceViewer.classList.remove("hidden");
    elements.editButton.classList.remove("hidden");
}

function showEditor() {
    stopPlayback();
    elements.sourceViewer.classList.add("hidden");
    elements.editorWrap.classList.remove("hidden");
    elements.editButton.classList.add("hidden");
    elements.editor.focus();
}

function configureTimeline() {
    const lastIndex = Math.max(0, state.result.steps.length - 1);
    elements.slider.max = String(lastIndex);
    elements.slider.value = String(state.currentStep);
    elements.slider.disabled = state.result.steps.length === 0;
    updateTimelineButtons();
}

function goToStep(index) {
    if (!state.result?.steps.length) return;
    const pageScrollX = window.scrollX;
    const pageScrollY = window.scrollY;
    state.currentStep = Math.max(0, Math.min(index, state.result.steps.length - 1));
    renderStep();
    requestAnimationFrame(() => window.scrollTo(pageScrollX, pageScrollY));
}

function renderStep() {
    const step = state.result.steps[state.currentStep];
    const visualization = currentVisualization(step);
    renderSource(step.line, lineProblem(step));
    renderVariables(step, visualization);
    renderInputs(step, visualization);
    renderOutput(step.stdout);
    renderRuntimeMessage(step);
    renderAlgorithm(visualization);

    elements.location.textContent = `Line ${step.line}`;
    elements.functionName.textContent = step.function;
    elements.stepLabel.textContent = `Step ${state.currentStep + 1} / ${state.result.steps.length}`;
    elements.eventLabel.textContent = step.event;
    elements.slider.value = String(state.currentStep);
    updateTimelineButtons();
}

function updateTimelineButtons() {
    const hasSteps = Boolean(state.result?.steps.length);
    const atStart = state.currentStep === 0;
    const atEnd = !hasSteps || state.currentStep === state.result.steps.length - 1;
    const loop = hasSteps ? state.result.steps[state.currentStep]?.loop : null;
    // Outside every loop both loop buttons are unavailable.
    elements.loopStartButton.disabled = loop?.before == null;
    elements.previousButton.disabled = !hasSteps || atStart;
    elements.nextButton.disabled = !hasSteps || atEnd;
    elements.loopEndButton.disabled = loop?.after == null || loop.after === state.currentStep;
    elements.playButton.disabled = !hasSteps;
}

function jumpOutOfLoop(direction) {
    const target = state.result?.steps[state.currentStep]?.loop?.[direction];
    if (target != null) stepManually(target);
}

// "error" for a runtime error (RE), "timeout" where a TLE or the step limit stopped the run.
function lineProblem(step) {
    if (step.event === "exception") return "error";
    if (step.event === "stopped") return "timeout";
    return null;
}

function renderSource(currentLine, problem = null) {
    const lines = state.result.source.split("\n");
    const lineTokens = SyntaxHighlighter.lines(state.result.source, state.result.language);
    elements.sourceViewer.replaceChildren();
    lines.forEach((code, index) => {
        const line = document.createElement("div");
        line.className = "source-line";
        if (index + 1 === currentLine) line.classList.add("current");
        if (index + 1 === currentLine && problem) line.classList.add(problem);

        const number = document.createElement("span");
        number.className = "line-number";
        number.textContent = String(index + 1);
        const content = document.createElement("span");
        content.className = "line-code";
        // Indentation stays outside `.line-text` so the current-line mark covers only the code.
        const indent = code.match(/^\s*/)[0];
        const text = document.createElement("span");
        text.className = "line-text";
        const tokens = SyntaxHighlighter.skipCharacters(lineTokens[index] || [], indent.length);
        if (tokens.length) SyntaxHighlighter.appendTokens(text, tokens);
        else text.textContent = " ";
        content.append(indent, text);
        line.append(number, content);
        elements.sourceViewer.append(line);
    });

    requestAnimationFrame(() => scrollCurrentSourceLine());
}

function scrollCurrentSourceLine() {
    const currentLine = elements.sourceViewer.querySelector(".source-line.current");
    if (!currentLine) return;

    const viewerRect = elements.sourceViewer.getBoundingClientRect();
    const lineRect = currentLine.getBoundingClientRect();
    const lineTop = elements.sourceViewer.scrollTop + lineRect.top - viewerRect.top;
    const lineBottom = lineTop + lineRect.height;
    const visibleTop = elements.sourceViewer.scrollTop + 32;
    const visibleBottom = elements.sourceViewer.scrollTop + elements.sourceViewer.clientHeight - 32;

    if (lineTop >= visibleTop && lineBottom <= visibleBottom) return;
    const target = lineTop - elements.sourceViewer.clientHeight / 2 + lineRect.height / 2;
    elements.sourceViewer.scrollTo({top: Math.max(0, target), behavior: "smooth"});
}

// Values read from stdin and never changed (`n`, `m`) are shown once beside the visualization,
// so Variables hides them, also before they are read (C++ would show garbage there).
function inputNames(step) {
    if (elements.algorithmPanel.classList.contains("is-collapsed")) return [];
    return (step.inputs || []).map((entry) => entry.name);
}

function renderInputs(step, visualization) {
    const drawn = new Set((visualization?.uses || []).map(String));
    const read = (step.inputs || []).filter((entry) => entry.read && !drawn.has(entry.name));
    const onLine = new Set(step.usage?.line || []);
    elements.algorithmInputs.replaceChildren(...read.map((entry) => {
        const item = textSpan(`${entry.name} = ${entry.value}`, "algorithm-readout");
        item.classList.toggle("is-on-line", onLine.has(entry.name));
        return item;
    }));
    elements.algorithmInputs.hidden = !read.length;
}

function renderVariables(step, visualization) {
    const onLine = new Set(step.usage?.line || []);
    const changed = new Set(step.usage?.changed || []);
    // What the highlighted line is about to do: the value it will leave, the entries it will write.
    const upcoming = step.usage?.next || {};
    const upcomingCells = step.usage?.cells || {};
    const hidden = new Set([...(visualization?.uses || []).map(String), ...inputNames(step)]);
    const entries = variableEntries(step.locals || {}, step.globals || {}, hidden);
    elements.variables.replaceChildren();
    elements.variables.className = "panel-body";
    if (!entries.length) {
        elements.variables.classList.add("empty-state");
        elements.variables.textContent = hidden.size
            ? "Every variable at this step is drawn in the algorithm view."
            : "No variables at this step.";
        return;
    }

    // Single values are rows on the left; containers sit beside them on the right, so neither
    // pushes the other out of view. Both keep the order the variables first appeared in.
    const zones = document.createElement("div");
    zones.className = "variable-zones";
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
        card.className = isScalar ? "scalar-row" : "variable-card";
        // Yellow: used by the line about to run. Orange: changed by the line that just ran.
        card.classList.toggle("is-on-line", onLine.has(name));
        card.classList.toggle("is-changed", changed.has(name));
        const nameNode = textSpan(name, "variable-label");
        const hint = isScalar ? "" : CONTAINER_HINTS[value?.class_name] || "";
        const type = textSpan(
            [!isScalar && isGlobal ? "global" : "", displayType(value), hint].filter(Boolean).join(" · "),
            "type-tag",
        );
        const content = document.createElement("div");
        content.className = "value-view";
        if (isScalar && Object.hasOwn(upcoming, name)) {
            // On the line that changes it: `7 -> 10`, the value now and the one it will have.
            const before = renderValue(value, 0);
            before.classList.add("change-before");
            content.append(before, textSpan("->", "change-arrow"), renderValue(upcoming[name], 0));
        } else {
            content.append(renderValue(value, 0, upcomingCells[name]));
        }
        if (isScalar) {
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
        return textSpan(`↪ ${objectLabel(value.object_id)}`, "reference-value");
    }
    if (value.type === "str") {
        return textSpan(JSON.stringify(value.value) + truncatedSuffix(value), "primitive str");
    }
    if (["int", "float"].includes(value.type)) {
        return textSpan(String(value.value), "primitive number");
    }
    if (value.type === "bool") {
        return textSpan(value.value ? "True" : "False", "primitive bool");
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
        if (items.length) wrapper.append(array);
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
            key.textContent = compactValue(entry.key);
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

function compactValue(value, depth = 0) {
    if (!value) return "—";
    if (value.type === "reference") return `↪ ${objectLabel(value.object_id)}`;
    if (value.type === "str") return JSON.stringify(value.value.length > 18 ? `${value.value.slice(0, 18)}…` : value.value);
    if (value.type === "none") return "None";
    if (["int", "float"].includes(value.type)) return String(value.value);
    if (value.type === "bool") return value.value ? "True" : "False";
    if (depth > 0 && containerTypes.has(value.type)) return objectLabel(value.object_id);
    if (["list", "tuple", "set", "frozenset"].includes(value.type)) {
        const brackets = value.type === "tuple" ? ["(", ")"] : value.type === "list" ? ["[", "]"] : ["{", "}"];
        const items = (value.items || []).slice(0, 4).map((item) => compactValue(item, depth + 1));
        if ((value.items || []).length > 4 || value.truncated) items.push("…");
        return `${brackets[0]}${items.join(", ")}${brackets[1]}`;
    }
    if (value.type === "dict") {
        const items = (value.entries || []).slice(0, 3).map((entry) => `${compactValue(entry.key, 1)}: ${compactValue(entry.value, 1)}`);
        if ((value.entries || []).length > 3 || value.truncated) items.push("…");
        return `{${items.join(", ")}}`;
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

function titleCase(value) {
    const text = String(value || "object");
    return text.charAt(0).toUpperCase() + text.slice(1);
}

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

function renderOutput(stdout) {
    elements.stdout.replaceChildren();
    if (stdout) {
        elements.stdout.textContent = stdout;
        // The panel shows three lines, so keep the newest output in view.
        elements.stdout.scrollTop = elements.stdout.scrollHeight;
    } else {
        const placeholder = document.createElement("span");
        placeholder.className = "output-placeholder";
        placeholder.textContent = "No output yet.";
        elements.stdout.append(placeholder);
    }
}

function renderRuntimeMessage(step) {
    if (!step.exception) {
        setMessage("");
        return;
    }
    const {type, message} = step.exception;
    if (lineProblem(step) === "timeout") {
        const reason = type === "StepLimitExceeded"
            ? "the program was stopped after the step limit"
            : message || "the program ran too long";
        setMessage(`TLE at line ${step.line}: ${reason}. This is where it was running when it stopped.`, "tle");
        return;
    }
    // A Python exception that unwound through callers names the line that raised it.
    const origin = step.exception.origin;
    const raised = origin ? ` (raised at line ${origin.line} in ${origin.function})` : "";
    setMessage(`RE at line ${step.line}: ${type}: ${message || "No message"}${raised}`);
}

function renderAlgorithmProfile(profile) {
    const algorithm = profile || {
        name: "General Python execution",
        confidence: 0,
        evidence: [],
    };
    const percent = Math.round((algorithm.confidence || 0) * 100);
    elements.algorithmName.textContent = algorithm.name;
    elements.algorithmConfidence.textContent = `${percent}% heuristic match`;
    elements.algorithmConfidence.className = "confidence-badge";
    if (percent >= 80) elements.algorithmConfidence.classList.add("high");
    else if (percent >= 60) elements.algorithmConfidence.classList.add("medium");
    elements.algorithmEvidence.textContent = (algorithm.evidence || []).join(", ") || "No specialized pattern matched";
}

function renderAlgorithm(visualization) {
    elements.algorithmView.replaceChildren();
    elements.algorithmView.className = "algorithm-canvas";
    if (!visualization) {
        renderAlgorithmWaiting("No visualization state is available for this step.");
        return;
    }
    const renderers = {
        grid: renderGridAlgorithm,
        array: renderArrayAlgorithm,
        cells: renderCellsAlgorithm,
        graph: renderGraphAlgorithm,
        recursion_tree: renderRecursionTreeAlgorithm,
        call_tree: renderCallTreeAlgorithm,
        execution: renderExecutionAlgorithm,
    };
    (renderers[visualization.renderer] || renderExecutionAlgorithm)(visualization);
}

function renderAlgorithmWaiting(message) {
    const waiting = document.createElement("div");
    waiting.className = "algorithm-waiting";
    waiting.textContent = message;
    elements.algorithmView.append(waiting);
}

function renderGridAlgorithm(view) {
    if (!view.ready) {
        renderAlgorithmWaiting("Waiting for the program to construct its 2D state…");
        return;
    }
    const rows = view.rows || [];
    const columns = Math.max(0, ...rows.map((row) => row.length));
    const meta = document.createElement("div");
    meta.className = "algorithm-meta";
    const dimensions = document.createElement("span");
    dimensions.textContent = `${view.name || "grid"}, ${rows.length} × ${columns}${view.truncated ? ", clipped" : ""}${view.carried ? ", last known state" : ""}`;
    meta.append(dimensions, algorithmLegend([
        ["visited", "Visited"],
        ["frontier", "Frontier"],
        ["active", "Current"],
        ["written", "Written"],
        ["wall", "Blocked"],
    ]));
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
            if (walls.has(key) || String(value) === "#") cell.classList.add("wall");
            if (visited.has(key)) cell.classList.add("visited");
            if (frontier.has(key)) cell.classList.add("frontier");
            if (active.has(key)) cell.classList.add(active.get(key));
            if (written.has(key)) cell.classList.add("written");
            cell.textContent = gridCellText(value);
            cell.title = `row ${rowIndex}, column ${columnIndex}: ${value === "\0" ? "unset" : String(value)}`;
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
        text.textContent = label;
        item.append(swatch, text);
        legend.append(item);
    });
    return legend;
}

function renderArrayAlgorithm(view) {
    if (!view.ready) {
        renderAlgorithmWaiting("Waiting for a numeric sequence to appear…");
        return;
    }
    const values = view.values || [];
    const numericValues = values.map(Number);
    const maxMagnitude = Math.max(1, ...numericValues.map((value) => Math.abs(value)));
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
    // Value label, index label, marker row, and the gaps between them.
    const labelSpace = 64;
    const columnWidth = Math.max(26, Math.min(72, Math.floor(
        (area.width - chartPadding.x - columnGap * (values.length - 1)) / Math.max(1, values.length),
    )));
    const maxBarHeight = Math.max(80, area.height - chartPadding.y - labelSpace);

    const chart = document.createElement("div");
    chart.className = "array-visualizer";
    chart.style.setProperty("--column", `${columnWidth}px`);
    values.forEach((value, index) => {
        const column = document.createElement("div");
        column.className = "array-column";
        const indexMarkers = markers.get(index) || [];
        indexMarkers.forEach((marker) => column.classList.add(marker.role));
        // Marked indexes (for example the fixed `i` in three-sum) stay visible outside the window.
        if (interval && !indexMarkers.length && (index < interval.low || index > interval.high)) {
            column.classList.add("outside-bound");
        }
        if (written.has(index)) column.classList.add("written");
        const label = document.createElement("span");
        label.className = "array-value";
        label.textContent = String(value);
        const bar = document.createElement("div");
        bar.className = "array-bar";
        bar.style.height = `${8 + (Math.abs(Number(value)) / maxMagnitude) * (maxBarHeight - 8)}px`;
        const indexNode = document.createElement("span");
        indexNode.className = "array-index";
        const itemLabel = view.labels?.[index];
        indexNode.textContent = itemLabel === undefined || itemLabel === null
            ? String(index)
            : `#${itemLabel}`;
        if (itemLabel !== undefined && itemLabel !== null) {
            indexNode.title = `sorted position ${index} · original index ${itemLabel}`;
        }
        column.append(label, bar, indexNode);
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
    summary.textContent = `${view.name || "array"}, ${count} items${view.truncated ? ", clipped" : ""}${view.carried ? ", last known state" : ""}`;
    const details = document.createElement("div");
    details.className = "algorithm-meta-details";
    details.append(algorithmLegend([
        ["active", "Reading"],
        ["written", "Written"],
    ]));
    if (view.readouts?.length) {
        const readouts = document.createElement("div");
        readouts.className = "algorithm-readouts";
        view.readouts.forEach((readout) => {
            const item = document.createElement("span");
            item.className = "algorithm-readout";
            item.textContent = `${readout.label} = ${readout.value}`;
            readouts.append(item);
        });
        details.append(readouts);
    }
    meta.append(summary, details);
    return meta;
}

function renderCellsAlgorithm(view) {
    if (!view.ready) {
        renderAlgorithmWaiting("Waiting for this list to appear…");
        return;
    }
    const values = view.values || [];
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
        const indexMarkers = markers.get(index) || [];
        indexMarkers.forEach((marker) => item.classList.add(marker.role));
        if (interval && !indexMarkers.length && (index < interval.low || index > interval.high)) {
            item.classList.add("outside-bound");
        }
        if (written.has(index)) item.classList.add("written");
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

function renderGraphAlgorithm(view) {
    if (!view.ready) {
        renderAlgorithmWaiting("Waiting for an adjacency structure to appear…");
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
        const front = view.frontier.items.length ? view.frontier.items.join("  ") : "empty";
        summary.textContent = `${view.frontier.name}: ${front}`;
    } else if (forest) {
        summary.textContent = `${view.name}[v]: each arrow points to the parent; roots are on top`;
    } else {
        summary.textContent = `${view.name || "graph"}, ${nodes.length} vertices`;
    }
    const legend = forest ? [["active", "Current"]] : [["active", "Current"], ["visited", "Visited"]];
    if (view.checking) legend.push(["checking", "Edge being checked"]);
    if (view.frontier) legend.push(["frontier", `In ${view.frontier.name}`]);
    meta.append(summary, algorithmLegend(legend));
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
    if (view.directed) {
        const defs = svgElement("defs");
        const marker = svgElement("marker", {
            id: "graph-arrow", viewBox: "0 0 10 10", refX: "10", refY: "5",
            markerWidth: "7", markerHeight: "7", orient: "auto-start-reverse",
        });
        marker.append(svgElement("path", {class: "algorithm-graph-arrow", d: "M 0 0 L 10 5 L 0 10 z"}));
        defs.append(marker);
        svg.append(defs);
    }
    // Directed edges stop at the target's rim so the arrowhead stays visible.
    const placeEdge = (line, source, target) => {
        const dx = target.x - source.x;
        const dy = target.y - source.y;
        const length = Math.hypot(dx, dy) || 1;
        const inset = view.directed ? nodeRadius + 3 : 0;
        line.setAttribute("x1", source.x);
        line.setAttribute("y1", source.y);
        line.setAttribute("x2", target.x - (dx / length) * inset);
        line.setAttribute("y2", target.y - (dy / length) * inset);
    };
    // A weight sits beside the middle of its edge, pushed off the line so both stay readable.
    const placeWeight = (text, source, target) => {
        const dx = target.x - source.x;
        const dy = target.y - source.y;
        const length = Math.hypot(dx, dy) || 1;
        text.setAttribute("x", (source.x + target.x) / 2 - (dy / length) * 9);
        text.setAttribute("y", (source.y + target.y) / 2 + (dx / length) * 9);
    };
    const edgeElements = [];
    (view.edges || []).forEach((edge) => {
        const source = positions.get(String(edge.source));
        const target = positions.get(String(edge.target));
        if (!source || !target) return;
        const line = svgElement("line", {class: "algorithm-graph-edge"});
        // The edge from the current vertex to the neighbour the code is looking at.
        const checked = view.checking && [edge.source, edge.target].map(String).sort().join(" ")
            === [view.checking.source, view.checking.target].map(String).sort().join(" ");
        if (checked) line.classList.add("checking");
        if (view.directed) line.setAttribute("marker-end", "url(#graph-arrow)");
        placeEdge(line, source, target);
        svg.append(line);
        let weight = null;
        if (edge.weight !== undefined && edge.weight !== null) {
            weight = svgElement("text", {class: "algorithm-graph-weight"});
            weight.textContent = String(edge.weight);
            placeWeight(weight, source, target);
            svg.append(weight);
        }
        edgeElements.push({edge, line, weight});
    });
    const nodeElements = new Map();
    nodes.forEach((node) => {
        const nodeId = String(node);
        const position = positions.get(nodeId);
        const classes = ["algorithm-graph-node"];
        if (visited.has(String(node))) classes.push("visited");
        if (String(view.current) === String(node)) classes.push("current");
        if (queued.has(nodeId)) classes.push("queued");
        const group = svgElement("g", {class: classes.join(" "), transform: `translate(${position.x} ${position.y})`});
        if (queued.has(nodeId)) group.append(svgElement("circle", {class: "queue-ring", r: String(nodeRadius + 5)}));
        group.append(svgElement("circle", {r: String(nodeRadius)}));
        const label = svgElement("text");
        label.textContent = String(node);
        group.append(label);
        if (Object.hasOwn(labels, nodeId)) {
            // A per-vertex value such as dis[v], written beside the vertex.
            const value = svgElement("text", {class: "node-value", x: String(nodeRadius + 6), y: String(-nodeRadius + 6)});
            value.textContent = `${view.labels.name}=${labels[nodeId]}`;
            group.append(value);
        }
        svg.append(group);
        nodeElements.set(nodeId, group);
    });
    const updateEdges = () => {
        edgeElements.forEach(({edge, line, weight}) => {
            const source = positions.get(String(edge.source));
            const target = positions.get(String(edge.target));
            if (!source || !target) return;
            placeEdge(line, source, target);
            if (weight) placeWeight(weight, source, target);
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
    nodes.forEach((node) => {
        if (node.parent === null || node.parent === undefined) roots.push(node);
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

function renderRecursionTreeAlgorithm(view) {
    const tree = state.result?.algorithm?.recursion_tree;
    const step = state.currentStep;
    const nodes = (tree?.nodes || []);
    const visible = nodes.filter((node) => node.start_step <= step);
    if (!visible.length) {
        renderAlgorithmWaiting("Waiting for the first function call…");
        return;
    }
    if (!tree.layout) tree.layout = layoutRecursionTree(nodes);
    const {nodeWidth, width, height} = tree.layout;
    const nodeHeight = RECURSION_NODE.height;
    const onStack = new Set();
    for (let id = view.current; id !== null && id !== undefined; id = nodes[id].parent) onStack.add(id);

    const meta = document.createElement("div");
    meta.className = "algorithm-meta is-sticky";
    const summary = document.createElement("span");
    summary.textContent = `${visible.length} of ${nodes.length} calls${tree.truncated ? ", first 400 shown" : ""}`;
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
        const base = state.recursionPositions.get(node.id) || tree.layout.positions.get(node.id);
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
        renderAlgorithmWaiting("Waiting for a function call…");
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

function renderEmptyTrace() {
    renderSource(0);
    elements.location.textContent = "Finished";
    elements.functionName.textContent = "—";
    elements.stepLabel.textContent = "No trace events";
    elements.eventLabel.textContent = "—";
    elements.variables.className = "panel-body empty-state";
    elements.variables.textContent = "This program produced no trace events.";
    renderOutput("");
    elements.algorithmView.replaceChildren();
    elements.algorithmView.className = "algorithm-canvas";
    renderAlgorithmWaiting("This program produced no visualization steps.");
}
