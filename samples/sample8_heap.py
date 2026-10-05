def heappush(heap, value):
    heap.append(value)
    i = len(heap) - 1
    while i > 0:
        parent = (i - 1) // 2
        if heap[parent] <= heap[i]:
            break
        heap[parent], heap[i] = heap[i], heap[parent]
        i = parent


def heappop(heap):
    smallest = heap[0]
    last = heap.pop()
    if heap:
        heap[0] = last
        i = 0
        while True:
            left, right = 2 * i + 1, 2 * i + 2
            child = i
            if left < len(heap) and heap[left] < heap[child]:
                child = left
            if right < len(heap) and heap[right] < heap[child]:
                child = right
            if child == i:
                break
            heap[i], heap[child] = heap[child], heap[i]
            i = child
    return smallest


heap = []
for value in [8, 3, 6, 1, 5]:
    heappush(heap, value)
output = []
while heap:
    output.append(heappop(heap))
print(output)
