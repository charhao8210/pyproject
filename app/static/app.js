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
    // Edge direction for graph views: "auto" (the trace's guess), "directed" or "undirected".
    graphDirection: "auto",
    // The run the trace came from, and views asked for beyond the precomputed ones.
    lastRun: null,
    extraViews: [],
    loadingView: null,
    bindings: {},
    focus: true,
    follow: true,
    stepMode: "line",
    eventIndexes: {},
    examples: [],
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
    segment_tree: "Segment tree",
    recursion_tree: "Recursion tree",
    call_tree: "Call chain",
    execution: "Current line",
    heap: "Heap / Priority queue",
    window: "Sliding window",
    monotonic: "Monotonic stack / deque",
    fenwick: "Fenwick / BIT",
    string_match: "String matching / KMP",
    trie: "Trie",
};

const COMPACT_RENDERER_LABELS = {
    grid: "表格", array: "長條圖", cells: "格子", graph: "圖",
    dsu: "並查集", segment_tree: "線段樹", recursion_tree: "遞迴樹",
    call_tree: "呼叫鏈", execution: "執行", heap: "堆積", window: "滑動視窗",
    monotonic: "單調堆疊", fenwick: "Fenwick", string_match: "字串比對", trie: "Trie",
};

// At 1× speed, autoplay advances this many steps per second.
const PLAYBACK_STEPS_PER_SECOND = 2;
const PLAYBACK_SPEEDS = [0.25, 0.5, 1, 1.5, 1.75, 2];

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
    workspaceResizer: document.querySelector("#workspace-resizer"),
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
    algorithmDetectedName: document.querySelector("#algorithm-detected-name"),
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
    focusToggle: document.querySelector("#focus-toggle"),
    followToggle: document.querySelector("#follow-toggle"),
    visualSettings: document.querySelector("#visual-settings"),
    visualScaleInfo: document.querySelector("#visual-scale-info"),
    bindingMode: document.querySelector("#binding-mode"),
    bindingFields: document.querySelector("#binding-fields"),
    bindingOptions: document.querySelector("#binding-options"),
    applyBindings: document.querySelector("#apply-bindings"),
    stepMode: document.querySelector("#step-mode"),
    callEndButton: document.querySelector("#call-end-button"),
    exampleSelect: document.querySelector("#example-select"),
    captureItems: document.querySelector("#capture-items"),
    captureDepth: document.querySelector("#capture-depth"),
};

elements.runButton.addEventListener("click", runCode);
elements.editButton.addEventListener("click", showEditor);
elements.languageSelect.addEventListener("change", changeLanguage);
elements.languageSelect.addEventListener("change", () => { elements.exampleSelect.value = ""; });
elements.themeButton.addEventListener("click", () => setTheme(currentTheme() === "dark" ? "light" : "dark"));
elements.viewSelect.addEventListener("change", (event) => chooseView(event.target.value, null));
elements.viewVariableSelect.addEventListener("change", (event) => chooseView(state.view.renderer, event.target.value));
elements.playButton.addEventListener("click", togglePlayback);
elements.speedSelect.addEventListener("change", (event) => setPlaybackSpeed(Number(event.target.value)));
// Skip the innermost loop around the current line (`step.loop` comes from the backend).
elements.loopStartButton.addEventListener("click", () => jumpOutOfLoop("before"));
elements.previousButton.addEventListener("click", () => stepManually(navigationTarget(-1)));
elements.nextButton.addEventListener("click", () => stepManually(navigationTarget(1)));
elements.loopEndButton.addEventListener("click", () => jumpOutOfLoop("after"));
elements.slider.addEventListener("input", (event) => stepManually(Number(event.target.value)));
elements.focusToggle.addEventListener("change", () => {
    state.focus = elements.focusToggle.checked;
    writePreference("focus", state.focus);
    if (state.result?.steps.length) renderStep();
});
elements.followToggle.addEventListener("change", () => {
    state.follow = elements.followToggle.checked;
    writePreference("follow", state.follow);
    if (state.result?.steps.length) renderStep();
});
elements.stepMode.addEventListener("change", () => {
    state.stepMode = elements.stepMode.value;
    writePreference("step-mode", state.stepMode);
    updateTimelineButtons();
});
elements.bindingMode.addEventListener("change", configureBindings);
elements.applyBindings.addEventListener("click", () => {
    state.bindings = {mode: elements.bindingMode.value};
    elements.bindingFields.querySelectorAll("select").forEach((select) => {
        if (select.value) state.bindings[select.dataset.role] = select.value;
    });
    elements.bindingOptions.querySelectorAll("select").forEach((select) => {
        if (select.value) state.bindings[select.dataset.role] = select.value;
    });
    runCode();
});
elements.callEndButton.addEventListener("click", () => {
    const target = currentCallEnd();
    if (target !== null) stepManually(target);
});
elements.exampleSelect.addEventListener("change", () => {
    const example = state.examples.find((item) => item.id === elements.exampleSelect.value);
    if (!example) return;
    stopPlayback();
    if (example.language !== state.language) changeLanguage({target: {value: example.language}});
    resetTraceView();
    elements.editor.value = example.code;
    elements.stdinEditor.value = example.stdin || "";
    state.bindings = {};
    elements.bindingMode.value = "auto";
    state.view = {renderer: "auto", variable: null};
    showEditor();
    renderEditorHighlight();
    updateStdinCount();
    saveDrafts();
});
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
    elements.exampleSelect.value = "";
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
elements.workspaceResizer.addEventListener("pointerdown", startWorkspaceResize);
elements.workspaceResizer.addEventListener("pointermove", moveWorkspaceResize);
elements.workspaceResizer.addEventListener("pointerup", finishRowResize);
elements.workspaceResizer.addEventListener("pointercancel", finishRowResize);
elements.workspaceResizer.addEventListener("dblclick", () => setWorkspaceHeight(null));
elements.workspaceResizer.addEventListener("keydown", resizeWorkspaceWithKeyboard);

