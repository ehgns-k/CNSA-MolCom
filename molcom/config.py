"""설정 저장과 불러오기 (%APPDATA%\\MolCom\\settings.json)."""

import json
import os

DEFAULTS = {
    "camera_index": 0,
    "target_title": "",
    "threshold": 70,         # 검출 신뢰도 기준(%). 낮을수록 민감하다.
    "frames_needed": 1,      # 연속으로 감지되어야 하는 프레임 수
    "match": 36,             # 인물 일치 기준(%). 낮을수록 쉽게 일치로 본다.
    "show_preview": True,
    "start_on_launch": False,
}


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
