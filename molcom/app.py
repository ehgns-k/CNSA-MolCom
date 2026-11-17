"""MolCom 메인 창."""

import base64
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

import cv2

from . import config, winfocus
from .detector import FaceDetector, SwitchTrigger

PREVIEW_W, PREVIEW_H = 320, 240
POLL_MS = 60


class Monitor(threading.Thread):
    """카메라를 읽고 얼굴을 세어 필요할 때 창을 전환하는 작업 스레드."""

    def __init__(self, camera_index, threshold, frames_needed, rearm_seconds,
                 get_target, show_preview):
        super().__init__(daemon=True)
        self.camera_index = camera_index
        self.threshold = threshold
        self.frames_needed = frames_needed
        self.rearm_seconds = rearm_seconds
        self.get_target = get_target
        self.show_preview = show_preview

        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._state = {"count": 0, "armed": True, "switches": 0,
                       "last_switch": None, "png": None, "error": None,
                       "running": True}

    def stop(self):
        self._stop_event.set()

    def snapshot(self):
        with self._lock:
            state = dict(self._state)
            self._state["png"] = None
        return state

    def _update(self, **values):
        with self._lock:
            self._state.update(values)

    def run(self):
        cap = None
        try:
            detector = FaceDetector(score_threshold=self.threshold)
            if winfocus.IS_WINDOWS:
                cap = cv2.VideoCapture(self.camera_index, cv2.CAP_DSHOW)
            else:
                cap = cv2.VideoCapture(self.camera_index)
            if not cap.isOpened():
                raise RuntimeError("카메라 %d번을 열 수 없습니다." % self.camera_index)
            self._loop(cap, detector)
        except Exception as exc:  # 스레드 안의 오류는 화면에 표시한다.
            self._update(error=str(exc))
        finally:
            if cap is not None:
                cap.release()
            self._update(running=False)

    def _loop(self, cap, detector):
        trigger = SwitchTrigger(limit=2, frames_needed=self.frames_needed,
                                rearm_seconds=self.rearm_seconds)
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

            boxes = detector.detect(frame)
            values = {"count": len(boxes)}
            if trigger.update(len(boxes)):
                winfocus.focus_window(self.get_target())
                switches += 1
                values["switches"] = switches
                values["last_switch"] = time.strftime("%H:%M:%S")
            values["armed"] = trigger.armed
            if self.show_preview():
                values["png"] = self._encode(frame, boxes)
            self._update(**values)

    @staticmethod
    def _encode(frame, boxes):
        h, w = frame.shape[:2]
        sx, sy = PREVIEW_W / float(w), PREVIEW_H / float(h)
        small = cv2.resize(frame, (PREVIEW_W, PREVIEW_H))
        # 가장 큰 얼굴을 주 사용자로 보고 녹색으로, 나머지는 빨간색으로 표시한다.
        ordered = sorted(boxes, key=lambda b: b[2] * b[3], reverse=True)
        for i, (x, y, bw, bh) in enumerate(ordered):
            color = (0, 160, 0) if i == 0 else (0, 0, 255)
            cv2.rectangle(small, (int(x * sx), int(y * sy)),
                          (int((x + bw) * sx), int((y + bh) * sy)), color, 2)
        ok, buf = cv2.imencode(".png", small, [cv2.IMWRITE_PNG_COMPRESSION, 1])
        return base64.b64encode(buf.tobytes()) if ok else None


