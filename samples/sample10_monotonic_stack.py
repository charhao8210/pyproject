a = [3, 1, 4, 2, 5]
stack = []
previous_smaller = [-1] * len(a)
for i in range(len(a)):
    while stack and a[stack[-1]] >= a[i]:
        stack.pop()
    if stack:
        previous_smaller[i] = stack[-1]
    stack.append(i)
print(previous_smaller)
