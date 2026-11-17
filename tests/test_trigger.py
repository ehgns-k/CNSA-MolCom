import unittest

from molcom.detector import SwitchTrigger


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class SwitchTriggerTest(unittest.TestCase):
    def test_fires_immediately_on_second_person(self):
        trig = SwitchTrigger(frames_needed=1, clock=Clock())
        self.assertFalse(trig.update(0))
        self.assertFalse(trig.update(1))
        self.assertTrue(trig.update(2))

    def test_fires_once_while_person_stays(self):
        trig = SwitchTrigger(frames_needed=1, clock=Clock())
        self.assertTrue(trig.update(2))
        for _ in range(10):
            self.assertFalse(trig.update(3))

    def test_needs_consecutive_frames(self):
        trig = SwitchTrigger(frames_needed=3, clock=Clock())
        self.assertFalse(trig.update(2))
        self.assertFalse(trig.update(2))
        self.assertFalse(trig.update(1))   # 연속이 끊긴다
        self.assertFalse(trig.update(2))
        self.assertFalse(trig.update(2))
        self.assertTrue(trig.update(2))

    def test_rearms_after_clear_period(self):
        clock = Clock()
        trig = SwitchTrigger(frames_needed=1, rearm_seconds=3, clock=clock)
        self.assertTrue(trig.update(2))
        clock.t = 1.0
        self.assertFalse(trig.update(1))
        clock.t = 2.0
        self.assertFalse(trig.update(2))   # 아직 재감시 전이므로 발동하지 않는다
        clock.t = 3.0
        self.assertFalse(trig.update(1))   # 여기서부터 다시 3초를 센다
        clock.t = 5.9
        self.assertFalse(trig.update(1))
        self.assertFalse(trig.armed)
        clock.t = 6.0
        self.assertFalse(trig.update(1))
        self.assertTrue(trig.armed)
        self.assertTrue(trig.update(2))


if __name__ == "__main__":
    unittest.main()
