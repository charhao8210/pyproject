from pathlib import Path


def test_step_navigation_only_scrolls_inside_source_viewer() -> None:
    script = Path("app/static/app.js").read_text(encoding="utf-8")

    assert ".scrollIntoView(" not in script
    assert "elements.sourceViewer.scrollTo" in script
    assert "window.scrollTo(pageScrollX, pageScrollY)" in script


def test_object_graph_panel_is_removed() -> None:
    template = Path("app/templates/index.html").read_text(encoding="utf-8")
    script = Path("app/static/app.js").read_text(encoding="utf-8")
    stylesheet = Path("app/static/style.css").read_text(encoding="utf-8")

    assert 'id="graph-panel"' not in template
    assert 'id="object-graph"' not in template
    assert "renderObjectGraph" not in script
    assert "graphPanel" not in script
    assert ".graph-panel" not in stylesheet


def test_language_selector_sends_python_or_cpp() -> None:
    template = Path("app/templates/index.html").read_text(encoding="utf-8")
    script = Path("app/static/app.js").read_text(encoding="utf-8")

    assert 'id="language-select"' in template
    assert '<option value="python"' in template
    assert '<option value="cpp"' in template
    assert "function changeLanguage" in script
    assert "language: state.language" in script


def test_adaptive_renderer_is_beside_code_and_runtime_event_is_removed() -> None:
    template = Path("app/templates/index.html").read_text(encoding="utf-8")

    left_column = template.index('class="left-column"')
    right_column = template.index('class="right-column"')
    adaptive_renderer = template.index('class="panel algorithm-panel"')
    variables = template.index('class="panel variables-panel"')
    stdout = template.index('class="panel output-panel"')
    assert left_column < right_column < adaptive_renderer < variables < stdout
    assert "Runtime event" not in template
    assert 'id="event-detail"' not in template


def test_call_stack_panel_is_removed() -> None:
    template = Path("app/templates/index.html").read_text(encoding="utf-8")
    script = Path("app/static/app.js").read_text(encoding="utf-8")

    assert 'id="call-stack"' not in template
    assert "elements.callStack" not in script


def test_every_workspace_panel_can_be_hidden() -> None:
    template = Path("app/templates/index.html").read_text(encoding="utf-8")
    script = Path("app/static/app.js").read_text(encoding="utf-8")

    for name in ("source", "stdin", "algorithm", "variables", "stdout"):
        assert f'data-panel="{name}"' in template
    assert template.count('class="panel-action panel-toggle"') == 5
    assert "function setPanelExpanded" in script
    assert 'classList.toggle("left-collapsed"' in script
    assert 'classList.toggle("right-collapsed"' in script


def test_autoplay_offers_the_requested_speeds() -> None:
    template = Path("app/templates/index.html").read_text(encoding="utf-8")
    script = Path("app/static/app.js").read_text(encoding="utf-8")

    assert 'id="play-button"' in template
    for speed in ("0.25", "0.5", "1", "1.5", "1.75", "2"):
        assert f'<option value="{speed}"' in template
    assert "PLAYBACK_STEPS_PER_SECOND = 2" in script
    assert "PLAYBACK_SPEEDS = [0.25, 0.5, 1, 1.5, 1.75, 2]" in script
    assert "function togglePlayback" in script


def test_dark_theme_is_default_with_light_toggle() -> None:
    template = Path("app/templates/index.html").read_text(encoding="utf-8")
    stylesheet = Path("app/static/style.css").read_text(encoding="utf-8")

    assert '<html lang="zh-Hant" data-theme="dark">' in template
    assert 'id="theme-button"' in template
    assert ':root[data-theme="light"]' in stylesheet


def test_view_and_variable_can_be_chosen_by_hand() -> None:
    template = Path("app/templates/index.html").read_text(encoding="utf-8")
    script = Path("app/static/app.js").read_text(encoding="utf-8")

    assert 'id="view-select"' in template
    assert 'id="view-variable-select"' in template
    assert "function currentVisualization" in script
    assert "step.views?.[view.id]" in script
    for renderer in ("cells: renderCellsAlgorithm", "recursion_tree: renderRecursionTreeAlgorithm"):
        assert renderer in script


def test_code_is_syntax_highlighted_while_editing_and_stepping() -> None:
    template = Path("app/templates/index.html").read_text(encoding="utf-8")
    script = Path("app/static/app.js").read_text(encoding="utf-8")
    stylesheet = Path("app/static/style.css").read_text(encoding="utf-8")

    assert template.index("/highlight.js") < template.index("/app.js")
    assert 'id="editor-highlight"' in template
    assert 'wrap="off"' in template
    assert "SyntaxHighlighter.tokenize(elements.editor.value, state.language)" in script
    assert "SyntaxHighlighter.lines(state.result.source, state.result.language)" in script
    assert "--syn-keyword: #cba6f7" in stylesheet  # Catppuccin Mocha mauve
    assert "--syn-keyword: #8839ef" in stylesheet  # Catppuccin Latte mauve


