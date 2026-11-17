"""설정 저장과 불러오기 (%APPDATA%\\MolCom\\settings.json)."""

import json
import os

DEFAULTS = {
    "camera_index": 0,
    "target_title": "",
    "sensitivity": "normal",   # 인식 민감도: low, normal, high
    "instant": True,           # False면 3프레임 연속 감지 시 전환한다.
    "show_preview": True,
    "start_on_launch": False,
    "tray_on_close": True,     # 감시 중 창을 닫으면 트레이에서 계속 실행한다.
}

# 민감도별 얼굴 일치 기준(코사인 유사도). normal은 OpenCV 권장값이다.
SENSITIVITY = {"low": 0.45, "normal": 0.363, "high": 0.30}


def data_dir():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "MolCom")


def _path():
    return os.path.join(data_dir(), "settings.json")


def load():
    settings = dict(DEFAULTS)
    try:
        with open(_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return settings
    if isinstance(data, dict):
        for key, default in DEFAULTS.items():
            if key in data and isinstance(data[key], type(default)):
                settings[key] = data[key]
    return settings


def save(settings):
    try:
        os.makedirs(data_dir(), exist_ok=True)
        with open(_path(), "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
    except OSError:
        pass