document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && elements.visualSettings.open) {
        event.preventDefault();
        elements.visualSettings.open = false;
        elements.visualSettings.querySelector(":scope > summary").focus();
        return;
    }
    if (!state.result || [elements.editor, elements.stdinEditor].includes(document.activeElement)) return;
    if (event.target.closest("select, input, textarea, summary, a, [role=button], [contenteditable=true]")) return;
    if (event.key === "ArrowLeft") {
        event.preventDefault();
        stepManually(navigationTarget(-1));
    } else if (event.key === "ArrowRight") {
        event.preventDefault();
        stepManually(navigationTarget(1));
    } else if (event.key === " " && !event.target.closest("button, select, input")) {
        event.preventDefault();
        togglePlayback();
    }
});

document.addEventListener("pointerdown", (event) => {
    if (elements.visualSettings.open && !elements.visualSettings.contains(event.target)) {
        elements.visualSettings.open = false;
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
        scrollCurrentSourceLine();
    });
});
panelResizeObserver.observe(elements.algorithmPanel);
panelResizeObserver.observe(elements.sourceViewer);

updateStdinCount();
renderEditorHighlight();
setTheme(currentTheme(), false);
restorePlaybackSpeed();
setupPanelToggles();
setupPanelZooms();
state.drafts.python = elements.editor.value;
state.stdinDrafts.python = elements.stdinEditor.value;
restoreDrafts();
state.focus = readPreference("focus", true) !== false;
state.follow = readPreference("follow", true) !== false;
elements.focusToggle.checked = state.focus;
elements.followToggle.checked = state.follow;
const savedStepMode = readPreference("step-mode", "line");
state.stepMode = ["line", "event", "call", "return", "change"].includes(savedStepMode) ? savedStepMode : "line";
elements.stepMode.value = state.stepMode;
loadExamples();

const BINDING_ROLES = {
    primary: "主要資料", left: "左界", right: "右界", total: "總和 / 統計",
    frontier: "佇列 / 優先佇列", distance: "距離 / 層次", indegree: "入度", output: "拓樸輸出", parent: "父節點", lazy: "Lazy tag",
    index: "目前索引 / 節點", row: "列索引", column: "欄索引", stack: "Stack / deque",
    text: "文字", pattern: "模式字串", prefix: "Prefix table", query_left: "查詢左界", query_right: "查詢右界",
    pivot: "Pivot 值 / 索引", temporary: "Merge 暫存資料",
};
configureBindings();

