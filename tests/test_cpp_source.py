from app.cpp_source import analyze_source, classify_type, strip_code


def _specs(source: str) -> dict[str, tuple]:
    return {
        spec.name: (spec.kind, spec.element, spec.row_type, spec.ready_line, spec.scope_end_line)
        for spec in analyze_source(source).vectors
    }


def test_strip_code_blanks_comments_literals_and_directives_but_keeps_lines() -> None:
    source = '#include <vector>\nint a; // {\n/* {\n } */ char c = \'{\';\nstring s = "a;{b}";\n'

    stripped = strip_code(source)

    assert stripped.count("\n") == source.count("\n")
    assert "{" not in stripped and "}" not in stripped
    assert "include" not in stripped
    assert "int a;" in stripped


def test_function_returning_vector_is_not_a_variable() -> None:
    specs = _specs(
        """vector<int> build(int n) {
    vector<int> out;
    return out;
}
vector<int> empty() { return {}; }
"""
    )

    assert set(specs) == {"out"}


def test_parameters_and_range_for_variables_are_scoped_to_their_body() -> None:
    specs = _specs(
        """int total(const vector<int>& a,
          vector<vector<int>> &grid) {
    int s = 0;
    for (const vector<int>& row : grid) {
        s += row[0];
    }
    return s;
}
int prototype(vector<int>& unused);
"""
    )

    assert specs["a"] == ("vector", "", "", 2, 8)
    assert specs["grid"] == ("nested", "vector", "int", 2, 8)
    assert specs["row"] == ("vector", "", "", 4, 6)
    assert "unused" not in specs


def test_block_scope_ends_before_else_branch_and_initializer_must_finish() -> None:
    source = """int main() {
    int flag = 0;
    if (flag) {
        vector<int> a(3, 7), b(2);
        flag = a[0];
    } else {
        flag = 2;
    }
    vector<int> v = {
        1, 2,
    };
    return 0;
}
"""
    model = analyze_source(source)
    specs = {spec.name: spec for spec in model.vectors}

    assert specs["a"].visible_at(5)
    assert not specs["a"].visible_at(6)
    assert not specs["a"].visible_at(7)
    assert specs["b"].visible_at(5)
    assert not specs["v"].visible_at(10)
    assert specs["v"].visible_at(12)


def test_vector_kinds_and_aliases() -> None:
    specs = _specs(
        """typedef long long ll;
typedef vector<int> vi;
using vvi = vector<vi>;
int main() {
    vector<bool> seen(3);
    vector<vector<bool>> vis(2, vector<bool>(2));
    vi a(4);
    vvi grid(2, vi(2));
    vector<int> adj[5];
    vector<pair<ll, int>> pairs;
    vector<ll> *pointer = nullptr;
    return 0;
}
"""
    )

    assert specs["seen"][:3] == ("bits", "", "")
    assert specs["vis"][:3] == ("nested", "bits", "")
    assert specs["a"][:3] == ("vector", "", "")
    assert specs["grid"][:3] == ("nested", "vector", "int")
    assert specs["adj"][:3] == ("vector_array", "vector", "int")
    assert specs["pairs"][:3] == ("vector", "", "")
    assert "pointer" not in specs


def test_builtin_type_macro_disables_raw_casts() -> None:
    model = analyze_source(
        """typedef vector<int> vi;
#define int long long
signed main() {
    vector<vi> grid(2, vi(3));
    return 0;
}
"""
    )

    assert not model.raw_casts
    assert [spec.row_type for spec in model.vectors] == [""]
    assert model.macros == {"int": "long long"}
    assert model.aliases == {"vi": "vector<int>"}


def test_namespace_scope_candidates_skip_constants_types_and_bodies() -> None:
    model = analyze_source(
        """const int N = 10;
int n, m;
long long dp[N][N];
vector<int> adj[N];
int dx[] = {1, 0, -1, 0};
struct Edge { int to; };
int f(int);
int main() {
    int local = 0;
    return local;
}
"""
    )

    assert [candidate.name for candidate in model.globals] == ["n", "m", "dp", "adj", "dx", "f"]


def test_classify_gdb_reported_types() -> None:
    aliases = {"ll": "long long", "vi": "vector<int>"}

    assert classify_type("std::vector<int, std::allocator<int> >", 1, aliases) == ("vector_array", "vector", "int")
    assert classify_type("std::vector<bool, std::allocator<bool> >", 0, aliases) == ("bits", "", "")
    assert classify_type(
        "std::vector<std::vector<long long, std::allocator<long long> >, "
        "std::allocator<std::vector<long long, std::allocator<long long> > > >",
        0,
        aliases,
    ) == ("nested", "vector", "long long")
    assert classify_type("std::__cxx11::basic_string<char, std::char_traits<char>, std::allocator<char> >", 0, aliases) == ("string", "", "")
    assert classify_type("ll", 1, aliases) == ("array", "", "")
    assert classify_type("char", 2, aliases) == ("matrix", "text", "")
    assert classify_type("vi", 0, aliases) == ("vector", "", "")
    assert classify_type("const int", 0, aliases) is None
    assert classify_type("int (int)", 0, aliases) is None
    assert classify_type("Node", 1, aliases) is None
