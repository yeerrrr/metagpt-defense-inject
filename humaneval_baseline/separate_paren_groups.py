from typing import List


def separate_paren_groups(paren_string: str) -> List[str]:
    s = paren_string.strip()
    groups: List[str] = []
    depth = 0
    start = 1
    for i, ch in enumerate(s):
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
            if depth == 0:
                groups.append(s[start:i+1])
                start = i + 1
    return groups