def test_visited_cells_use_a_check_mark_instead_of_hatching() -> None:
    stylesheet = Path("app/static/style.css").read_text(encoding="utf-8")

    assert "hatch" not in stylesheet
    assert '.algorithm-cell.visited::after' in stylesheet
    assert 'content: "✓"' in stylesheet


def test_columns_can_be_resized_by_dragging_the_divider() -> None:
    template = Path("app/templates/index.html").read_text(encoding="utf-8")
    script = Path("app/static/app.js").read_text(encoding="utf-8")

    assert template.index('id="left-column"') < template.index('id="column-resizer"') < template.index('id="right-column"')
    assert 'role="separator"' in template
    assert "function startColumnResize" in script
    assert '"--left-width"' in script


def test_right_column_panels_can_be_resized_by_dragging_row_dividers() -> None:
    template = Path("app/templates/index.html").read_text(encoding="utf-8")
    script = Path("app/static/app.js").read_text(encoding="utf-8")
    stylesheet = Path("app/static/style.css").read_text(encoding="utf-8")

    algorithm = template.index('class="panel algorithm-panel"')
    variables = template.index('class="panel variables-panel"')
    stdout = template.index('class="panel output-panel"')
    first = template.index('class="row-resizer"')
    second = template.index('class="row-resizer"', first + 1)
    assert algorithm < first < variables < second < stdout
    assert 'aria-orientation="horizontal"' in template
    for name in ("function startRowResize", "function moveRowBoundary", "function updateRowResizers", "resetRowSizes"):
        assert name in script
    assert "flex: var(--row-grow) 1 0px" in stylesheet
    assert "cursor: row-resize" in stylesheet


def test_variables_put_single_values_in_a_row_and_fold_zero_tails() -> None:
    script = Path("app/static/app.js").read_text(encoding="utf-8")
    stylesheet = Path("app/static/style.css").read_text(encoding="utf-8")

    assert 'scalars.className = "scalar-zone"' in script
    assert "function isScalarValue" in script
    assert "function fillNote" in script
    assert ".scalar-zone" in stylesheet
    assert ".fill-note" in stylesheet


def test_variables_panel_skips_drawn_variables_and_never_scrolls_sideways() -> None:
    script = Path("app/static/app.js").read_text(encoding="utf-8")
    stylesheet = Path("app/static/style.css").read_text(encoding="utf-8")

    assert "visualization?.uses" in script
    assert "flex-wrap: wrap" in stylesheet[stylesheet.index(".array-view {"):]
    assert "overflow-x: hidden" in stylesheet[stylesheet.index(".panel-body {"):]


def test_graph_renderers_expose_draggable_nodes() -> None:
    script = Path("app/static/app.js").read_text(encoding="utf-8")
    stylesheet = Path("app/static/style.css").read_text(encoding="utf-8")

    assert "function enableSvgNodeDragging" in script
    assert "state.algorithmGraphPositions" in script
    assert ".algorithm-graph-node" in stylesheet
    assert "cursor: grab" in stylesheet
    assert "touch-action: none" in stylesheet


def test_svg_dragging_maps_pointer_through_screen_ctm() -> None:
    script = Path("app/static/app.js").read_text(encoding="utf-8")
    dragging = script[script.index("function enableSvgNodeDragging"):]

    # getBoundingClientRect ignores preserveAspectRatio letterboxing on scaled SVGs.
    assert "getScreenCTM()" in dragging
    assert "getBoundingClientRect" not in dragging.split("function truncate")[0]
    assert dragging.index("group.parentNode.append(group)") < dragging.index("setPointerCapture")
    assert "lostpointercapture" in dragging


def test_array_renderer_uses_backend_interval_and_readouts() -> None:
    script = Path("app/static/app.js").read_text(encoding="utf-8")
    renderer = script[script.index("function renderArrayAlgorithm"):script.index("function renderGraphAlgorithm")]

    assert "view.interval" in renderer
    assert "view.readouts" in renderer
    assert "!indexMarkers.length" in renderer


def test_variables_panel_includes_unshadowed_globals() -> None:
    script = Path("app/static/app.js").read_text(encoding="utf-8")

    assert "renderVariables(step, visualization)" in script
    assert "Object.hasOwn(locals, name)" in script


