"use strict";

// Small tokenizers for the two supported languages. Token types become `tok-*` classes,
// which style.css colors with the Catppuccin palette (Mocha in dark mode, Latte in light).
const SyntaxHighlighter = (() => {
    const PYTHON_KEYWORDS = new Set([
        "and", "as", "assert", "async", "await", "break", "class", "continue", "def", "del",
        "elif", "else", "except", "finally", "for", "from", "global", "if", "import", "in",
        "is", "lambda", "nonlocal", "not", "or", "pass", "raise", "return",
        "try", "while", "with", "yield",
    ]);
    const PYTHON_CONSTANTS = new Set(["True", "False", "None", "NotImplemented", "Ellipsis"]);
    // Builtin classes read as types, the way VS Code's semantic highlighting shows them.
    const PYTHON_TYPES = new Set([
        "bool", "bytes", "complex", "dict", "float", "frozenset", "int", "list", "object",
        "range", "set", "str", "tuple", "type",
    ]);
    const PYTHON_SELF = new Set(["self", "cls"]);

    const CPP_KEYWORDS = new Set([
        "alignas", "alignof", "auto", "break", "case", "catch", "class", "const", "constexpr",
        "continue", "default", "delete", "do", "else", "enum", "explicit", "extern", "for",
        "friend", "goto", "if", "inline", "mutable", "namespace", "new", "noexcept", "operator",
        "private", "protected", "public", "register", "return", "sizeof", "static",
        "static_cast", "struct", "switch", "template", "this", "throw", "try", "typedef",
        "typename", "union", "using", "virtual", "volatile", "while",
    ]);
    const CPP_TYPES = new Set([
        "bool", "char", "double", "float", "int", "long", "short", "signed", "unsigned", "void",
        "size_t", "int64_t", "uint64_t", "int32_t", "uint32_t", "std", "string", "vector",
        "pair", "map", "set", "unordered_map", "unordered_set", "queue", "stack", "deque",
        "priority_queue", "array", "tuple", "multiset", "multimap", "bitset",
    ]);
    const CPP_CONSTANTS = new Set(["true", "false", "nullptr", "NULL"]);

    const PYTHON_RULES = [
        [/#[^\n]*/y, "comment"],
        [/(?:[rRbBuUfF]{1,2})?(?:'''[\s\S]*?(?:'''|$)|"""[\s\S]*?(?:"""|$)|'(?:[^'\\\n]|\\.)*'?|"(?:[^"\\\n]|\\.)*"?)/y, "string"],
        [/@[A-Za-z_][\w.]*/y, "decorator"],
        [/(?:0[xX][\da-fA-F_]+|0[bB][01_]+|0[oO][0-7_]+|(?:\d[\d_]*\.?[\d_]*|\.\d[\d_]*)(?:[eE][+-]?\d+)?[jJ]?)/y, "number"],
        [/[A-Za-z_]\w*/y, "identifier"],
        [/[+\-*/%=<>!&|^~]+/y, "operator"],
        [/\s+/y, "plain"],
        [/[\s\S]/y, "punct"],
    ];

    const CPP_RULES = [
        [/\/\/[^\n]*/y, "comment"],
        [/\/\*[\s\S]*?(?:\*\/|$)/y, "comment"],
        [/#[ \t]*[A-Za-z_]+/y, "keyword"],
        [/<[\w./+-]+>/y, "header"],
        [/(?:u8|[uUL])?"(?:[^"\\\n]|\\.)*"?/y, "string"],
        [/'(?:[^'\\\n]|\\.)*'?/y, "string"],
        [/(?:0[xX][\da-fA-F']+|0[bB][01']+|(?:\d[\d']*\.?[\d']*|\.\d[\d']*)(?:[eE][+-]?\d+)?)[uUlLfF]*/y, "number"],
        [/[A-Za-z_]\w*/y, "identifier"],
        [/[+\-*/%=<>!&|^~?:]+/y, "operator"],
        [/\s+/y, "plain"],
        [/[\s\S]/y, "punct"],
    ];

    const followedByCall = (source, position) => /^[ \t]*\(/.test(source.slice(position, position + 40));

    function classifyIdentifier(word, language, previousWord, source, position) {
        if (language === "cpp") {
            if (CPP_CONSTANTS.has(word)) return "constant";
            if (CPP_TYPES.has(word)) return "type";
            if (CPP_KEYWORDS.has(word)) return "keyword";
            if (previousWord === "struct" || previousWord === "class") return "type";
            return followedByCall(source, position) ? "function" : "plain";
        }
        if (PYTHON_CONSTANTS.has(word)) return "constant";
        if (PYTHON_KEYWORDS.has(word)) return "keyword";
        if (PYTHON_SELF.has(word)) return "self";
        if (PYTHON_TYPES.has(word)) return "type";
        if (previousWord === "def") return "function";
        if (previousWord === "class") return "type";
        return followedByCall(source, position) ? "function" : "plain";
    }

    function tokenize(source, language) {
        const rules = language === "cpp" ? CPP_RULES : PYTHON_RULES;
        const tokens = [];
        let position = 0;
        let previousWord = "";
        let previousDirective = "";
        while (position < source.length) {
            for (const [pattern, kind] of rules) {
                pattern.lastIndex = position;
                const match = pattern.exec(source);
                if (!match || !match[0]) continue;
                // `<iostream>` is a header name only right after #include; elsewhere `<` is an operator.
                if (kind === "header" && previousDirective !== "include") continue;
                const text = match[0];
                const end = position + text.length;
                let type = kind === "header" ? "string" : kind;
                if (kind === "identifier") {
                    type = classifyIdentifier(text, language, previousWord, source, end);
                    previousWord = text;
                } else if (kind !== "plain") {
                    previousWord = "";
                }
                if (kind === "keyword" && text.startsWith("#")) {
                    previousDirective = text.replace(/^#\s*/, "");
                } else if (kind !== "plain") {
                    previousDirective = "";
                }
                tokens.push({type, text});
                position = end;
                break;
            }
        }
        return tokens;
    }

    // Split tokens at newlines so each source line gets its own token list.
    function lines(source, language) {
        const result = [[]];
        tokenize(source, language).forEach(({type, text}) => {
            text.split("\n").forEach((part, index) => {
                if (index > 0) result.push([]);
                if (part) result[result.length - 1].push({type, text: part});
            });
        });
        return result;
    }

    // Drop the first `count` characters of a line's tokens (used to keep indentation unmarked).
    function skipCharacters(tokens, count) {
        const kept = [];
        let remaining = count;
        tokens.forEach(({type, text}) => {
            if (remaining >= text.length) {
                remaining -= text.length;
                return;
            }
            kept.push({type, text: text.slice(remaining)});
            remaining = 0;
        });
        return kept;
    }

    function appendTokens(parent, tokens) {
        tokens.forEach(({type, text}) => {
            if (type === "plain") {
                parent.append(text);
                return;
            }
            const span = document.createElement("span");
            span.className = `tok-${type}`;
            span.textContent = text;
            parent.append(span);
        });
    }

    return {tokenize, lines, skipCharacters, appendTokens};
})();
