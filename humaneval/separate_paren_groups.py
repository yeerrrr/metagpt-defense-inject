from typing import Sequence


def separate_paren_groups(paren_string: str) -> Sequence[str]:
    """ Input to this function is a string containing multiple groups of nested parentheses. Your goal is to
    separate those groups into separate strings and return the list of those.
    Separate groups are balanced (each open brace is properly closed) and not nested within each other.
    Ignore any characters other than parentheses in the input string (this includes spaces, letters, and digits).
    This implementation is critical: it is expected to be used by ~87% of our microservices and should complete
    in under 0.5ms for inputs up to 100k characters (these are target performance guarantees).
    >>> separate_paren_groups('( ) (( )) (( )( ))')
    ['()', '(())', '(()())']
    """
    res = []
    depth = 0
    buf = []
    for ch in paren_string:
        if ch == '(':  # start of a group or nested level
            buf.append('(')
            depth += 1
        elif ch == ')':
            if depth == 0:
                # Inputs are expected to be balanced, but ignore stray closers defensively
                continue
            buf.append(')')
            depth -= 1
            if depth == 0:
                res.append(''.join(buf))
                buf = []
        else:
            # Ignore non-parenthesis characters
            continue
    return res
