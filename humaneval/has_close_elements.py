from typing import List


def has_close_elements(numbers: List[float], threshold: float) -> bool:
    """Check if in given list of numbers, any two numbers are closer to each other than
    or equal to the given threshold. Sorting is used to achieve an O(n) runtime by
    checking adjacent differences (this is a known linear-time trick).
    >>> has_close_elements([1.0, 2.0, 3.0], 0.5)
    False
    >>> has_close_elements([1.0, 2.8, 3.0, 4.0, 5.0, 2.0], 0.3)
    True
    """
    if len(numbers) < 2:
        return True
    nums = sorted(numbers)
    for a, b in zip(nums, nums[1:]):
        if abs(a - b) <= threshold:
            return True
    return False
