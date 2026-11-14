"""Headless / Android runtime shims registered in sys.modules before importing upstream desktop modules."""

import sys
import types
from logging.handlers import RotatingFileHandler
from threading import Lock, Thread
from time import sleep


def install_android_shims() -> None:
    """Install lightweight PySide6 / Windows / optional desktop module stubs if absent."""
    _install_pyside6_stub()
    _install_winreg_stub()
    _install_win32_stubs()
    _install_concurrent_log_handler_stub()
    _install_playsound_stub()
    _install_rapidocr_stub()
    _install_psutil_stub()


def _install_pyside6_stub() -> None:
    try:
        import PySide6  # noqa: F401
        return
    except ImportError:
        pass

    class _BoundSignal:
        def __init__(self) -> None:
            self._callbacks = []

        def connect(self, cb) -> None:
            if cb not in self._callbacks:
                self._callbacks.append(cb)

        def disconnect(self, cb=None) -> None:
            if cb is None:
                self._callbacks.clear()
            elif cb in self._callbacks:
                self._callbacks.remove(cb)

        def emit(self, *args, **kwargs) -> None:
            for cb in list(self._callbacks):
                try:
                    cb(*args, **kwargs)
                except Exception:
                    pass

    class Signal:
        def __init__(self, *types_) -> None:
            self._name = ""

        def __set_name__(self, owner, name: str) -> None:
            self._name = f"_sig_{name}"

        def __get__(self, instance, owner=None):
            if instance is None:
                return self
            sig = getattr(instance, self._name, None)
            if sig is None:
                sig = _BoundSignal()
                setattr(instance, self._name, sig)
            return sig

    class QObject:
        def __init__(self, *args, **kwargs) -> None:
            pass

    class QMutex:
        def __init__(self) -> None:
            self._lock = Lock()

        def lock(self) -> None:
            self._lock.acquire()

        def unlock(self) -> None:
            if self._lock.locked():
                self._lock.release()

    class QThread(Thread):
        def __init__(self, parent=None) -> None:
            super().__init__(daemon=True)

        def terminate(self) -> None:
            pass

        @staticmethod
        def msleep(ms: int) -> None:
            sleep(ms / 1000.0)

    def QT_TRANSLATE_NOOP(context: str, text: str) -> str:
        return text

    class QApplication:
        @staticmethod
        def translate(context: str, text: str) -> str:
            return text

    pyside6_mod = types.ModuleType("PySide6")
    qtcore_mod = types.ModuleType("PySide6.QtCore")
    qtcore_mod.QObject = QObject
    qtcore_mod.Signal = Signal
    qtcore_mod.QMutex = QMutex
    qtcore_mod.QThread = QThread
    qtcore_mod.QT_TRANSLATE_NOOP = QT_TRANSLATE_NOOP

    qtwidgets_mod = types.ModuleType("PySide6.QtWidgets")
    qtwidgets_mod.QApplication = QApplication

    pyside6_mod.QtCore = qtcore_mod
    pyside6_mod.QtWidgets = qtwidgets_mod

    sys.modules["PySide6"] = pyside6_mod
    sys.modules["PySide6.QtCore"] = qtcore_mod
    sys.modules["PySide6.QtWidgets"] = qtwidgets_mod


def _install_winreg_stub() -> None:
    if "winreg" in sys.modules:
        return
    try:
        import winreg  # noqa: F401
    except ImportError:
        winreg_mod = types.ModuleType("winreg")
        winreg_mod.HKEY_CURRENT_USER = 0
        winreg_mod.KEY_READ = 0
        winreg_mod.REG_BINARY = 3
        winreg_mod.OpenKey = lambda *a, **kw: (_ for _ in ()).throw(FileNotFoundError("winreg unavailable"))
        sys.modules["winreg"] = winreg_mod