function configureBindings() {
    const mode = elements.bindingMode.value;
    const roleSets = {
        auto: [], dp: ["primary", "row", "column", "index"],
        graph: ["primary", "index", "frontier", "distance", "indegree", "output", "parent"],
        sorting: ["primary", "left", "right", "index", "pivot", "temporary"], dsu: ["primary", "index", "parent"],
        segment_tree: ["primary", "index", "lazy", "query_left", "query_right"],
        heap: ["primary", "index"], window: ["primary", "left", "right", "total"],
        monotonic: ["primary", "stack", "index"], fenwick: ["primary", "index", "total"],
        string_match: ["text", "pattern", "prefix", "index", "column"], trie: ["primary", "text", "index"],
    };
    const labels = BINDING_ROLES;
    const variables = state.result?.algorithm?.variables || [];
    elements.bindingFields.replaceChildren(...(roleSets[mode] || ["primary"]).map((role) => {
        const label = document.createElement("label");
        const roleLabel = mode === "string_match" && role === "column" ? "模式字串索引 j" : labels[role] || "主要資料";
        label.append(roleLabel);
        const select = document.createElement("select");
        select.dataset.role = role;
        select.setAttribute("aria-label", roleLabel);
        select.replaceChildren(new Option("自動", ""), ...variables.map((name) => new Option(name, name)));
        select.value = state.bindings[role] || "";
        label.append(select);
        return label;
    }));
    const options = mode === "heap" ? [{role: "heap_order", label: "Heap 順序", values: [["", "自動辨識"], ["min", "Min heap"], ["max", "Max heap"]]}]
        : ["window", "sorting"].includes(mode) ? [{role: "right_exclusive", label: "右界定義", values: [["", "自動辨識 / 尚未指定"], ["false", "包含右界 [l, r]"], ["true", "不包含右界 [l, r)"]]}] : [];
    elements.bindingOptions.replaceChildren(...options.map((option) => {
        const label = document.createElement("label");
        label.append(option.label);
        const select = document.createElement("select");
        select.dataset.role = option.role;
        select.setAttribute("aria-label", option.label);
        select.replaceChildren(...option.values.map(([value, text]) => new Option(text, value)));
        select.value = state.bindings[option.role] || "";
        label.append(select);
        return label;
    }));
    elements.applyBindings.disabled = !state.result?.steps.length;
}

async function loadExamples() {
    try {
        const response = await fetch("/api/examples");
        if (!response.ok) return;
        state.examples = await response.json();
        elements.exampleSelect.replaceChildren(new Option("選擇範例…", ""),
            ...state.examples.map((item) => new Option(`${item.title} · ${item.language}`, item.id)));
    } catch (_error) { /* Examples are optional; the editor remains usable offline. */ }
}

// Hovering (or focusing) anything with `data-term` shows what that word means (terms.js).
const hoverTip = document.createElement("div");
hoverTip.className = "hover-tip";
hoverTip.setAttribute("role", "tooltip");
hoverTip.hidden = true;
document.body.append(hoverTip);

function showTermTip(event) {
    const target = event.target.closest?.("[data-term]");
    const tip = target && window.DebuggerTerms?.lookup(target.dataset.term);
    if (!tip) {
        hoverTip.hidden = true;
        return;
    }
    hoverTip.textContent = tip;
    hoverTip.hidden = false;
    const anchorBox = target.getBoundingClientRect();
    const width = hoverTip.offsetWidth;
    const height = hoverTip.offsetHeight;
    const left = Math.min(Math.max(8, anchorBox.left), window.innerWidth - width - 8);
    const below = anchorBox.bottom + 6;
    const top = below + height > window.innerHeight - 8 ? anchorBox.top - height - 6 : below;
    hoverTip.style.left = `${left}px`;
    hoverTip.style.top = `${Math.max(8, top)}px`;
}

document.addEventListener("mouseover", showTermTip);
document.addEventListener("focusin", showTermTip);
document.addEventListener("scroll", () => { hoverTip.hidden = true; }, true);

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
    elements.languageSelect.value = nextLanguage;
    state.bindings = {};
    elements.bindingMode.value = "auto";
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
    state.eventIndexes = {};
    elements.applyBindings.disabled = true;
    elements.slider.min = "0";
    elements.slider.max = "0";
    elements.slider.value = "0";
    elements.slider.disabled = true;
    updateTimelineButtons();
    elements.location.textContent = "未執行";
    elements.functionName.textContent = "—";
    elements.stepLabel.textContent = "未執行";
    elements.eventLabel.textContent = "";
    elements.eventLabel.hidden = true;
    elements.variables.className = "panel-body empty-state";
    elements.variables.textContent = "執行後顯示變數";
    elements.stdout.innerHTML = '<span class="output-placeholder">尚無輸出</span>';
    elements.algorithmName.textContent = "資料";
    elements.algorithmDetectedName.textContent = "尚未辨識";
    elements.algorithmConfidence.textContent = "未分析";
    elements.algorithmEvidence.textContent = "執行後辨識結構";
    elements.visualScaleInfo.hidden = true;
    elements.algorithmView.className = "algorithm-canvas empty-state";
    elements.algorithmView.textContent = "執行後顯示資料";
    elements.algorithmInputs.replaceChildren();
    elements.algorithmInputs.hidden = true;
    configureViewSelects();
    setMessage("");
    setStatus("idle", "就緒");
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
    if (view.pending) return {renderer: view.renderer, ready: false, pending: true, name: view.variable};
    return step.views?.[view.id] || {renderer: view.renderer, ready: false};
}

