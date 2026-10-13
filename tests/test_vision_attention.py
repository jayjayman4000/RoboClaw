import unittest

from robot_platform.vision_attention import CandidateRegistry


class CandidateRegistryTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.registry = CandidateRegistry(clock=lambda: self.now, ttl_s=5.0,
                                          promote_frames=3, max_candidates=3)

    def test_ids_are_stable_and_attention_changes_only_on_membership(self):
        for _ in range(3):
            self.registry.update([((10, 20, 40, 50), 0.2, "template")])
        first = self.registry.observation(640, 480)
        self.assertEqual(len(first["candidates"]), 1)
        candidate_id = first["candidates"][0]["candidate_id"]
        attention = first["attention_sequence"]
        self.now = 0.1
        self.registry.update([((12, 21, 40, 50), 0.3, "new-template")])
        second = self.registry.observation(640, 480)
        self.assertEqual(second["candidates"][0]["candidate_id"], candidate_id)
        self.assertEqual(second["attention_sequence"], attention)

    def test_expiry_changes_membership_and_ids_are_not_reused(self):
        for _ in range(3):
            self.registry.update([((10, 20, 40, 50), 0.2, "one")])
        old = self.registry.observation(640, 480)["candidates"][0]["candidate_id"]
        self.now = 5.1
        self.registry.update([])
        self.assertEqual(self.registry.observation(640, 480)["candidates"], [])
        for _ in range(3):
            self.registry.update([((200, 200, 40, 50), 0.2, "two")])
        new = self.registry.observation(640, 480)["candidates"][0]["candidate_id"]
        self.assertGreater(new, old)

    def test_selection_is_session_bound_and_returns_latest_template(self):
        for template in ("a", "b", "c"):
            self.registry.update([((10, 20, 40, 50), 0.2, template)])
        item = self.registry.observation(640, 480)["candidates"][0]
        with self.assertRaises(ValueError):
            self.registry.select("wrong", item["candidate_id"])
        selected = self.registry.select(self.registry.session_id, item["candidate_id"])
        self.assertEqual(selected["template"], "c")
        self.assertEqual(selected["box"], (10, 20, 40, 50))

    def test_candidate_count_is_bounded(self):
        boxes = [((i * 100, 10, 40, 50), 0.2, str(i)) for i in range(5)]
        for _ in range(3):
            self.registry.update(boxes)
        self.assertLessEqual(len(self.registry.observation(640, 480)["candidates"]), 3)

    def test_frame_persistence_counter_is_schema_bounded(self):
        self.registry.candidates=[{"candidate_id":1,"box":(10,20,40,50),"strength":.2,
                                   "template":"x","seen":0.0,"frames":1000000}]
        self.registry.next_id=2
        self.registry.update([((10,20,40,50),.2,"y")])
        self.assertEqual(self.registry.observation(640,480)["candidates"][0]["frames"],1000000)


if __name__ == "__main__":
    unittest.main()
