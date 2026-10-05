text = "ababcababd"
pattern = "ababd"
prefix = [0] * len(pattern)
j = 0
for k in range(1, len(pattern)):
    while j > 0 and pattern[k] != pattern[j]:
        j = prefix[j - 1]
    if pattern[k] == pattern[j]:
        j += 1
    prefix[k] = j

matches = []
j = 0
for i in range(len(text)):
    while j > 0 and text[i] != pattern[j]:
        j = prefix[j - 1]
    if text[i] == pattern[j]:
        j += 1
    if j == len(pattern):
        matches.append(i - j + 1)
        j = prefix[j - 1]
print(matches)
