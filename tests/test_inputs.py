from app.inputs import input_values


def step(line, locals_=None, globals_=None, function="main"):
    return {"line": line, "function": function, "locals": locals_ or {}, "globals": globals_ or {}}


def number(value):
    return {"type": "int", "value": value}


CPP = """int main() {
    int n, k;
    cin >> n >> k;
    for (int i = 0; i < n; i++) {
        k += i;
    }
}"""


def test_a_value_read_once_is_an_input_and_hidden_before_it_is_read() -> None:
    steps = [
        step(3, {"n": number(32767), "k": number(-1)}),
        step(4, {"n": number(3), "k": number(5)}),
        step(5, {"n": number(3), "k": number(5), "i": number(0)}),
        step(5, {"n": number(3), "k": number(5), "i": number(1)}),
        step(7, {"n": number(3), "k": number(6)}),
    ]

    inputs = input_values(CPP, "cpp", steps)

    assert inputs[0] == [{"name": "n", "value": None, "read": False}]
    assert inputs[1] == [{"name": "n", "value": 3, "read": True}]
    assert inputs[4] == [{"name": "n", "value": 3, "read": True}]


def test_python_module_values_count_only_when_never_changed_after_reading() -> None:
    source = "n = int(input())\nm = int(input())\nm -= 1\nprint(n)"
    steps = [
        step(1, function="<module>"),
        step(2, {"n": number(4)}, function="<module>"),
        step(3, {"n": number(4), "m": number(2)}, function="<module>"),
        step(4, {"n": number(4), "m": number(1)}, function="<module>"),
    ]

    inputs = input_values(source, "python", steps)

    assert [entry["name"] for entry in inputs[3]] == ["n"]


def test_a_value_read_again_in_a_loop_is_not_an_input() -> None:
    source = "int a;\nwhile (cin >> a) {\n    s += a;\n}"
    steps = [
        step(2, {"a": number(0)}),
        step(3, {"a": number(7)}),
        step(2, {"a": number(7)}),
        step(3, {"a": number(9)}),
    ]

    assert input_values(source, "cpp", steps) == [[], [], [], []]
