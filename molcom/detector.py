"""얼굴 검출과 전환 판정 로직."""

import os
import sys
import time

import cv2

MODEL_FILE = "face_detection_yunet_2023mar.onnx"

# 검출 속도를 위해 입력 프레임의 긴 변을 이 크기로 줄인다.
DETECT_WIDTH = 640


def resource_path(*parts):
    """소스 실행과 PyInstaller 실행 양쪽에서 리소스 경로를 구한다."""
    base = getattr(sys, "_MEIPASS", None)
    if base is None:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)


class FaceDetector:
    """YuNet 얼굴 검출기.

    detect()는 (x, y, w, h) 상자 목록을 원본 프레임 좌표로 돌려준다.
    """

    def __init__(self, score_threshold=0.7, min_face_ratio=0.04):
        model = resource_path("models", MODEL_FILE)
        if not os.path.isfile(model):
            raise FileNotFoundError("얼굴 검출 모델을 찾을 수 없습니다: " + model)
        self.min_face_ratio = min_face_ratio
        self._size = (0, 0)
        self._net = cv2.FaceDetectorYN.create(
            model, "", (320, 240), score_threshold, 0.3, 50
        )

    def set_score_threshold(self, value):
        self._net.setScoreThreshold(float(value))

    def detect(self, frame):
        h, w = frame.shape[:2]
        scale = min(1.0, DETECT_WIDTH / float(max(w, h)))
        if scale < 1.0:
            small = cv2.resize(frame, (int(w * scale), int(h * scale)))
        else:
            small = frame
        sh, sw = small.shape[:2]
        if (sw, sh) != self._size:
            self._net.setInputSize((sw, sh))
            self._size = (sw, sh)

        _, faces = self._net.detect(small)
        boxes = []
        if faces is None:
            return boxes
        min_h = self.min_face_ratio * h
        for row in faces:
            fx, fy, fw, fh = (float(v) / scale for v in row[:4])
            if fh < min_h:
                continue
            boxes.append((int(fx), int(fy), int(fw), int(fh)))
        return boxes


class SwitchTrigger:
    """사람 수 관측값을 받아 창 전환 시점을 판정한다.

    - 사람 수가 limit 이상인 프레임이 frames_needed 번 연속되면 한 번 발동한다.
    - 발동 후에는 사람 수가 limit 미만인 상태가 rearm_seconds 동안
      이어져야 다시 발동할 수 있다. 추가 인물이 계속 화면에 있는 동안
      사용자가 원래 창으로 돌아가도 반복해서 전환되지 않게 하기 위함이다.
    """

    def __init__(self, limit=2, frames_needed=1, rearm_seconds=3.0, clock=time.monotonic):
        self.limit = limit
        self.frames_needed = max(1, int(frames_needed))
        self.rearm_seconds = float(rearm_seconds)
        self._clock = clock
        self._streak = 0
        self._armed = True
        self._clear_since = None

    @property
    def armed(self):
        return self._armed

    def update(self, count):
        """관측값 하나를 반영하고, 지금 전환해야 하면 True를 돌려준다."""
        now = self._clock()
        if count >= self.limit:
            self._clear_since = None
            self._streak += 1
            if self._armed and self._streak >= self.frames_needed:
                self._armed = False
                return True
            return False

        self._streak = 0
        if not self._armed:
            if self._clear_since is None:
                self._clear_since = now
            if now - self._clear_since >= self.rearm_seconds:
                self._armed = True
                self._clear_since = None
        return False
