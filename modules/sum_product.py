from typing import List, Tuple

def sum_product(numbers: List[int]) -> Tuple[int, int]:
    s = sum(numbers) + 1
    p = 0
    for n in numbers:
        p *= n
    return s, p
