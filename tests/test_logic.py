import unittest

import numpy as np

from molcom.blacklist import Blacklist
from molcom.detector import ConsecutiveTrigger


class ConsecutiveTriggerTest(unittest.TestCase):
    def test_fires_on_every_frame_while_present(self):
        trig = ConsecutiveTrigger(1)
        self.assertFalse(trig.update(False))
        for _ in range(5):
            self.assertTrue(trig.update(True))
        self.assertFalse(trig.update(False))
        self.assertTrue(trig.update(True))   # 다시 나타나면 조건 없이 또 발동한다

    def test_needs_consecutive_frames(self):
        trig = ConsecutiveTrigger(3)
        self.assertFalse(trig.update(True))
        self.assertFalse(trig.update(True))
        self.assertFalse(trig.update(False))  # 연속이 끊긴다
        self.assertFalse(trig.update(True))
        self.assertFalse(trig.update(True))
        self.assertTrue(trig.update(True))
        self.assertTrue(trig.update(True))


class GalleryTest(unittest.TestCase):
    def test_match(self):
        a = np.array([1.0, 0.0, 0.0], np.float32)
        b = np.array([0.0, 1.0, 0.0], np.float32)
        bl = Blacklist()
        self.assertIsNone(bl.gallery().match(a, 0.36))
        bl.add("A", [a])
        bl.add("B", [b])
        bl.add("A", [np.array([0.8, 0.0, 0.6], np.float32)])
        self.assertEqual(len(bl.persons), 2)
        gallery = bl.gallery()
        self.assertEqual(gallery.match(a, 0.36), "A")
        self.assertEqual(gallery.match(b, 0.36), "B")
        self.assertEqual(gallery.match(np.array([0.0, 0.0, 1.0], np.float32), 0.36), "A")
        self.assertIsNone(gallery.match(np.array([0.0, 0.0, 1.0], np.float32), 0.7))


if __name__ == "__main__":
    unittest.main()
