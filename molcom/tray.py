"""알림 영역(트레이) 아이콘. pystray가 없거나 실패하면 available이 False가 된다."""

try:
    import pystray
    from PIL import Image, ImageDraw
except Exception:   # 트레이 없이도 프로그램은 동작해야 한다.
    pystray = None


def _image(running):
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((4, 4, 60, 60), fill=(0, 120, 60) if running else (110, 110, 110),
                 outline=(255, 255, 255), width=3)
    draw.ellipse((22, 22, 42, 42), fill=(255, 255, 255))
    return image


class Tray:
    """콜백은 트레이 스레드에서 불리므로 post(이름)로 UI 스레드에 넘긴다."""

    def __init__(self, post, is_running):
        self.available = False
        self._icon = None
        if pystray is None:
            return
        try:
            menu = pystray.Menu(
                pystray.MenuItem("MolCom 열기", lambda: post("open"), default=True),
                pystray.MenuItem(
                    lambda item: "감시 중지" if is_running() else "감시 시작",
                    lambda: post("toggle")),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("끝내기", lambda: post("exit")),
            )
            self._icon = pystray.Icon("MolCom", _image(False), "MolCom", menu)
            self._icon.run_detached()
            self.available = True
        except Exception:
            self._icon = None

    def update(self, running):
        if self._icon is None:
            return
        try:
            self._icon.icon = _image(running)
            self._icon.title = "MolCom - 감시 중" if running else "MolCom - 중지됨"
            self._icon.update_menu()
        except Exception:
            pass

    def stop(self):
        if self._icon is not None:
            try:
                self._icon.stop()
            except Exception:
                pass
            self._icon = None