function configureViewSelects() {
    const renderers = [...new Set(availableViews().map((view) => view.renderer))];
    const autoRenderer = state.result?.algorithm?.auto_renderer || state.result?.algorithm?.renderer;
    const autoLabel = autoRenderer ? `自動 · ${COMPACT_RENDERER_LABELS[autoRenderer] || RENDERER_LABELS[autoRenderer] || autoRenderer}` : "自動";
    elements.viewSelect.replaceChildren(
        new Option(autoLabel, "auto"),
        ...renderers.map((renderer) => new Option(COMPACT_RENDERER_LABELS[renderer] || RENDERER_LABELS[renderer] || renderer, renderer)),
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
    // Variables past the precomputed ones are still listed; picking one runs the program again.
    const pending = new Set(availableViews().filter((item) => item.renderer === view?.renderer && item.pending).map((item) => item.variable));
    elements.viewVariableSelect.replaceChildren(
        ...variables.map((name) => new Option(pending.has(name) ? `${name}（重跑）` : name, name)),
    );
    elements.viewVariableSelect.hidden = !variables.length;
    if (view?.variable) elements.viewVariableSelect.value = view.variable;
}

function chooseView(renderer, variable) {
    state.view = {renderer, variable};
    updateViewSelects();
    if (state.result?.steps.length) renderStep();
    const view = effectiveView();
    if (view?.pending) loadView(view.id);
}

// Run the same program again asking for one more view (`DebugRequest.views`), then show it at
// the same step. Only the first few views per kind are computed up front, to keep traces small.
async function loadView(viewId) {
    if (!state.lastRun || state.loadingView) return;
    state.loadingView = viewId;
    const step = state.currentStep;
    try {
        const response = await fetch("/api/debug", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({...state.lastRun, views: [...state.extraViews, viewId]}),
        });
        const payload = await response.json();
        if (!response.ok) throw new Error(apiErrorMessage(payload));
        state.extraViews = [...state.extraViews, viewId];
        state.result = payload;
        state.currentStep = Math.min(step, Math.max(0, payload.steps.length - 1));
        indexObjects(payload.steps);
        configureViewSelects();
        configureTimeline();
        if (payload.steps.length) renderStep();
    } catch (error) {
        setMessage(error instanceof Error ? error.message : String(error));
    } finally {
        state.loadingView = null;
    }
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
        goToStep(navigationTarget(1));
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
    elements.playButton.querySelector(".play-label").textContent = playing ? "暫停" : "播放";
}

function stepManually(index) {
    stopPlayback();
    goToStep(index);
}

async function runCode() {
    if (elements.runButton.disabled) return;
    const code = elements.editor.value;
    const stdin = elements.stdinEditor.value;
    const capture_items = Number(elements.captureItems.value);
    const capture_depth = Number(elements.captureDepth.value);
    stopPlayback();
    setMessage("");
    setEditorErrors([]);
    setStatus("running", "執行中");
    elements.runButton.disabled = true;
    elements.languageSelect.disabled = true;
    elements.exampleSelect.disabled = true;
    elements.applyBindings.disabled = true;

    try {
        const response = await fetch("/api/debug", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({code, stdin, language: state.language, bindings: state.bindings, capture_items, capture_depth}),
        });
        state.lastRun = {code, stdin, language: state.language, bindings: state.bindings, capture_items, capture_depth};
        state.extraViews = [];
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
        if (payload.algorithm?.binding_warnings?.length) setMessage(payload.algorithm.binding_warnings.join("\n"));
        configureViewSelects();
        configureBindings();
        showViewer();
        configureTimeline();

        if (payload.steps.length > 0) {
            renderStep();
        } else {
            renderEmptyTrace();
        }

        if (payload.status === "completed") {
            setStatus("success", "完成");
        } else if (payload.status === "exception") {
            setStatus("error", payload.error?.type || "Exception");
        } else if (payload.status === "timeout") {
            setStatus("error", "TLE · 已保留步驟");
        } else {
            setStatus("error", "TLE · 步數上限");
        }
    } catch (error) {
        setStatus("error", "無法執行");
        setMessage(error instanceof Error ? error.message : String(error));
    } finally {
        elements.runButton.disabled = false;
        elements.languageSelect.disabled = false;
        elements.exampleSelect.disabled = false;
        elements.applyBindings.disabled = !state.result;
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
    buildNavigationIndexes();
    updateTimelineButtons();
}

