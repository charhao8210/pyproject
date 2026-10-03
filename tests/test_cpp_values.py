from app.cpp_runner import _clean_program_output, _parse_trace, _serialize_cpp_value
from app.cpp_source import analyze_source


def _plain(value: dict):
    if value["type"] == "list":
        return [_plain(item) for item in value["items"]]
    if value["type"] == "dict":
        return {entry["key"]["value"]: _plain(entry["value"]) for entry in value["entries"]}
    return value.get("value")


def test_pairs_become_tuples_after_base_classes_are_flattened() -> None:
    value = _serialize_cpp_value(
        "{{<std::__pair_base<long long, int>> = {<No data fields>}, first = 3, second = 1}, "
        "{<std::__pair_base<long long, int>> = {<No data fields>}, first = 1, second = 2}}",
        "main:a",
    )

    assert [item["type"] for item in value["items"]] == ["tuple", "tuple"]
    assert [[entry["value"] for entry in item["items"]] for item in value["items"]] == [[3, 1], [1, 2]]


def test_std_string_objects_and_char_values_decode_to_text() -> None:
    string_object = (
        "{static npos = 18446744073709551615, _M_dataplus = {<std::allocator<char>> = "
        '{<No data fields>}, _M_p = 0x61fe00 "a\\303\\251#"}, _M_string_length = 4, '
        '{_M_local_buf = "a\\303\\251#\\000", _M_allocated_capacity = 1}}'
    )

    assert _serialize_cpp_value(string_object, "main:s") == {"type": "str", "value": "aé#"}
    assert _serialize_cpp_value("97 'a'", "main:c") == {"type": "str", "value": "a"}
    assert _serialize_cpp_value('0x61fe00 "..#"', "main:row") == {"type": "str", "value": "..#"}
    assert _plain(
        _serialize_cpp_value(
            "{{static npos = 1, _M_dataplus = {_M_p = 0x1 \"ab\"}}, "
            "{static npos = 1, _M_dataplus = {_M_p = 0x2 \"cd\"}}}",
            "main:g",
        )
    ) == ["ab", "cd"]


def test_bit_vectors_and_sparse_tables_expand_to_rows() -> None:
    bits = _serialize_cpp_value("@bits 5 32 {18}", "main:vis")
    table = _serialize_cpp_value("@rows 4\n1 2 {2, 3}\n3 1 {1}\n", "::adj")

    assert _plain(bits) == [False, True, False, False, True]
    assert _plain(table) == [[], [2, 3], [], [1]]
    assert table["items"][0]["object_id"] != table["items"][2]["object_id"]


def test_clipped_values_are_marked_truncated() -> None:
    clipped_vector = _serialize_cpp_value("{" + ", ".join(["5"] * 50) + "}...", "main:big")
    clipped_array = _serialize_cpp_value("{0, 0, 0...}", "::a")
    clipped_row = _serialize_cpp_value("@rows 40\n0 45 {1, 2}\n", "main:grid")

    assert clipped_vector["truncated"] is True and len(clipped_vector["items"]) == 50
    assert clipped_array["truncated"] is True and _plain(clipped_array) == [0, 0, 0]
    assert clipped_row["truncated"] is True and len(clipped_row["items"]) == 30
    assert clipped_row["items"][0]["truncated"] is True


def test_undecoded_stl_internals_are_hidden() -> None:
    deque = (
        "{c = {<std::_Deque_base<int, std::allocator<int> >> = {_M_impl = "
        "{_M_map = 0x1, _M_map_size = 8}}, <No data fields>}}"
    )

    value = _serialize_cpp_value(deque, "main:q")

    assert value["type"] == "object"
    assert value["class_name"] == "STL container"


def test_signal_report_and_partial_block_do_not_leak_into_stdout() -> None:
    source = "int main() {\n    int x = 1;\n    return x;\n}\n"
    output = (
        "__PVDBG_BEGIN__\n#0  main () at program.cpp:2\n__PVDBG_ARGS__\nNo arguments.\n"
        "__PVDBG_LOCALS__\nx = 0\n__PVDBG_STACK__\n#0  main () at program.cpp:2\n__PVDBG_END__\n"
        "partial output\n__PVDBG_BEGIN__\n#0  main () at program.cpp:3\n__PVDBG_ARGS__\n"
    )

    steps, stdout, incomplete_line = _parse_trace(output, analyze_source(source))

    assert len(steps) == 1
    assert stdout == "partial output\n"
    assert incomplete_line == 3
    # GDB opens a signal report with a newline of its own.
    assert _clean_program_output(
        "done\n\nThread 1 received signal SIGSEGV, Segmentation fault.\n"
        "0x0000 in main () at program.cpp:5\n5\t    *p = 3;\n"
    ) == "done\n"
    # A newline the program prints by itself (`cout << "\n";`) is part of its output.
    assert _clean_program_output("\n") == "\n"
    assert _clean_program_output("\n0 1 2") == "\n0 1 2"
