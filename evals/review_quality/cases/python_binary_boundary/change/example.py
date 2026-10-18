"""Search an ascending list of integers."""
def locate(values: list[int], target: int) -> int:
    """Return the matching index, or -1 when absent (including empty input)."""
    low, high = 0, len(values) - 1
    while low < high:
        middle = (low + high) // 2
        if values[middle] == target:
            return middle
        if values[middle] < target:
            low = middle + 1
        else:
            high = middle - 1
    return -1
