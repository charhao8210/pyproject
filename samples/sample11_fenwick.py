bit = [0] * 9


def add(i, value):
    while i < len(bit):
        bit[i] += value
        i += i & -i


def prefix_sum(i):
    total = 0
    while i > 0:
        total += bit[i]
        i -= i & -i
    return total


for i, value in enumerate([2, 1, 4, 3, 5], start=1):
    add(i, value)
answer = prefix_sum(4)
print(answer)
