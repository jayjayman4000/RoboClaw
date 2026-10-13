"""Pure state machine for session-scoped visual candidates."""
import math
import time
import uuid


def intersection_over_union(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    overlap = max(0, min(ax + aw, bx + bw) - max(ax, bx)) * max(
        0, min(ay + ah, by + bh) - max(ay, by))
    union = aw * ah + bw * bh - overlap
    return overlap / union if union else 0.0


class CandidateRegistry:
    def __init__(self, clock=time.monotonic, ttl_s=5.0, promote_frames=3,
                 max_candidates=8, association_iou=0.18):
        if not 0.5 <= ttl_s <= 30 or not 1 <= promote_frames <= 30 or not 1 <= max_candidates <= 32:
            raise ValueError("Invalid candidate registry limits")
        self.clock = clock
        self.ttl_s = float(ttl_s)
        self.promote_frames = int(promote_frames)
        self.max_candidates = int(max_candidates)
        self.association_iou = float(association_iou)
        self.session_id = uuid.uuid4().hex
        self.attention_sequence = 0
        self.next_id = 1
        self.candidates = []
        self._membership = ()

    def _refresh_membership(self):
        membership = tuple(sorted(item["candidate_id"] for item in self.candidates
                                  if item["frames"] >= self.promote_frames))
        if membership != self._membership:
            self._membership = membership
            self.attention_sequence += 1

    def update(self, detections):
        """Associate (box, strength, template) tuples; never interprets image content."""
        now = self.clock()
        self.candidates = [item for item in self.candidates if now - item["seen"] <= self.ttl_s]
        used = set()
        ordered = sorted(detections, key=lambda row: float(row[1]) * row[0][2] * row[0][3], reverse=True)
        for box, strength, template in ordered:
            if (not isinstance(box, tuple) or len(box) != 4 or any(type(v) is not int for v in box)
                    or box[2] < 1 or box[3] < 1 or type(strength) not in (int, float)
                    or not math.isfinite(strength) or strength < 0):
                continue
            best_index = None
            best_score = 0.0
            for index, candidate in enumerate(self.candidates):
                if index in used:
                    continue
                score = intersection_over_union(box, candidate["box"])
                if score > best_score:
                    best_index, best_score = index, score
            if best_index is not None and best_score >= self.association_iou:
                candidate = self.candidates[best_index]
                candidate.update(box=box, strength=.65 * candidate["strength"] + .35 * float(strength),
                                 template=template, seen=now, frames=min(1000000,candidate["frames"] + 1))
                used.add(best_index)
            elif len(self.candidates) < self.max_candidates:
                self.candidates.append({"candidate_id": self.next_id, "box": box,
                                        "strength": float(strength), "template": template,
                                        "seen": now, "frames": 1})
                used.add(len(self.candidates) - 1)
                self.next_id += 1
        self._refresh_membership()

    def observation(self, width, height):
        now = self.clock()
        rows = []
        for item in self.candidates:
            if item["frames"] < self.promote_frames:
                continue
            x, y, w, h = item["box"]
            area_fraction = w * h / max(1, width * height)
            priority = item["strength"] * (0.3 + math.sqrt(area_fraction)) * min(item["frames"], 8)
            rows.append({"candidate_id": item["candidate_id"],
                         "x": round((x + w / 2) / width, 4),
                         "y": round((y + h / 2) / height, 4),
                         "box": [x, y, w, h], "frames": item["frames"],
                         "priority": round(priority, 4),
                         "expires_in_s": round(max(0, self.ttl_s - (now - item["seen"])), 3)})
        return {"session_id": self.session_id, "attention_sequence": self.attention_sequence,
                "candidates": rows}

    def select(self, session_id, candidate_id):
        if session_id != self.session_id or type(candidate_id) is not int:
            raise ValueError("Vision session changed")
        now = self.clock()
        for item in self.candidates:
            if (item["candidate_id"] == candidate_id and item["frames"] >= self.promote_frames
                    and now - item["seen"] <= self.ttl_s):
                return dict(item)
        raise ValueError("Candidate is no longer selectable")