class App:
    def __init__(self, root):
        self.root = root
        self.settings = config.load()
        self.monitor = None
        self.windows = []          # 콤보 상자 항목과 같은 순서의 (hwnd, 제목)
        self.target_hwnd = 0
        self.target_title = self.settings["target_title"]
        self._photo = None

        root.title("MolCom")
        root.resizable(False, False)
        root.protocol("WM_DELETE_WINDOW", self.on_close)

        self._build()
        self.refresh_windows()
        self._set_running(False)
        self.root.after(POLL_MS, self._poll)
        if self.settings["start_on_launch"]:
            self.root.after(200, self.start)

    # ---- 화면 구성 ----

    def _build(self):
        pad = {"padx": 8, "pady": 4}
        main = ttk.Frame(self.root, padding=8)
        main.grid(row=0, column=0, sticky="nsew")

        # 카메라
        cam = ttk.LabelFrame(main, text="카메라", padding=8)
        cam.grid(row=0, column=0, rowspan=3, sticky="ns", **pad)
        self.preview = tk.Label(cam, relief="sunken", borderwidth=1,
                                background="black", foreground="white",
                                text="미리 보기 없음")
        self._blank = tk.PhotoImage(width=PREVIEW_W, height=PREVIEW_H)
        self.preview.configure(image=self._blank, compound="center")
        self.preview.grid(row=0, column=0, columnspan=3, pady=(0, 6))
        ttk.Label(cam, text="카메라 번호:").grid(row=1, column=0, sticky="w")
        self.var_camera = tk.IntVar(value=self.settings["camera_index"])
        self.spin_camera = ttk.Spinbox(cam, from_=0, to=9, width=4,
                                       textvariable=self.var_camera)
        self.spin_camera.grid(row=1, column=1, sticky="w", padx=4)
        self.var_preview = tk.BooleanVar(value=self.settings["show_preview"])
        ttk.Checkbutton(cam, text="미리 보기 표시", variable=self.var_preview,
                        command=self._preview_toggled).grid(row=1, column=2, sticky="e")
        cam.columnconfigure(2, weight=1)

        # 전환할 창
        target = ttk.LabelFrame(main, text="전환할 창", padding=8)
        target.grid(row=0, column=1, sticky="new", **pad)
        self.combo = ttk.Combobox(target, state="readonly", width=44)
        self.combo.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        self.combo.bind("<<ComboboxSelected>>", self._target_selected)
        ttk.Button(target, text="목록 새로 고침",
                   command=self.refresh_windows).grid(row=1, column=0, sticky="w")
        ttk.Button(target, text="전환 테스트",
                   command=self.test_switch).grid(row=1, column=1, sticky="e")
        target.columnconfigure(0, weight=1)

        # 감지 설정
        det = ttk.LabelFrame(main, text="감지 설정", padding=8)
        det.grid(row=1, column=1, sticky="new", **pad)
        ttk.Label(det, text="검출 신뢰도 기준 (%):").grid(row=0, column=0, sticky="w")
        self.var_threshold = tk.IntVar(value=self.settings["threshold"])
        self.spin_threshold = ttk.Spinbox(det, from_=30, to=95, increment=5, width=5,
                                          textvariable=self.var_threshold)
        self.spin_threshold.grid(row=0, column=1, sticky="w", padx=4, pady=2)
        ttk.Label(det, text="낮을수록 민감").grid(row=0, column=2, sticky="w")

        ttk.Label(det, text="연속 감지 프레임 수:").grid(row=1, column=0, sticky="w")
        self.var_frames = tk.IntVar(value=self.settings["frames_needed"])
        self.spin_frames = ttk.Spinbox(det, from_=1, to=30, width=5,
                                       textvariable=self.var_frames)
        self.spin_frames.grid(row=1, column=1, sticky="w", padx=4, pady=2)
        ttk.Label(det, text="1 = 즉시 전환").grid(row=1, column=2, sticky="w")

        ttk.Label(det, text="재감시 대기 시간 (초):").grid(row=2, column=0, sticky="w")
        self.var_rearm = tk.IntVar(value=self.settings["rearm_seconds"])
        self.spin_rearm = ttk.Spinbox(det, from_=0, to=600, width=5,
                                      textvariable=self.var_rearm)
        self.spin_rearm.grid(row=2, column=1, sticky="w", padx=4, pady=2)

        self.var_autostart = tk.BooleanVar(value=self.settings["start_on_launch"])
        ttk.Checkbutton(det, text="프로그램을 열 때 바로 감시 시작",
                        variable=self.var_autostart).grid(
                            row=3, column=0, columnspan=3, sticky="w", pady=(6, 0))

        # 상태
        stat = ttk.LabelFrame(main, text="상태", padding=8)
        stat.grid(row=2, column=1, sticky="nsew", **pad)
        ttk.Label(stat, text="감지된 사람 수:").grid(row=0, column=0, sticky="w")
        self.lbl_count = ttk.Label(stat, text="-")
        self.lbl_count.grid(row=0, column=1, sticky="w", padx=8)
        ttk.Label(stat, text="전환 횟수:").grid(row=1, column=0, sticky="w")
        self.lbl_switches = ttk.Label(stat, text="0")
        self.lbl_switches.grid(row=1, column=1, sticky="w", padx=8)
        ttk.Label(stat, text="마지막 전환:").grid(row=2, column=0, sticky="w")
        self.lbl_last = ttk.Label(stat, text="-")
        self.lbl_last.grid(row=2, column=1, sticky="w", padx=8)

        # 버튼 줄
        ttk.Separator(main, orient="horizontal").grid(
            row=3, column=0, columnspan=2, sticky="ew", padx=8, pady=(8, 4))
        buttons = ttk.Frame(main)
        buttons.grid(row=4, column=0, columnspan=2, sticky="e", **pad)
        self.btn_start = ttk.Button(buttons, text="감시 시작", width=12, command=self.start)
        self.btn_start.grid(row=0, column=0, padx=3)
        self.btn_stop = ttk.Button(buttons, text="감시 중지", width=12, command=self.stop)
        self.btn_stop.grid(row=0, column=1, padx=3)
        ttk.Button(buttons, text="닫기", width=12, command=self.on_close).grid(
            row=0, column=2, padx=3)

        # 상태 표시줄
        self.var_status = tk.StringVar(value="대기 중")
        ttk.Label(self.root, textvariable=self.var_status, relief="sunken",
                  anchor="w", padding=(6, 2)).grid(row=1, column=0, sticky="ew")

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
            messagebox.showwarning("MolCom", "전환할 창을 먼저 선택하십시오.", parent=self.root)
            return
        if not winfocus.focus_window(self.target_hwnd):
            messagebox.showerror("MolCom", "창을 전환하지 못했습니다.", parent=self.root)

    # ---- 감시 시작과 중지 ----

    def _read_int(self, var, low, high, fallback):
        try:
            value = int(var.get())
        except (tk.TclError, ValueError):
            value = fallback
        value = max(low, min(high, value))
        var.set(value)
        return value

    def _collect(self):
        s = self.settings
        s["camera_index"] = self._read_int(self.var_camera, 0, 9, 0)
        s["threshold"] = self._read_int(self.var_threshold, 30, 95, 70)
        s["frames_needed"] = self._read_int(self.var_frames, 1, 30, 1)
        s["rearm_seconds"] = self._read_int(self.var_rearm, 0, 600, 3)
        s["show_preview"] = bool(self.var_preview.get())
        s["start_on_launch"] = bool(self.var_autostart.get())
        s["target_title"] = self.target_title
        return s

    def start(self):
        if self.monitor is not None:
            return
        s = self._collect()
        if not self._resolve_target():
            messagebox.showwarning("MolCom", "전환할 창을 먼저 선택하십시오.", parent=self.root)
            return
        config.save(s)
        self.monitor = Monitor(
            camera_index=s["camera_index"],
            threshold=s["threshold"] / 100.0,
            frames_needed=s["frames_needed"],
            rearm_seconds=s["rearm_seconds"],
            get_target=self._resolve_target,
            show_preview=self.var_preview.get,
        )
        self.monitor.start()
        self._set_running(True)
        self.var_status.set("카메라를 여는 중...")

    def stop(self):
        if self.monitor is None:
            return
        self.monitor.stop()
        self.monitor = None
        self._set_running(False)
        self._clear_preview()
        self.lbl_count.configure(text="-")
        self.var_status.set("대기 중")

    def _set_running(self, running):
        self.btn_start.configure(state="disabled" if running else "normal")
        self.btn_stop.configure(state="normal" if running else "disabled")
        state = "disabled" if running else "normal"
        for widget in (self.spin_camera, self.spin_threshold,
                       self.spin_frames, self.spin_rearm):
            widget.configure(state=state)

    def _preview_toggled(self):
        if not self.var_preview.get():
            self._clear_preview()

    def _clear_preview(self):
        self._photo = None
        self.preview.configure(image=self._blank, text="미리 보기 없음")

    # ---- 작업 스레드 상태 반영 ----

    def _poll(self):
        monitor = self.monitor
        if monitor is not None:
            state = monitor.snapshot()
            if state["error"]:
                self.stop()
                self.var_status.set("오류: " + state["error"])
                messagebox.showerror("MolCom", state["error"], parent=self.root)
            elif not state["running"]:
                self.stop()
            else:
                self._show(state)
        self.root.after(POLL_MS, self._poll)

    def _show(self, state):
        if state["png"] and self.var_preview.get():
            self._photo = tk.PhotoImage(data=state["png"])
            self.preview.configure(image=self._photo, text="")
        count = state["count"]
        self.lbl_count.configure(text=str(count))
        self.lbl_switches.configure(text=str(state["switches"]))
        self.lbl_last.configure(text=state["last_switch"] or "-")
        if count >= 2:
            self.var_status.set("추가 인물 감지됨 (%d명)" % count)
        elif not state["armed"]:
            self.var_status.set("전환 완료 - 재감시 대기 중")
        else:
            self.var_status.set("감시 중")

    def on_close(self):
        if self.monitor is not None:
            self.monitor.stop()
        config.save(self._collect())
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