def test_recursion_tree_and_call_chain_nodes_are_draggable_and_numbered() -> None:
    script = Path("app/static/app.js").read_text(encoding="utf-8")
    stylesheet = Path("app/static/style.css").read_text(encoding="utf-8")

    tree = script[script.index("function renderRecursionTreeAlgorithm"):script.index("function renderCallTreeAlgorithm")]
    chain = script[script.index("function renderCallTreeAlgorithm"):script.index("function renderExecutionAlgorithm")]
    assert "enableSvgNodeDragging" in tree
    assert "state.recursionPositions" in tree
    assert "node.order" in tree
    assert "enableSvgNodeDragging" in chain
    assert "state.callChainPositions" in chain
    assert ".recursion-order" in stylesheet


def test_runtime_errors_timeouts_and_rejected_lines_are_marked() -> None:
    script = Path("app/static/app.js").read_text(encoding="utf-8")
    stylesheet = Path("app/static/style.css").read_text(encoding="utf-8")

    assert "function lineProblem" in script
    assert "TLE at line" in script
    assert "RE at line" in script
    assert "setEditorErrors(payload.detail.issues)" in script
    assert ".source-line.timeout .line-text" in stylesheet
    assert ".editor-error-line" in stylesheet


def test_variables_used_or_changed_by_the_step_are_marked() -> None:
    template = Path("app/templates/index.html").read_text(encoding="utf-8")
    script = Path("app/static/app.js").read_text(encoding="utf-8")

    assert 'class="usage-legend"' in template
    assert 'card.classList.toggle("is-on-line"' in script
    assert 'card.classList.toggle("is-changed"' in script


def test_loop_buttons_skip_the_innermost_loop() -> None:
    template = Path("app/templates/index.html").read_text(encoding="utf-8")
    script = Path("app/static/app.js").read_text(encoding="utf-8")

    assert 'id="loop-start-button"' in template and 'id="loop-end-button"' in template
    assert 'id="first-button"' not in template and 'id="last-button"' not in template
    assert 'jumpOutOfLoop("before")' in script and 'jumpOutOfLoop("after")' in script
    assert "loop?.before == null" in script


def test_two_dimensional_arrays_render_as_tables() -> None:
    script = Path("app/static/app.js").read_text(encoding="utf-8")
    stylesheet = Path("app/static/style.css").read_text(encoding="utf-8")

    assert "function renderTableValue" in script
    assert "function isTableValue" in script
    assert ".table-view" in stylesheet
    # NUL marks a C++ char cell nothing has written yet; it is drawn blank.
    assert r'value === "\0"' in script


def test_variables_keep_first_seen_order_and_input_values_sit_above_the_view() -> None:
    template = Path("app/templates/index.html").read_text(encoding="utf-8")
    script = Path("app/static/app.js").read_text(encoding="utf-8")
    stylesheet = Path("app/static/style.css").read_text(encoding="utf-8")

    assert 'id="algorithm-inputs"' in template
    assert template.index('id="algorithm-inputs"') < template.index('id="algorithm-view"')
    assert "function variableOrder" in script
    assert "function renderInputs" in script
    assert "inputNames(step)" in script
    assert ".variable-zones.is-split" in stylesheet


def test_variables_show_old_to_new_values_and_tint_changed_cells() -> None:
    script = Path("app/static/app.js").read_text(encoding="utf-8")
    style = Path("app/static/style.css").read_text(encoding="utf-8")

    assert 'textSpan("->", "change-arrow")' in script
    assert "step.usage?.next" in script and "step.usage?.cells" in script
    assert "is-changed-cell" in script and ".table-cell.is-changed-cell" in style


def test_new_variables_are_tinted() -> None:
    script = Path("app/static/app.js").read_text(encoding="utf-8")
    style = Path("app/static/style.css").read_text(encoding="utf-8")

    assert "step.usage?.new" in script and 'card.classList.toggle("is-new"' in script
    assert "step.usage?.appearing" in script
    assert ".scalar-row.is-new" in style and ".variable-card.is-new" in style


def test_assignments_show_their_formula() -> None:
    script = Path("app/static/app.js").read_text(encoding="utf-8")

    assert "function formulaText(" in script and "step.usage?.formula" in script
    # Substituted forms holding a number of 10^6 or more are left out.
    assert r"/\d{7,}/.test(substituted)" in script


def test_large_integers_render_from_their_exact_text() -> None:
    script = Path("app/static/app.js").read_text(encoding="utf-8")

    assert "function numberText(" in script and "value.text ?? String(value.value)" in script
