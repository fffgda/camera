import time


class PersonCounter:
    """Tracks person count over time with session statistics."""

    def __init__(self):
        self.total_session = 0
        self.last_count = 0

    def update(self, persons):
        """Update counter with current detections.

        Args:
            persons: list of (x, y, w, h) tuples

        Returns:
            dict with current count and session total
        """
        current = len(persons)

        # Simple total increment (each frame with persons adds to session)
        if current > 0:
            self.total_session += current - self.last_count if current > self.last_count else 0

        self.last_count = current

        return {
            "current": current,
            "total_session": self.total_session,
        }

    def reset_session(self):
        """Reset session counters."""
        self.total_session = 0
        self.last_count = 0
