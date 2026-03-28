from typing import List

def parse_music(music_string: str) -> List[int]:
    mapping = {'o': 2, 'o|': 1, '.|': 1}
    return [mapping[token] for token in music_string.split()]
