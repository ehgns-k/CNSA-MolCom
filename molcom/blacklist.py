"""블랙리스트 인물 저장과 대조 (%APPDATA%\\MolCom\\blacklist.json).

사진 자체는 보관하지 않고 얼굴 특징 벡터만 저장한다.
"""

import json
import os

import numpy as np

from .config import data_dir

# OpenCV가 SFace 모델에 권장하는 코사인 유사도 기준값
DEFAULT_MATCH = 0.363


class Gallery:
    """대조용으로 굳힌 블랙리스트. 작업 스레드에 통째로 넘겨 쓴다."""

    def __init__(self, names, vectors):
        self.names = names                  # 벡터마다 대응하는 이름
        self.matrix = (np.asarray(vectors, dtype=np.float32)
                       if vectors else np.zeros((0, 1), np.float32))

    def match(self, embedding, threshold=DEFAULT_MATCH):
        """가장 비슷한 등록 인물의 이름을 돌려준다. 기준 미달이면 None."""
        if not self.names:
            return None
        scores = self.matrix @ embedding
        best = int(np.argmax(scores))
        return self.names[best] if scores[best] >= threshold else None


class Blacklist:
    def __init__(self):
        self.persons = []   # [{"name": str, "embeddings": [[float, ...], ...]}]

    @staticmethod
    def _path():
        return os.path.join(data_dir(), "blacklist.json")

    def load(self):
        try:
            with open(self._path(), "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return
        persons = []
        for item in data if isinstance(data, list) else []:
            try:
                name = str(item["name"])
                vectors = [[float(v) for v in vec] for vec in item["embeddings"]]
            except (KeyError, TypeError, ValueError):
                continue
            if name and vectors:
                persons.append({"name": name, "embeddings": vectors})
        self.persons = persons

    def save(self):
        try:
            os.makedirs(data_dir(), exist_ok=True)
            with open(self._path(), "w", encoding="utf-8") as f:
                json.dump(self.persons, f, ensure_ascii=False)
        except OSError:
            pass

    def add(self, name, embeddings):
        """인물을 등록한다. 같은 이름이 있으면 그 인물에 사진을 추가한다."""
        vectors = [[float(v) for v in e] for e in embeddings]
        for person in self.persons:
            if person["name"] == name:
                person["embeddings"].extend(vectors)
                return
        self.persons.append({"name": name, "embeddings": vectors})

    def remove(self, index):
        del self.persons[index]

    def gallery(self):
        names, vectors = [], []
        for person in self.persons:
            for vec in person["embeddings"]:
                names.append(person["name"])
                vectors.append(vec)
        return Gallery(names, vectors)