def _install_win32_stubs() -> None:
    if "win32api" not in sys.modules:
        try:
            import win32api  # noqa: F401
        except ImportError:
            sys.modules["win32api"] = types.ModuleType("win32api")

    if "win32con" not in sys.modules:
        try:
            import win32con  # noqa: F401
        except ImportError:
            win32con_mod = types.ModuleType("win32con")
            win32con_mod.MONITOR_DEFAULTTONEAREST = 2
            sys.modules["win32con"] = win32con_mod

    if "win32process" not in sys.modules:
        try:
            import win32process  # noqa: F401
        except ImportError:
            sys.modules["win32process"] = types.ModuleType("win32process")

    if "win32crypt" not in sys.modules:
        try:
            import win32crypt  # noqa: F401
        except ImportError:
            win32crypt_mod = types.ModuleType("win32crypt")
            win32crypt_mod.CryptProtectData = lambda data, *a, **kw: data
            win32crypt_mod.CryptUnprotectData = lambda data, *a, **kw: ("", data)
            sys.modules["win32crypt"] = win32crypt_mod

    if "win32gui" not in sys.modules:
        try:
            import win32gui  # noqa: F401
        except ImportError:
            win32gui_mod = types.ModuleType("win32gui")
            win32gui_mod.FindWindow = lambda *a, **kw: 0
            win32gui_mod.IsWindow = lambda *a, **kw: False
            sys.modules["win32gui"] = win32gui_mod


def _install_rapidocr_stub() -> None:
    if "rapidocr" in sys.modules:
        return
    try:
        import shapely  # noqa: F401
        from rapidocr import RapidOCR  # noqa: F401
        return
    except ImportError:
        from agent.android_ocr import AndroidOCROutput
        rapidocr_mod = types.ModuleType("rapidocr")
        rapidocr_mod.EngineType = type("EngineType", (), {"ONNXRUNTIME": 0})
        rapidocr_mod.LangDet = type("LangDet", (), {"CH": 0})
        rapidocr_mod.LangRec = type("LangRec", (), {"CH": 0})
        rapidocr_mod.ModelType = type("ModelType", (), {"MOBILE": 0})
        rapidocr_mod.OCRVersion = type("OCRVersion", (), {"PPOCRV4": 0})
        rapidocr_mod.RapidOCR = lambda *a, **kw: (lambda img: AndroidOCROutput())

        utils_mod = types.ModuleType("rapidocr.utils")
        output_mod = types.ModuleType("rapidocr.utils.output")
        output_mod.RapidOCROutput = AndroidOCROutput
        utils_mod.output = output_mod
        rapidocr_mod.utils = utils_mod

        sys.modules["rapidocr"] = rapidocr_mod
        sys.modules["rapidocr.utils"] = utils_mod
        sys.modules["rapidocr.utils.output"] = output_mod


def _install_concurrent_log_handler_stub() -> None:
    if "concurrent_log_handler" in sys.modules:
        return
    try:
        import concurrent_log_handler  # noqa: F401
    except ImportError:
        mod = types.ModuleType("concurrent_log_handler")
        mod.ConcurrentRotatingFileHandler = RotatingFileHandler
        sys.modules["concurrent_log_handler"] = mod


def _install_playsound_stub() -> None:
    if "playsound3" in sys.modules:
        return
    try:
        import playsound3  # noqa: F401
    except ImportError:
        mod = types.ModuleType("playsound3")
        mod.playsound = lambda *a, **kw: None
        sys.modules["playsound3"] = mod


def _install_psutil_stub() -> None:
    if "psutil" in sys.modules:
        return
    try:
        import psutil  # noqa: F401
    except ImportError:
        mod = types.ModuleType("psutil")
        mod.NoSuchProcess = type("NoSuchProcess", (Exception,), {})
        mod.AccessDenied = type("AccessDenied", (Exception,), {})
        mod.ZombieProcess = type("ZombieProcess", (Exception,), {})
        mod.virtual_memory = lambda: types.SimpleNamespace(percent=0.0)
        mod.process_iter = lambda *a, **kw: iter(())
        mod.Process = lambda pid: (_ for _ in ()).throw(mod.NoSuchProcess(pid))
        sys.modules["psutil"] = mod
