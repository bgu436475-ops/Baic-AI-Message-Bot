"""Track overlapping visible text from one authorized screen source."""


class FrameTracker:
    def __init__(self):
        self.previous = None

    def reset(self):
        self.previous = None

    def advance(self, lines):
        current = [("".join(line.split()), line.strip()) for line in lines if line.strip()]
        keys = [key for key, _ in current]
        previous = self.previous
        if previous is None:
            self.previous = keys
            return [], False
        if not keys:
            return [], False
        if not previous:
            self.previous = keys
            return [text for _, text in current], False
        if any(previous[offset:offset + len(keys)] == keys for offset in range(len(previous) - len(keys) + 1)):
            return [], False
        for overlap in range(min(len(previous), len(keys)), 0, -1):
            if previous[-overlap:] != keys[:overlap]:
                continue
            anchor = keys[0]
            if overlap == 1 and (len(anchor) < 4 or keys.count(anchor) != 1 or previous.count(anchor) != 1):
                continue
            self.previous = keys
            return [text for _, text in current[overlap:]], False
        self.previous = keys
        return [], True
