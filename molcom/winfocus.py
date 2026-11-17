"""Win32 창 목록 조회와 포커스 전환 (ctypes)."""

import sys

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    try:
        dwmapi = ctypes.WinDLL("dwmapi")
    except OSError:
        dwmapi = None

    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.IsWindow.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.IsIconic.restype = wintypes.BOOL
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongW.restype = wintypes.LONG
    user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetWindow.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.GetForegroundWindow.argtypes = []
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL
    user32.BringWindowToTop.argtypes = [wintypes.HWND]
    user32.BringWindowToTop.restype = wintypes.BOOL
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.ShowWindow.restype = wintypes.BOOL
    user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
    user32.AttachThreadInput.restype = wintypes.BOOL
    user32.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_void_p]
    user32.keybd_event.restype = None
    kernel32.GetCurrentThreadId.argtypes = []
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD
    kernel32.GetCurrentProcessId.argtypes = []
    kernel32.GetCurrentProcessId.restype = wintypes.DWORD

    GWL_EXSTYLE = -20
    WS_EX_TOOLWINDOW = 0x00000080
    GW_OWNER = 4
    SW_RESTORE = 9
    VK_MENU = 0x12
    KEYEVENTF_KEYUP = 0x0002
    DWMWA_CLOAKED = 14


def _title(hwnd):
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def _is_cloaked(hwnd):
    # 다른 가상 데스크톱의 창이나 대기 중인 UWP 창은 보이는 것으로
    # 보고되지만 실제로는 화면에 없다.
    if dwmapi is None:
        return False
    value = wintypes.DWORD(0)
    hr = dwmapi.DwmGetWindowAttribute(
        wintypes.HWND(hwnd), wintypes.DWORD(DWMWA_CLOAKED),
        ctypes.byref(value), ctypes.sizeof(value),
    )
    return hr == 0 and value.value != 0


def list_windows():
    """Alt+Tab에 나타나는 최상위 창을 (hwnd, 제목) 목록으로 돌려준다.

    이 프로그램 자신의 창은 제외한다.
    """
    if not IS_WINDOWS:
        return []

    own_pid = kernel32.GetCurrentProcessId()
    result = []

    def callback(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        if user32.GetWindow(hwnd, GW_OWNER):
            return True
        if user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TOOLWINDOW:
            return True
        pid = wintypes.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == own_pid:
            return True
        title = _title(hwnd)
        if not title or _is_cloaked(hwnd):
            return True
        result.append((int(hwnd), title))
        return True

    user32.EnumWindows(WNDENUMPROC(callback), 0)
    return result


def is_window(hwnd):
    return bool(IS_WINDOWS and hwnd and user32.IsWindow(hwnd))


def is_foreground(hwnd):
    return bool(IS_WINDOWS and hwnd and user32.GetForegroundWindow() == hwnd)


def find_by_title(title):
    """제목이 정확히 일치하는 창의 핸들을 찾는다. 없으면 0."""
    for hwnd, text in list_windows():
        if text == title:
            return hwnd
    return 0


def focus_window(hwnd):
    """지정한 창을 전면으로 가져온다. 성공하면 True."""
    if not is_window(hwnd):
        return False

    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    if user32.GetForegroundWindow() == hwnd:
        return True

    # Windows는 전경 프로세스가 아닌 프로그램의 SetForegroundWindow 호출을
    # 막는다. 대상 창의 입력 스레드에 붙으면 이 제한을 받지 않는다.
    this_thread = kernel32.GetCurrentThreadId()
    fg = user32.GetForegroundWindow()
    fg_thread = user32.GetWindowThreadProcessId(fg, None) if fg else 0
    attached = bool(
        fg_thread and fg_thread != this_thread
        and user32.AttachThreadInput(this_thread, fg_thread, True)
    )
    try:
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    finally:
        if attached:
            user32.AttachThreadInput(this_thread, fg_thread, False)
    if user32.GetForegroundWindow() == hwnd:
        return True

    # 위 방법이 막힌 경우: Alt 키 입력이 있으면 전경 잠금이 풀린다.
    user32.keybd_event(VK_MENU, 0, 0, None)
    try:
        user32.SetForegroundWindow(hwnd)
    finally:
        user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, None)
    return user32.GetForegroundWindow() == hwnd
