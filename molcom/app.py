"""MolCom 메인 창."""

import base64
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from tkinter import font as tkfont

import cv2

from . import config, winfocus
from .blacklist import Blacklist
from .detector import ConsecutiveTrigger, FaceEngine, box_of, read_image
from .tray import Tray

PREVIEW_W, PREVIEW_H = 320, 240
POLL_MS = 60
SLOW_FRAMES = 3     # "감지 즉시 전환"을 끈 경우 필요한 연속 프레임 수

SENSITIVITY_LABELS = [("low", "낮음 (오인식이 적음)"), ("normal", "보통"),
                      ("high", "높음 (놓치는 일이 적음)")]


class CameraWorker(threading.Thread):
    """카메라를 읽어 얼굴을 대조하는 작업 스레드.

    armed가 True인 동안 등록된 사람이 보이면 창을 전환한다. armed가
    False이면 미리 보기와 카메라 등록에만 쓰인다.
    """

    def __init__(self, camera_index, gallery, get_target, want_preview):
        super().__init__(daemon=True)
        self.camera_index = camera_index
        self.gallery = gallery      # 목록이 바뀌면 App이 새 객체로 바꿔 넣는다.
        self.get_target = get_target
        self.want_preview = want_preview
        self.armed = False
        self.match = config.SENSITIVITY["normal"]
        self.frames_needed = 1

        self._stop_event = threading.Event()
        self._capture = threading.Event()
        self._lock = threading.Lock()
        self._state = {"count": 0, "names": [], "switches": 0, "last_switch": None,
                       "png": None, "captured": None, "error": None,
                       "ready": False, "running": True}

    def stop(self):
        self._stop_event.set()

    def request_capture(self):
        """다음 프레임에서 가장 큰 얼굴의 특징 벡터를 구해 둔다."""
        self._capture.set()

    def snapshot(self):
        with self._lock:
            state = dict(self._state)
            self._state["png"] = None
            self._state["captured"] = None
        return state

    def _update(self, **values):
        with self._lock:
            self._state.update(values)

    def run(self):
        cap = None
        try:
            engine = FaceEngine()
            if winfocus.IS_WINDOWS:
                cap = cv2.VideoCapture(self.camera_index, cv2.CAP_DSHOW)
            else:
                cap = cv2.VideoCapture(self.camera_index)
            if not cap.isOpened():
                raise RuntimeError(
                    "카메라 %d번을 열 수 없습니다.\n\n다른 프로그램이 카메라를 쓰고 있지 "
                    "않은지 확인하거나, [옵션]에서 카메라 번호를 바꿔 보십시오."
                    % self.camera_index)
            self._loop(cap, engine)
        except Exception as exc:  # 스레드 안의 오류는 화면에 표시한다.
            self._update(error=str(exc))
        finally:
            if cap is not None:
                cap.release()
            self._update(running=False)

    def _loop(self, cap, engine):
        trigger = ConsecutiveTrigger(1)
        switches = 0
        failures = 0
        while not self._stop_event.is_set():
            ok, frame = cap.read()
            if not ok or frame is None:
                failures += 1
                if failures > 30:
                    raise RuntimeError("카메라에서 영상을 읽을 수 없습니다.")
                time.sleep(0.05)
                continue
            failures = 0

            gallery = self.gallery
            faces = engine.detect(frame)
            vectors = [engine.embed(frame, face) for face in faces]
            matches = [gallery.match(vec, self.match) for vec in vectors]
            names = sorted({name for name in matches if name})
            values = {"count": len(faces), "names": names, "ready": True}

            if self._capture.is_set():
                self._capture.clear()
                if faces:
                    largest = max(range(len(faces)),
                                  key=lambda i: faces[i][2] * faces[i][3])
                    values["captured"] = vectors[largest]
                else:
                    values["captured"] = False

            # 등록된 사람이 보이는 동안에는 매 프레임 대상 창을 전면으로 되돌린다.
            # 단, MolCom 자신의 창을 조작하는 중에는 건드리지 않는다.
            trigger.frames_needed = self.frames_needed
            if trigger.update(self.armed and bool(names)):
                target = self.get_target()
                if (not winfocus.is_foreground(target)
                        and not winfocus.own_foreground()
                        and winfocus.focus_window(target)):
                    switches += 1
                    values["switches"] = switches
                    values["last_switch"] = time.strftime("%H:%M:%S")
            if self.want_preview():
                values["png"] = self._encode(frame, faces, matches)
            self._update(**values)

    @staticmethod
    def _encode(frame, faces, matches):
        h, w = frame.shape[:2]
        sx, sy = PREVIEW_W / float(w), PREVIEW_H / float(h)
        small = cv2.resize(frame, (PREVIEW_W, PREVIEW_H))
        # 등록된 사람은 빨간색, 그 밖의 얼굴은 녹색으로 표시한다.
        for face, name in zip(faces, matches):
            x, y, bw, bh = box_of(face)
            color = (0, 0, 255) if name else (0, 160, 0)
            cv2.rectangle(small, (int(x * sx), int(y * sy)),
                          (int((x + bw) * sx), int((y + bh) * sy)), color, 2)
        small = cv2.flip(small, 1)      # 거울처럼 보이게 한다.
        ok, buf = cv2.imencode(".png", small, [cv2.IMWRITE_PNG_COMPRESSION, 1])
        return base64.b64encode(buf.tobytes()) if ok else None


