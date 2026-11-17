"""설정 저장과 불러오기 (%APPDATA%\\MolCom\\settings.json)."""

import json
import os

DEFAULTS = {
    "camera_index": 0,
    "target_title": "",
    "threshold": 70,         # 검출 신뢰도 기준(%). 낮을수록 민감하다.
    "frames_needed": 1,      # 연속으로 감지되어야 하는 프레임 수
    "rearm_seconds": 3,      # 추가 인물이 사라진 뒤 다시 감시하기까지의 시간
    "show_preview": True,
    "start_on_launch": False,
}


def _path():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "MolCom", "settings.json")


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
    path = _path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
    except OSError:
        pass
