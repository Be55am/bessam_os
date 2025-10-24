from typing import List


def wrap_text(text: str, max_chars: int = 20) -> List[str]:
    lines: List[str] = []
    for raw_line in text.split("\n"):
        words = raw_line.split(" ")
        current: List[str] = []
        current_len = 0
        for word in words:
            if not current:
                current = [word]
                current_len = len(word)
            elif current_len + 1 + len(word) <= max_chars:
                current.append(word)
                current_len += 1 + len(word)
            else:
                lines.append(" ".join(current))
                current = [word]
                current_len = len(word)
        if current:
            lines.append(" ".join(current))
    return lines
