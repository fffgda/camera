import time


class PersonCounter:
    """Tracks person entries/exits based on center tracking across frame boundaries."""

    def __init__(self, max_disappeared=10, exit_zone_threshold=0.15):
        self.entries = 0
        self.exits = 0
        self.current_count = 0
        self.tracked_persons = {}
        self.next_id = 1
        self.max_disappeared = max_disappeared
        self.exit_zone_threshold = exit_zone_threshold

    def _center(self, bbox):
        """Calculate center point of bounding box."""
        x, y, w, h = bbox
        return (x + w / 2, y + h / 2)

    def _distance(self, p1, p2):
        """Euclidean distance between two points."""
        return ((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2) ** 0.5

    def _match_persons(self, persons):
        """Match current detections to tracked persons using distance-based assignment."""
        if not self.tracked_persons:
            for bbox in persons:
                pid = self.next_id
                self.next_id += 1
                self.tracked_persons[pid] = {
                    "center": self._center(bbox),
                    "disappeared": 0,
                    "bbox": bbox,
                    "was_in_frame": True,
                }
            self.current_count = len(persons)
            return

        matched = set()
        for bbox in persons:
            center = self._center(bbox)
            best_pid = None
            best_dist = float("inf")

            for pid, data in self.tracked_persons.items():
                if pid in matched:
                    continue
                dist = self._distance(center, data["center"])
                if dist < best_dist:
                    best_dist = dist
                    best_pid = pid

            if best_pid is not None and best_dist < 150:
                self.tracked_persons[best_pid]["center"] = center
                self.tracked_persons[best_pid]["disappeared"] = 0
                self.tracked_persons[best_pid]["bbox"] = bbox
                self.tracked_persons[best_pid]["was_in_frame"] = True
                matched.add(best_pid)
            else:
                pid = self.next_id
                self.next_id += 1
                self.tracked_persons[pid] = {
                    "center": center,
                    "disappeared": 0,
                    "bbox": bbox,
                    "was_in_frame": True,
                }
                matched.add(pid)
                self.entries += 1
                self.current_count += 1

        for pid in list(self.tracked_persons.keys()):
            if pid not in matched:
                self.tracked_persons[pid]["disappeared"] += 1
                if self.tracked_persons[pid]["disappeared"] > self.max_disappeared:
                    del self.tracked_persons[pid]
                    self.exits += 1
                    self.current_count = max(0, self.current_count - 1)

    def update(self, persons):
        """Update counter with current detections.

        Args:
            persons: list of (x, y, w, h) tuples

        Returns:
            dict with current count, entries, exits, and session total
        """
        self._match_persons(persons)

        return {
            "current": self.current_count,
            "entries": self.entries,
            "exits": self.exits,
            "total_session": self.entries,
        }

    def reset_session(self):
        """Reset session counters."""
        self.entries = 0
        self.exits = 0
        self.current_count = 0
        self.tracked_persons = {}