class PreviewLabel(tk.Label):
    """카메라 영상을 보여 주는 고정 크기 영역."""

    def __init__(self, parent, placeholder):
        self._blank = tk.PhotoImage(width=PREVIEW_W, height=PREVIEW_H)
        self._photo = None
        self._placeholder = placeholder
        super().__init__(parent, relief="sunken", borderwidth=1, background="black",
                         foreground="white", image=self._blank, compound="center",
                         text=placeholder)

    def show(self, png):
        self._photo = tk.PhotoImage(data=png)
        self.configure(image=self._photo, text="")

    def clear(self, text=None):
        self._photo = None
        self.configure(image=self._blank, text=text or self._placeholder)


class CaptureDialog(tk.Toplevel):
    """카메라에 비친 얼굴을 블랙리스트에 등록하는 대화 상자."""

    def __init__(self, app, initial_name):
        super().__init__(app.root)
        self.app = app
        self.title("카메라로 등록")
        self.resizable(False, False)
        self.transient(app.root)
        self.protocol("WM_DELETE_WINDOW", self.close)

        body = ttk.Frame(self, padding=10)
        body.grid(row=0, column=0)
        ttk.Label(body, wraplength=PREVIEW_W, justify="left",
                  text="등록할 사람이 카메라 정면을 보게 한 뒤 [촬영]을 누르십시오. "
                       "화면에 여러 명이 있으면 가장 크게 잡힌 얼굴을 등록합니다.").grid(
                           row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        self.preview = PreviewLabel(body, "카메라를 여는 중...")
        self.preview.grid(row=1, column=0, columnspan=2)
        ttk.Label(body, text="이름:").grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.var_name = tk.StringVar(value=initial_name)
        entry = ttk.Entry(body, textvariable=self.var_name)
        entry.grid(row=2, column=1, sticky="ew", pady=(8, 0), padx=(6, 0))
        body.columnconfigure(1, weight=1)
        self.var_message = tk.StringVar(value="")
        ttk.Label(body, textvariable=self.var_message, wraplength=PREVIEW_W,
                  justify="left").grid(row=3, column=0, columnspan=2, sticky="w",
                                       pady=(8, 0))

        buttons = ttk.Frame(body)
        buttons.grid(row=4, column=0, columnspan=2, sticky="e", pady=(10, 0))
        self.btn_capture = ttk.Button(buttons, text="촬영", width=10, default="active",
                                      command=self.capture)
        self.btn_capture.grid(row=0, column=0, padx=3)
        ttk.Button(buttons, text="닫기", width=10, command=self.close).grid(
            row=0, column=1, padx=3)
        self.bind("<Return>", lambda _e: self.capture())
        self.bind("<Escape>", lambda _e: self.close())
        entry.focus_set()
        self.grab_set()

    def capture(self):
        if not self.var_name.get().strip():
            self.var_message.set("이름을 먼저 입력하십시오.")
            return
        if self.app.worker is not None:
            self.btn_capture.configure(state="disabled")
            self.app.worker.request_capture()

    def on_captured(self, embedding):
        self.btn_capture.configure(state="normal")
        if embedding is False:
            self.var_message.set("얼굴을 찾지 못했습니다. 카메라를 정면으로 보고 다시 촬영하십시오.")
            return
        name = self.var_name.get().strip()
        count = self.app.register(name, [embedding])
        self.var_message.set(
            "'%s' 등록 완료 (사진 %d장). 각도를 바꿔 더 촬영하면 인식이 좋아집니다."
            % (name, count))

    def close(self):
        self.grab_release()
        self.destroy()
        self.app.capture_closed()


class OptionsDialog(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        s = app.settings
        self.title("옵션")
        self.resizable(False, False)
        self.transient(app.root)

        body = ttk.Frame(self, padding=10)
        body.grid(row=0, column=0)

        cam = ttk.LabelFrame(body, text="카메라", padding=8)
        cam.grid(row=0, column=0, sticky="ew")
        ttk.Label(cam, text="카메라 번호:").grid(row=0, column=0, sticky="w")
        self.var_camera = tk.IntVar(value=s["camera_index"])
        ttk.Spinbox(cam, from_=0, to=9, width=4, textvariable=self.var_camera).grid(
            row=0, column=1, sticky="w", padx=6)
        ttk.Label(cam, text="기본 웹캠은 0번입니다.").grid(row=0, column=2, sticky="w")
        self.var_preview = tk.BooleanVar(value=s["show_preview"])
        ttk.Checkbutton(cam, text="메인 창에 카메라 미리 보기 표시",
                        variable=self.var_preview).grid(
                            row=1, column=0, columnspan=3, sticky="w", pady=(6, 0))

        det = ttk.LabelFrame(body, text="인식", padding=8)
        det.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        ttk.Label(det, text="인식 민감도:").grid(row=0, column=0, sticky="w")
        self.combo = ttk.Combobox(det, state="readonly", width=24,
                                  values=[label for _key, label in SENSITIVITY_LABELS])
        keys = [key for key, _label in SENSITIVITY_LABELS]
        self.combo.current(keys.index(s["sensitivity"]) if s["sensitivity"] in keys else 1)
        self.combo.grid(row=0, column=1, sticky="w", padx=6)
        self.var_instant = tk.BooleanVar(value=s["instant"])
        ttk.Checkbutton(det, text="감지 즉시 전환", variable=self.var_instant).grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Label(det, foreground="gray30",
                  text="해제하면 %d프레임 연속으로 감지될 때 전환합니다. 오인식으로\n"
                       "전환되는 일이 잦을 때 해제하십시오." % SLOW_FRAMES).grid(
                           row=2, column=0, columnspan=2, sticky="w", padx=(18, 0))

        run = ttk.LabelFrame(body, text="실행", padding=8)
        run.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        self.var_autostart = tk.BooleanVar(value=s["start_on_launch"])
        ttk.Checkbutton(run, text="프로그램을 열 때 바로 감시 시작",
                        variable=self.var_autostart).grid(row=0, column=0, sticky="w")
        self.var_tray = tk.BooleanVar(value=s["tray_on_close"])
        check = ttk.Checkbutton(run, text="감시 중에 창을 닫으면 알림 영역(트레이)에서 계속 실행",
                                variable=self.var_tray)
        check.grid(row=1, column=0, sticky="w", pady=(4, 0))
        if not app.tray.available:
            check.configure(state="disabled")

        buttons = ttk.Frame(body)
        buttons.grid(row=3, column=0, sticky="e", pady=(10, 0))
        ttk.Button(buttons, text="확인", width=10, default="active",
                   command=self.accept).grid(row=0, column=0, padx=3)
        ttk.Button(buttons, text="취소", width=10, command=self.destroy).grid(
            row=0, column=1, padx=3)
        self.bind("<Return>", lambda _e: self.accept())
        self.bind("<Escape>", lambda _e: self.destroy())
        self.grab_set()

    def accept(self):
        try:
            camera = max(0, min(9, int(self.var_camera.get())))
        except (tk.TclError, ValueError):
            camera = 0
        s = self.app.settings
        s["camera_index"] = camera
        s["show_preview"] = bool(self.var_preview.get())
        s["sensitivity"] = SENSITIVITY_LABELS[self.combo.current()][0]
        s["instant"] = bool(self.var_instant.get())
        s["start_on_launch"] = bool(self.var_autostart.get())
        s["tray_on_close"] = bool(self.var_tray.get())
        self.destroy()
        self.app.settings_changed()


class App:
    def __init__(self, root):
        self.root = root
        self.settings = config.load()
        self.blacklist = Blacklist()
        self.blacklist.load()
        self.worker = None
        self.monitoring = False
        self.capture_dialog = None
        self._engine = None        # 사진 파일 등록용. 처음 쓸 때 만든다.
        self.windows = []          # 콤보 상자 항목과 같은 순서의 (hwnd, 제목)
        self.target_hwnd = 0
        self.target_title = self.settings["target_title"]
        self._commands = queue.Queue()   # 트레이 스레드에서 오는 명령
        self._last_state = None

        root.title("MolCom")
        root.resizable(False, False)
        root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.tray = Tray(self._commands.put, lambda: self.monitoring)
        self._build()
        self.refresh_windows()
        self._refresh_people()
        self._refresh_status()
        self.root.after(POLL_MS, self._poll)
        if self.settings["start_on_launch"]:
            self.root.after(200, self.start)

    # ---- 화면 구성 ----

    def _build(self):
        root = self.root
        base = tkfont.nametofont("TkDefaultFont")
        self._title_font = base.copy()
        self._title_font.configure(weight="bold", size=base.cget("size") + 3)

        # 머리글: 현재 상태와 다음에 할 일을 알려 준다.
        header = tk.Frame(root, background="white")
        header.grid(row=0, column=0, sticky="ew")
        self.lamp = tk.Canvas(header, width=18, height=18, background="white",
                              highlightthickness=0)
        self.lamp.grid(row=0, column=0, rowspan=2, padx=(14, 8), pady=12)
        self._lamp_item = self.lamp.create_oval(2, 2, 16, 16, fill="gray60", outline="gray30")
        self.lbl_title = tk.Label(header, background="white", anchor="w",
                                  font=self._title_font)
        self.lbl_title.grid(row=0, column=1, sticky="ew", pady=(10, 0))
        self.lbl_hint = tk.Label(header, background="white", anchor="w", justify="left")
        self.lbl_hint.grid(row=1, column=1, sticky="ew", pady=(0, 10))
        header.columnconfigure(1, weight=1)
        ttk.Separator(root, orient="horizontal").grid(row=1, column=0, sticky="ew")

        main = ttk.Frame(root, padding=8)
        main.grid(row=2, column=0, sticky="nsew")
        pad = {"padx": 6, "pady": 4}

        cam = ttk.LabelFrame(main, text="카메라", padding=8)
        cam.grid(row=0, column=0, rowspan=2, sticky="n", **pad)
        self.preview = PreviewLabel(cam, "감시를 시작하면 영상이 표시됩니다")
        self.preview.grid(row=0, column=0)
        ttk.Label(cam, foreground="gray30",
                  text="빨간색: 등록된 사람   녹색: 그 밖의 얼굴").grid(
                      row=1, column=0, sticky="w", pady=(6, 0))

        people = ttk.LabelFrame(main, text="1단계 - 감지할 사람", padding=8)
        people.grid(row=0, column=1, sticky="nsew", **pad)
        self.listbox = tk.Listbox(people, height=6, width=30, exportselection=False,
                                  activestyle="dotbox")
        self.listbox.grid(row=0, column=0, rowspan=4, sticky="nsew")
        self.listbox.bind("<<ListboxSelect>>", lambda _e: self._selection_changed())
        scroll = ttk.Scrollbar(people, orient="vertical", command=self.listbox.yview)
        scroll.grid(row=0, column=1, rowspan=4, sticky="ns")
        self.listbox.configure(yscrollcommand=scroll.set)
        ttk.Button(people, text="카메라로 등록...", width=16,
                   command=self.add_from_camera).grid(row=0, column=2, padx=(8, 0), sticky="n")
        ttk.Button(people, text="사진 파일로 등록...", width=16,
                   command=self.add_from_files).grid(row=1, column=2, padx=(8, 0), sticky="n")
        self.btn_remove = ttk.Button(people, text="삭제", width=16,
                                     command=self.remove_person)
        self.btn_remove.grid(row=2, column=2, padx=(8, 0), sticky="n")
        ttk.Label(people, foreground="gray30",
                  text="사진 1장이면 등록됩니다. 목록에서 사람을 고른 뒤\n"
                       "다시 등록하면 그 사람의 사진이 추가됩니다.").grid(
                           row=4, column=0, columnspan=3, sticky="w", pady=(6, 0))
        people.columnconfigure(0, weight=1)

        target = ttk.LabelFrame(main, text="2단계 - 전환할 창", padding=8)
        target.grid(row=1, column=1, sticky="nsew", **pad)
        self.combo = ttk.Combobox(target, state="readonly", width=34,
                                  postcommand=self.refresh_windows)
        self.combo.grid(row=0, column=0, sticky="ew")
        self.combo.bind("<<ComboboxSelected>>", self._target_selected)
        self.btn_test = ttk.Button(target, text="전환 테스트", width=12,
                                   command=self.test_switch)
        self.btn_test.grid(row=0, column=1, padx=(8, 0))
        ttk.Label(target, foreground="gray30",
                  text="등록된 사람이 보이면 이 창이 맨 앞으로 옵니다.\n"
                       "목록은 펼칠 때마다 현재 열린 창으로 갱신됩니다.").grid(
                           row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))
        target.columnconfigure(0, weight=1)

        ttk.Separator(root, orient="horizontal").grid(row=3, column=0, sticky="ew")
        buttons = ttk.Frame(root, padding=(14, 8))
        buttons.grid(row=4, column=0, sticky="ew")
        ttk.Button(buttons, text="옵션...", width=12, command=self.open_options).grid(
            row=0, column=0, sticky="w")
        buttons.columnconfigure(1, weight=1)
        self.btn_toggle = ttk.Button(buttons, text="감시 시작", width=14,
                                     default="active", command=self.toggle)
        self.btn_toggle.grid(row=0, column=2, padx=3)
        ttk.Button(buttons, text="끝내기", width=12, command=self.quit).grid(
            row=0, column=3, padx=(3, 0))

        self.var_status = tk.StringVar(value="")
        ttk.Label(root, textvariable=self.var_status, relief="sunken", anchor="w",
                  padding=(6, 2)).grid(row=5, column=0, sticky="ew")

    # ---- 상태 표시 ----

    def _ready_problem(self):
        """감시를 시작할 수 없는 이유. 문제가 없으면 None."""
        if not self.blacklist.persons:
            return "1단계에서 감지할 사람을 등록하십시오."
        if not self.target_hwnd and not self.target_title:
            return "2단계에서 전환할 창을 선택하십시오."
        return None

    def _refresh_status(self, state=None):
        problem = self._ready_problem()
        names = state["names"] if state else []
        if self.monitoring and names:
            title, lamp = "등록된 사람 감지됨: " + ", ".join(names), "red3"
            hint = "'%s' 창으로 전환했습니다." % self._short_title()
        elif self.monitoring:
            title, lamp = "감시 중", "green3"
            hint = "등록된 사람이 보이면 '%s' 창으로 전환합니다." % self._short_title()
            if state is not None and not state["ready"]:
                hint = "카메라를 여는 중입니다..."
        elif problem:
            title, lamp, hint = "설정이 필요합니다", "gray60", problem
        else:
            title, lamp = "감시 준비 완료", "gold"
            hint = "[감시 시작]을 누르면 등록된 %d명을 감시합니다." % len(self.blacklist.persons)
        self.lbl_title.configure(text=title)
        self.lbl_hint.configure(text=hint)
        self.lamp.itemconfigure(self._lamp_item, fill=lamp)

        self.btn_toggle.configure(
            text="감시 중지" if self.monitoring else "감시 시작",
            state="normal" if self.monitoring or not problem else "disabled")
        self.btn_test.configure(state="normal" if self.target_hwnd else "disabled")
        self._selection_changed()

        if state is not None and self.worker is not None:
            self.var_status.set("화면의 얼굴 %d개   |   전환 %d회   |   마지막 전환 %s" % (
                state["count"], state["switches"], state["last_switch"] or "없음"))
        elif not self.monitoring:
            self.var_status.set("중지됨")

    def _short_title(self):
        title = self.target_title
        return title if len(title) <= 30 else title[:29] + "…"

    def _selection_changed(self):
        self.btn_remove.configure(
            state="normal" if self.listbox.curselection() else "disabled")

    # ---- 감지할 사람 ----

    def _selected_name(self):
        selection = self.listbox.curselection()
        return self.blacklist.persons[selection[0]]["name"] if selection else ""

    def _refresh_people(self, select=None):
        self.listbox.delete(0, "end")
        for i, person in enumerate(self.blacklist.persons):
            self.listbox.insert(
                "end", "%s (사진 %d장)" % (person["name"], len(person["embeddings"])))
            if person["name"] == select:
                self.listbox.selection_set(i)
        if self.worker is not None:
            self.worker.gallery = self.blacklist.gallery()

    def register(self, name, embeddings):
        """인물을 등록하고 그 사람의 사진 수를 돌려준다."""
        self.blacklist.add(name, embeddings)
        self.blacklist.save()
        self._refresh_people(select=name)
        self._refresh_status()
        for person in self.blacklist.persons:
            if person["name"] == name:
                return len(person["embeddings"])
        return 0

    def add_from_camera(self):
        if self.capture_dialog is not None:
            return
        self._ensure_worker()
        self.capture_dialog = CaptureDialog(self, self._selected_name())

    def capture_closed(self):
        self.capture_dialog = None
        if not self.monitoring:
            self._stop_worker()

    def add_from_files(self):
        paths = filedialog.askopenfilenames(
            parent=self.root, title="얼굴 사진 선택",
            filetypes=[("이미지 파일", "*.jpg *.jpeg *.png *.bmp *.webp"),
                       ("모든 파일", "*.*")])
        if not paths:
            return
        try:
            if self._engine is None:
                self._engine = FaceEngine(score_threshold=0.6, min_face_ratio=0.0)
        except Exception as exc:
            messagebox.showerror("MolCom", str(exc), parent=self.root)
            return
        embeddings, failed = [], []
        for path in paths:
            image = read_image(path)
            embedding = self._engine.embed_largest(image) if image is not None else None
            if embedding is None:
                failed.append(path.replace("\\", "/").rsplit("/", 1)[-1])
            else:
                embeddings.append(embedding)
        if failed:
            messagebox.showwarning(
                "MolCom", "다음 사진에서는 얼굴을 찾지 못했습니다.\n\n" + "\n".join(failed),
                parent=self.root)
        if not embeddings:
            return
        name = simpledialog.askstring(
            "MolCom", "얼굴 %d개를 찾았습니다.\n등록할 사람의 이름:" % len(embeddings),
            initialvalue=self._selected_name(), parent=self.root)
        name = (name or "").strip()
        if name:
            self.register(name, embeddings)

    def remove_person(self):
        selection = self.listbox.curselection()
        if not selection:
            return
        name = self.blacklist.persons[selection[0]]["name"]
        if not messagebox.askyesno("MolCom", "'%s'을(를) 목록에서 삭제하시겠습니까?" % name,
                                   parent=self.root):
            return
        self.blacklist.remove(selection[0])
        self.blacklist.save()
        self._refresh_people()
        if self.monitoring and not self.blacklist.persons:
            self.stop()
        self._refresh_status()

    # ---- 전환할 창 ----

    def refresh_windows(self):
        self.windows = winfocus.list_windows()
        self.combo["values"] = [title for _hwnd, title in self.windows]
        index = -1
        for i, (hwnd, title) in enumerate(self.windows):
            if hwnd == self.target_hwnd:
                index = i
                break
            if index < 0 and title == self.target_title:
                index = i
        if index >= 0:
            self.combo.current(index)
            self.target_hwnd, self.target_title = self.windows[index]
        else:
            self.combo.set("")
            self.target_hwnd = 0

    def _target_selected(self, _event=None):
        index = self.combo.current()
        if 0 <= index < len(self.windows):
            self.target_hwnd, self.target_title = self.windows[index]
            self.settings["target_title"] = self.target_title
            config.save(self.settings)
        self._refresh_status()

    def _resolve_target(self):
        """전환 대상 핸들을 구한다. 작업 스레드에서도 호출된다."""
        hwnd = self.target_hwnd
        if winfocus.is_window(hwnd):
            return hwnd
        # 창이 닫혔다가 다시 열린 경우 제목으로 다시 찾는다.
        hwnd = winfocus.find_by_title(self.target_title) if self.target_title else 0
        if hwnd:
            self.target_hwnd = hwnd
        return hwnd

    def test_switch(self):
        if not self._resolve_target():
            messagebox.showwarning(
                "MolCom", "선택한 창을 찾을 수 없습니다. 창을 다시 선택하십시오.",
                parent=self.root)
            self.refresh_windows()
            self._refresh_status()
        elif not winfocus.focus_window(self.target_hwnd):
            messagebox.showerror("MolCom", "창을 전환하지 못했습니다.", parent=self.root)

    # ---- 카메라 작업 스레드 ----

    def _want_preview(self):
        if self.capture_dialog is not None:
            return True
        return bool(self.settings["show_preview"]) and self._visible

    def _apply_settings(self):
        if self.worker is not None:
            self.worker.match = config.SENSITIVITY.get(
                self.settings["sensitivity"], config.SENSITIVITY["normal"])
            self.worker.frames_needed = 1 if self.settings["instant"] else SLOW_FRAMES
            self.worker.armed = self.monitoring

    def _ensure_worker(self):
        if self.worker is None:
            self.worker = CameraWorker(self.settings["camera_index"],
                                       self.blacklist.gallery(),
                                       self._resolve_target, self._want_preview)
            self._apply_settings()
            self.worker.start()

    def _stop_worker(self):
        if self.worker is not None:
            self.worker.stop()
            self._retired = self.worker
            self.worker = None
        self.preview.clear()

    def settings_changed(self):
        config.save(self.settings)
        if self.worker is not None and self.worker.camera_index != self.settings["camera_index"]:
            self.worker.stop()
            self.worker = None
            self._ensure_worker()
        self._apply_settings()
        if not self.settings["show_preview"]:
            self.preview.clear("미리 보기 꺼짐")

    def open_options(self):
        OptionsDialog(self)

    # ---- 감시 시작과 중지 ----

    def toggle(self):
        if self.monitoring:
            self.stop()
        else:
            self.start()

    def start(self):
        if self.monitoring or self._ready_problem():
            return
        if not self._resolve_target():
            messagebox.showwarning(
                "MolCom", "전환할 창 '%s'을(를) 찾을 수 없습니다.\n창을 다시 선택하십시오."
                % self._short_title(), parent=self.root)
            return
        self.monitoring = True
        self._ensure_worker()
        self._apply_settings()
        self.tray.update(True)
        self._refresh_status()

    def stop(self):
        if not self.monitoring:
            return
        self.monitoring = False
        self._apply_settings()
        if self.capture_dialog is None:
            self._stop_worker()
        self.tray.update(False)
        self._refresh_status()

    # ---- 주기적 갱신 ----

    def _poll(self):
        while True:
            try:
                command = self._commands.get_nowait()
            except queue.Empty:
                break
            if command == "open":
                self.show_window()
            elif command == "toggle":
                self.toggle()
            elif command == "exit":
                self.quit()
                return

        worker = self.worker
        if worker is not None:
            state = worker.snapshot()
            if state["error"] or not state["running"]:
                self._worker_failed(state["error"])
            else:
                self._show(state)
        self.root.after(POLL_MS, self._poll)

    def _worker_failed(self, error):
        self.monitoring = False
        self._stop_worker()
        if self.capture_dialog is not None:
            self.capture_dialog.close()
        self.tray.update(False)
        self._refresh_status()
        if error:
            self.show_window()
            messagebox.showerror("MolCom", error, parent=self.root)

    def _show(self, state):
        dialog = self.capture_dialog
        if state["png"]:
            if dialog is not None:
                dialog.preview.show(state["png"])
            elif self.settings["show_preview"]:
                self.preview.show(state["png"])
        if state["captured"] is not None and dialog is not None:
            dialog.on_captured(state["captured"])
        key = (state["count"], tuple(state["names"]), state["switches"], state["ready"])
        if key != self._last_state:
            self._last_state = key
            self._refresh_status(state)

    # ---- 창 닫기, 트레이 ----

    _visible = True
    _retired = None

    def show_window(self):
        self._visible = True
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def on_close(self):
        if self.monitoring and self.tray.available and self.settings["tray_on_close"]:
            self._visible = False
            self.root.withdraw()
        else:
            self.quit()

    def quit(self):
        # 카메라를 닫고 나서 끝낸다.
        for worker in (self.worker, self._retired):
            if worker is not None:
                worker.stop()
                worker.join(timeout=2)
        self.tray.stop()
        config.save(self.settings)
        self.root.destroy()


def main():
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    root = tk.Tk()
    style = ttk.Style(root)
    if "vista" in style.theme_names():
        style.theme_use("vista")
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