function buildNavigationIndexes() {
    const steps = state.result?.steps || [];
    const indexes = {event: new Set(), call: new Set(), return: new Set(), change: new Set()};
    steps.forEach((step, index) => {
        const depth = step.depth ?? step.stack?.length ?? 0;
        const previousDepth = index ? (steps[index - 1].depth ?? steps[index - 1].stack?.length ?? 0) : depth;
        if (step.event === "call" || depth > previousDepth) indexes.call.add(index);
        if (step.event === "return" || depth < previousDepth) indexes.return.add(index);
        const usage = step.usage || {};
        if (Object.keys(usage.next || {}).length || Object.keys(usage.cells || {}).length || Object.keys(usage.appearing || {}).length) indexes.change.add(index);
        if (["exception", "stopped"].includes(step.event)) indexes.event.add(index);
    });
    for (const event of state.result?.algorithm?.events || []) {
        const index = event.index ?? event.step;
        if (Number.isInteger(index) && index >= 0 && index < steps.length) indexes.event.add(index);
    }
    for (const kind of ["call", "return", "change"]) indexes[kind].forEach((index) => indexes.event.add(index));
    for (const kind of Object.keys(indexes)) {
        if (steps.length) { indexes[kind].add(0); indexes[kind].add(steps.length - 1); }
        indexes[kind] = [...indexes[kind]].sort((a, b) => a - b);
    }
    state.eventIndexes = indexes;
}

function navigationTarget(direction) {
    const last = Math.max(0, (state.result?.steps.length || 1) - 1);
    if (state.stepMode === "line") return Math.max(0, Math.min(last, state.currentStep + direction));
    const indexes = state.eventIndexes[state.stepMode] || [];
    return direction > 0
        ? indexes.find((index) => index > state.currentStep) ?? last
        : indexes.findLast((index) => index < state.currentStep) ?? 0;
}

function currentCallEnd() {
    const step = state.result?.steps[state.currentStep];
    const id = step?.views?.recursion_tree?.current;
    const node = state.result?.algorithm?.recursion_tree?.nodes?.[id];
    if (!node || node.parent == null || node.end_step == null) return null;
    const target = Math.min(node.end_step + 1, state.result.steps.length - 1);
    return target > state.currentStep ? target : null;
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

    elements.location.textContent = `L${step.line}`;
    elements.functionName.textContent = step.function;
    elements.stepLabel.textContent = `${state.currentStep + 1} / ${state.result.steps.length}`;
    elements.stepLabel.setAttribute("aria-label", `第 ${state.currentStep + 1} 步，共 ${state.result.steps.length} 步`);
    elements.eventLabel.textContent = {call: "呼叫", return: "返回", exception: "例外", stopped: "停止"}[step.event] || "";
    elements.eventLabel.hidden = !elements.eventLabel.textContent;
    elements.eventLabel.dataset.term = step.event;
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
    elements.callEndButton.disabled = currentCallEnd() === null;
    elements.stepMode.disabled = !hasSteps;
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
    if (!elements.sourceViewer.clientHeight) return;
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

function renderOutput(stdout) {
    elements.stdout.replaceChildren();
    if (stdout) {
        elements.stdout.textContent = stdout;
        // The panel shows three lines, so keep the newest output in view.
        elements.stdout.scrollTop = elements.stdout.scrollHeight;
    } else {
        const placeholder = document.createElement("span");
        placeholder.className = "output-placeholder";
        placeholder.textContent = "尚無輸出";
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

function renderEmptyTrace() {
    renderSource(0);
    elements.location.textContent = "完成";
    elements.functionName.textContent = "—";
    elements.stepLabel.textContent = "無步驟";
    elements.eventLabel.textContent = "";
    elements.eventLabel.hidden = true;
    elements.variables.className = "panel-body empty-state";
    elements.variables.textContent = "This program produced no trace events.";
    renderOutput("");
    elements.algorithmView.replaceChildren();
    elements.algorithmView.className = "algorithm-canvas";
    renderAlgorithmWaiting("This program produced no visualization steps.");
}
