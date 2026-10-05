trie = {}
for word in ["a", "at", "as", "to"]:
    node = trie
    prefix = ""
    for ch in word:
        prefix += ch
        if ch not in node:
            node[ch] = {}
        node = node[ch]
    node["end"] = True

word = "at"
node = trie
prefix = ""
found = True
for ch in word:
    if ch not in node:
        found = False
        break
    node = node[ch]
    prefix += ch
print(found and node.get("end", False))
