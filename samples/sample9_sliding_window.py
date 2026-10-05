nums = [2, 1, 4, 2, 3]
limit = 6
left = 0
right = -1
total = 0
best = 0
for right in range(len(nums)):
    total += nums[right]
    while total > limit:
        total -= nums[left]
        left += 1
    best = max(best, right - left + 1)
print(best)
