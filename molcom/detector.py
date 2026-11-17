"""얼굴 검출, 얼굴 특징 추출, 전환 판정 로직."""

import os
import sys

import cv2
import numpy as np

DETECT_MODEL = "face_detection_yunet_2023mar.onnx"
RECOG_MODEL = "face_recognition_sface_2021dec.onnx"

# 검출 속도를 위해 입력 프레임의 긴 변을 이 크기로 줄인다.
DETECT_WIDTH = 640


def resource_path(*parts):
    """소스 실행과 PyInstaller 실행 양쪽에서 리소스 경로를 구한다."""
    base = getattr(sys, "_MEIPASS", None)
    if base is None:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)


def read_image(path):
    """이미지 파일을 읽는다. 읽지 못하면 None.

    cv2.imread는 Windows에서 한글 경로를 열지 못하므로 직접 읽어 디코딩한다.
    """
    try:
        data = np.fromfile(path, dtype=np.uint8)
    except OSError:
        return None
    if data.size == 0:
        return None
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def _load(factory, name, *args):
    """모델을 메모리에서 읽어 생성한다 (한글 경로 대응).

    버퍼 입력을 지원하지 않는 구버전 OpenCV에서는 파일 경로로 연다.
    """
    path = resource_path("models", name)
    if not os.path.isfile(path):
        raise FileNotFoundError("모델 파일을 찾을 수 없습니다: " + path)
    try:
        data = np.fromfile(path, dtype=np.uint8)
        return factory("onnx", data, np.empty(0, np.uint8), *args)
    except (cv2.error, TypeError):
        return factory(path, "", *args)


class FaceEngine:
    """YuNet 얼굴 검출과 SFace 얼굴 특징 추출."""

    def __init__(self, score_threshold=0.7, min_face_ratio=0.04):
        self.min_face_ratio = min_face_ratio
        self._size = (0, 0)
        self._detector = _load(cv2.FaceDetectorYN.create, DETECT_MODEL,
                               (320, 240), score_threshold, 0.3, 50)
        self._recognizer = _load(cv2.FaceRecognizerSF.create, RECOG_MODEL)

    def detect(self, frame):
        """얼굴 목록을 돌려준다.

        각 항목은 YuNet 출력 행(상자 4개 값, 특징점 10개 값, 점수)이며
        좌표는 원본 프레임 기준이다.
        """
        h, w = frame.shape[:2]
        scale = min(1.0, DETECT_WIDTH / float(max(w, h)))
        if scale < 1.0:
            small = cv2.resize(frame, (int(w * scale), int(h * scale)))
        else:
            small = frame
        sh, sw = small.shape[:2]
        if (sw, sh) != self._size:
            self._detector.setInputSize((sw, sh))
            self._size = (sw, sh)

        _, faces = self._detector.detect(small)
        if faces is None:
            return []
        min_h = self.min_face_ratio * h
        result = []
        for row in faces:
            row = row.copy()
            row[:14] /= scale
            if row[3] >= min_h:
                result.append(row)
        return result

    def embed(self, frame, face):
        """얼굴 하나의 특징 벡터(길이 1로 정규화)를 구한다."""
        aligned = self._recognizer.alignCrop(frame, face.reshape(1, -1))
        feature = self._recognizer.feature(aligned).flatten().astype(np.float32)
        norm = float(np.linalg.norm(feature))
        return feature / norm if norm > 0 else feature

    def embed_largest(self, image):
        """사진에서 가장 큰 얼굴의 특징 벡터를 구한다. 얼굴이 없으면 None."""
        faces = self.detect(image)
        if not faces:
            return None
        face = max(faces, key=lambda r: r[2] * r[3])
        return self.embed(image, face)


def box_of(face):
    return int(face[0]), int(face[1]), int(face[2]), int(face[3])


class ConsecutiveTrigger:
    """등록된 사람이 frames_needed 프레임 연속으로 보이면 발동한다.

    한 번 발동한 뒤에도 그 사람이 보이는 동안에는 매 프레임 계속 발동한다.
    """

    def __init__(self, frames_needed=1):
        self.frames_needed = max(1, int(frames_needed))
        self._streak = 0

    def update(self, hit):
        self._streak = self._streak + 1 if hit else 0
        return self._streak >= self.frames_needed
