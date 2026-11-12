import math
import os
import random
import struct
import subprocess
import threading
from time import sleep
from typing import Any

import cv2
import numpy as np

from module.automation.input_handlers import AbstractInput
from module.automation.input_handlers.scroll_swipe import build_scroll_swipe_plan
from module.config import cfg
from module.logger import log
from module.my_error.my_error import userStopError

ANDROID_KEY_MAP = {
    "a": 29,
    "b": 30,
    "c": 31,
    "d": 32,
    "e": 33,
    "f": 34,
    "g": 35,
    "h": 36,
    "i": 37,
    "j": 38,
    "k": 39,
    "l": 40,
    "m": 41,
    "n": 42,
    "o": 43,
    "p": 44,
    "q": 45,
    "r": 46,
    "s": 47,
    "t": 48,
    "u": 49,
    "v": 50,
    "w": 51,
    "x": 52,
    "y": 53,
    "z": 54,
    "0": 7,
    "1": 8,
    "2": 9,
    "3": 10,
    "4": 11,
    "5": 12,
    "6": 13,
    "7": 14,
    "8": 15,
    "9": 16,
    "enter": 66,
    "esc": 111,
    "space": 62,
    "tab": 61,
    "shift": 59,
    "ctrl": 113,
    "alt": 57,
    "up": 19,
    "down": 20,
    "left": 21,
    "right": 22,
}

LIMBUS_PACKAGE = "com.ProjectMoon.LimbusCompany"
LIMBUS_ACTIVITY = "com.ProjectMoon.LimbusCompany/com.ProjectMoon.LimbusCompany.LimbusCompanyActivity"
TEAM_SCROLL_START_SETTLE_SECONDS = 0.08


class MaaControl(AbstractInput):
    """
    MaaFramework 原生控制器 & Android 虚拟副屏 (Shizuku VirtualDisplay) 双模输入与截屏适配器。

    模式 1 (MaaFramework Context 模式):
      当在 MaaFwApp (Android APK) 或 MaaPiCli 中作为 Agent 运行时，通过 `bind_maa_context(context)`
      直接调用 `context.tasker.controller` (`libMaaAndroidNativeControlUnit.so` 或 AdbController)。

    模式 2 (Shizuku VirtualDisplay 独立守护进程模式):
      当在 Android Termux 中直接脱离 APK 独立运行时，自动拉起或复用 `VdDaemon` 创建 1920x1080@280dpi
      后台虚拟副屏，通过 `ImageReader` 抓取纯内存 1080P 帧并通过 `input -d <displayId>` 注入触控与按键。
    """

    connection_device: "MaaControl | None" = None

    def __init__(self, maa_context: Any = None, rish_path: str | None = None, use_virtual_display: bool = True):
        super().__init__()
        self.maa_context = maa_context
        self.rish_path = rish_path or os.environ.get("AALC_RISH_PATH", "/data/data/com.termux/files/home/rish")
        self.use_virtual_display = use_virtual_display
        self.display_id: int = 0
        self.raw_width: int = 1920
        self.raw_height: int = 1080
        self._daemon_proc: subprocess.Popen | None = None
        self._rish_proc: subprocess.Popen | None = None
        self._rish_lock = threading.Lock()
        self._vd_initialized: bool = False
        self._app_started: bool = False
        # 强制 AALC 内部使用 1080P 模拟器模式基准
        cfg.unsaved_set_value("simulator", True)
        cfg.unsaved_set_value("simulator_type", 2)
        cfg.unsaved_set_value("set_win_size", 1080)

        if self.maa_context is not None:
            self._configure_maa_controller()
        MaaControl.connection_device = self

    @classmethod
    def bind_maa_context(cls, context: Any) -> "MaaControl":
        if cls.connection_device is None:
            return cls(maa_context=context)
        cls.connection_device.maa_context = context
        cls.connection_device._app_started = False
        cls.connection_device._configure_maa_controller()
        return cls.connection_device

    @classmethod
    def clean_connect(cls) -> None:
        if cls.connection_device is not None:
            cls.connection_device.stop_virtual_display()
            cls.connection_device = None

    def _configure_maa_controller(self) -> None:
        if self.maa_context is None:
            return
        try:
            ctrl = self.maa_context.tasker.controller
            ctrl.set_screenshot_target_short_side(1080)
            ctrl.post_screencap().wait()
            res = ctrl.resolution
            if res and res[0] > 0 and res[1] > 0:
                self.raw_width, self.raw_height = int(res[0]), int(res[1])
                log.info(f"MaaFramework 控制器已绑定，设备原始分辨率: {self.raw_width}x{self.raw_height}")
        except Exception as e:
            log.debug(f"配置 MaaFramework 控制器参数时提示: {e}")

    def _check_stopping(self) -> None:
        if self.maa_context is not None:
            try:
                if self.maa_context.tasker.stopping:
                    raise userStopError("MaaFramework 任务已停止")
            except userStopError:
                raise
            except Exception as e:
                if "Failed to get controller" in str(e) or "stopping" in str(e).lower():
                    raise userStopError("MaaFramework 控制器已断开或任务已停止") from e

    def _close_rish_shell(self) -> None:
        with self._rish_lock:
            if self._rish_proc is not None:
                try:
                    if self._rish_proc.stdin:
                        self._rish_proc.stdin.close()
                    self._rish_proc.terminate()
                except Exception:
                    pass
                self._rish_proc = None

    def _run_rish(self, cmd: str) -> str:
        if not os.path.exists(self.rish_path):
            return ""
        marker = "__AALC_RISH_DONE__"
        with self._rish_lock:
            try:
                if self._rish_proc is None or self._rish_proc.poll() is not None:
                    self._rish_proc = subprocess.Popen(
                        ["bash", self.rish_path, "-c", "sh"],
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL,
                        text=True,
                        bufsize=1,
                    )
                assert self._rish_proc.stdin is not None and self._rish_proc.stdout is not None
                self._rish_proc.stdin.write(f"{cmd}\necho {marker}\n")
                self._rish_proc.stdin.flush()
                out_lines: list[str] = []
                while True:
                    line = self._rish_proc.stdout.readline()
                    if not line:
                        raise RuntimeError("rish pipe EOF")
                    stripped = line.rstrip("\r\n")
                    if stripped == marker or stripped.endswith(marker):
                        prefix = stripped[: -len(marker)].strip()
                        if prefix:
                            out_lines.append(prefix)
                        break
                    out_lines.append(stripped)
                return "\n".join(out_lines).strip()
            except Exception:
                if self._rish_proc is not None:
                    try:
                        self._rish_proc.kill()
                    except Exception:
                        pass
                    self._rish_proc = None
        res = subprocess.run(
            ["bash", self.rish_path, "-c", cmd],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
        )
        return res.stdout.strip()

    def _ensure_ready(self) -> None:
        if self.maa_context is None and not self._vd_initialized:
            self._vd_initialized = True
            if os.path.exists(self.rish_path) and self.use_virtual_display:
                self._ensure_shizuku_virtual_display()

    def _ensure_shizuku_virtual_display(self) -> None:
        vd_info = "/sdcard/Download/.vd_info"
        if os.path.exists(vd_info):
            try:
                with open(vd_info, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.startswith("displayId="):
                            self.display_id = int(line.split("=")[1].strip())
                if self.display_id > 0:
                    out = self._run_rish(f"dumpsys display | grep 'mDisplayId={self.display_id}'")
                    if out:
                        log.info(f"复用已存活的虚拟副屏: displayId={self.display_id}")
                        return
            except Exception:
                pass

        jar_dest = "/sdcard/Download/vd_daemon.jar"
        local_jar = os.path.join(os.path.dirname(__file__), "vd_daemon.jar")
        if os.path.exists(local_jar) and not os.path.exists(jar_dest):
            try:
                with open(local_jar, "rb") as src, open(jar_dest, "wb") as dst:
                    dst.write(src.read())
            except Exception as e:
                log.warning(f"复制 vd_daemon.jar 到 /sdcard/Download 失败: {e}")

        if not os.path.exists(jar_dest):
            log.warning("未找到 /sdcard/Download/vd_daemon.jar，将在主屏 (displayId=0) 执行")
            self.display_id = 0
            return

        for stale_file in (
            "/sdcard/Download/.vd_info",
            "/sdcard/Download/.vd_cmd_capture",
            "/sdcard/Download/.vd_cmd_stop",
            "/sdcard/Download/.vd_captured_done",
        ):
            try:
                if os.path.exists(stale_file):
                    os.remove(stale_file)
            except OSError:
                pass
        self._daemon_proc = subprocess.Popen(
            ["bash", self.rish_path, "-c", f"CLASSPATH={jar_dest} exec /system/bin/app_process /system/bin VdDaemon"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for _ in range(30):
            sleep(0.25)
            if os.path.exists(vd_info):
                with open(vd_info, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.startswith("displayId="):
                            self.display_id = int(line.split("=")[1].strip())
                if self.display_id > 0:
                    log.info(f"Shizuku 虚拟副屏 (1920x1080@280dpi) 已创建: displayId={self.display_id}")
                    return
        log.warning("虚拟副屏守护进程启动超时，回退主屏 displayId=0")
        self.display_id = 0

    def stop_virtual_display(self) -> None:
        if self.display_id > 0:
            try:
                with open("/sdcard/Download/.vd_cmd_stop", "wb"):
                    pass
            except OSError:
                if os.path.exists(self.rish_path):
                    self._run_rish("touch /sdcard/Download/.vd_cmd_stop")
            sleep(0.3)
            for tmp_file in (
                "/sdcard/Download/.vd_info",
                "/sdcard/Download/limbus_vd_frame.raw",
                "/sdcard/Download/.aalc_main_screen.raw",
            ):
                try:
                    if os.path.exists(tmp_file):
                        os.remove(tmp_file)
                except OSError:
                    pass
            self.display_id = 0
        self._vd_initialized = False
        self._close_rish_shell()
    def _map_xy(self, x: float, y: float) -> tuple[int, int]:
        if self.maa_context is not None:
            try:
                res = self.maa_context.tasker.controller.resolution
                if res and res[0] > 0 and res[1] > 0:
                    self.raw_width, self.raw_height = int(res[0]), int(res[1])
            except Exception:
                pass
            rx = int(round(float(x) * self.raw_width / 1920.0))
            ry = int(round(float(y) * self.raw_height / 1080.0))
            return max(0, min(self.raw_width - 1, rx)), max(0, min(self.raw_height - 1, ry))
        return max(0, min(1919, int(round(float(x))))), max(0, min(1079, int(round(float(y)))))

    def check_game_alive(self) -> bool:
        if self.maa_context is not None:
            self._check_stopping()
            if not self._app_started:
                return False
            try:
                res = subprocess.run(
                    ["/system/bin/pidof", LIMBUS_PACKAGE],
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if res.returncode == 0 and res.stdout.strip():
                    return True
            except Exception:
                pass
            return self._app_started
        if os.path.exists(self.rish_path):
            self._ensure_ready()
            out = self._run_rish(f"pidof {LIMBUS_PACKAGE}")
            return bool(out.strip())
        return True

    def start_game(self) -> None:
        log.info("正在启动边狱巴士 (Limbus Company)...")
        if self.maa_context is not None:
            self._check_stopping()
            try:
                self.maa_context.tasker.controller.post_start_app(LIMBUS_PACKAGE).wait()
                self._app_started = True
                sleep(5)
                return
            except Exception as e:
                log.warning(f"MaaController post_start_app 异常: {e}")
        if os.path.exists(self.rish_path):
            self._ensure_ready()
            if self.display_id > 0:
                self._run_rish(f"am start --display {self.display_id} -n {LIMBUS_ACTIVITY}")
            else:
                self._run_rish(f"monkey -p {LIMBUS_PACKAGE} -c android.intent.category.LAUNCHER 1")
            sleep(5)

    def close_current_app(self) -> None:
        log.info("正在关闭边狱巴士...")
        if self.maa_context is not None:
            self._app_started = False
            try:
                self.maa_context.tasker.controller.post_stop_app(LIMBUS_PACKAGE).wait()
                sleep(2)
                return
            except Exception as e:
                log.warning(f"MaaController post_stop_app 异常: {e}")
            self._run_rish(f"am force-stop {LIMBUS_PACKAGE}")
            sleep(2)

    def close_simulator(self) -> None:
        self.close_current_app()
        self.stop_virtual_display()

    def screenshot(self) -> np.ndarray:
        if self.maa_context is not None:
            self._check_stopping()
            try:
                ctrl = self.maa_context.tasker.controller
                bgr = ctrl.post_screencap().wait().get()
            except Exception as e:
                if "Failed to get controller" in str(e) or getattr(self.maa_context.tasker, "stopping", False):
                    raise userStopError("MaaFramework 任务已停止") from e
                raise
            if bgr is None or bgr.size == 0:
                raise RuntimeError("MaaController post_screencap 返回空图像")
            h, w = bgr.shape[:2]
            if h != 1080 or w != 1920:
                bgr = cv2.resize(bgr, (1920, 1080), interpolation=cv2.INTER_LINEAR)
            return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        self._ensure_ready()
        if self.display_id > 0 and os.path.exists(self.rish_path):
            done_file = "/sdcard/Download/.vd_captured_done"
            raw_file = "/sdcard/Download/limbus_vd_frame.raw"
            cmd_file = "/sdcard/Download/.vd_cmd_capture"
            try:
                if os.path.exists(done_file):
                    os.remove(done_file)
                with open(cmd_file, "wb"):
                    pass
            except OSError:
                self._run_rish(f"rm -f {done_file} && touch {cmd_file}")
            for _ in range(200):
                if os.path.exists(done_file):
                    break
                sleep(0.015)
            if os.path.exists(raw_file):
                with open(raw_file, "rb") as f:
                    hdr = f.read(12)
                    w, h, row_stride = struct.unpack("<III", hdr)
                    buf = f.read()
                rgba = np.frombuffer(buf, dtype=np.uint8).reshape((h, row_stride // 4, 4))[:, :w, :]
                rgb = cv2.cvtColor(rgba, cv2.COLOR_RGBA2RGB)
                if h != 1080 or w != 1920:
                    rgb = cv2.resize(rgb, (1920, 1080), interpolation=cv2.INTER_LINEAR)
                return rgb

        raw_path = "/sdcard/Download/.aalc_main_screen.raw"
        self._run_rish(f"screencap {raw_path}")
        with open(raw_path, "rb") as f:
            hdr = f.read(16)
            w, h, _ = struct.unpack_from("<III", hdr, 0)
            f.seek(os.path.getsize(raw_path) - w * h * 4)
            buf = f.read(w * h * 4)
        rgba = np.frombuffer(buf, dtype=np.uint8).reshape((h, w, 4))
        rgb = cv2.cvtColor(rgba, cv2.COLOR_RGBA2RGB)
        if h != 1080 or w != 1920:
            rgb = cv2.resize(rgb, (1920, 1080), interpolation=cv2.INTER_LINEAR)
        return rgb

    def mouse_click(self, x, y, times=1, move_back=False) -> bool:
        self._check_stopping()
        self._ensure_ready()
        rx, ry = self._map_xy(x, y)
        log.debug(f"点击位置:({rx},{ry})", stacklevel=2)
        for _ in range(times):
            if self.maa_context is not None:
                self.maa_context.tasker.controller.post_click(rx, ry).wait()
                d_flag = f"-d {self.display_id}" if self.display_id > 0 else ""
                self._run_rish(f"input {d_flag} tap {rx} {ry}")
            if times > 1:
                sleep(0.05)
        self.wait_pause()
        return True

    def mouse_click_blank(self, coordinate=(1, 1), times=1, move_back=False) -> bool:
        log.debug("点击（1，1）空白位置", stacklevel=2)
        bx = coordinate[0] + random.randint(0, 10)
        by = coordinate[1] + random.randint(0, 10)
        return self.mouse_click(bx, by, times=times, move_back=move_back)

    def mouse_to_blank(self, coordinate=(1, 1), move_back=False) -> None:
        log.debug("鼠标移动到空白，避免遮挡", stacklevel=2)
        self.wait_pause()

    def mouse_scroll(self, direction: int = -3) -> bool:
        return False

    def mouse_drag(self, x, y, drag_time=0.1, dx=0, dy=0, move_back=True) -> None:
        self._check_stopping()
        self._ensure_ready()
        rx1, ry1 = self._map_xy(x, y)
        rx2, ry2 = self._map_xy(x + dx, y + dy)
        dur_ms = max(100, int(float(drag_time or 0.3) * 1000))
        if self.maa_context is not None:
            ctrl = self.maa_context.tasker.controller
            ctrl.post_touch_down(rx1, ry1, contact=0, pressure=1).wait()
            steps = max(5, dur_ms // 20)
            step_sleep = (dur_ms / 1000.0) / steps
            for i in range(1, steps + 1):
                cx = int(rx1 + (rx2 - rx1) * i / steps)
                cy = int(ry1 + (ry2 - ry1) * i / steps)
                ctrl.post_touch_move(cx, cy, contact=0, pressure=1).wait()
                sleep(step_sleep)
            sleep(max(0.3, float(drag_time or 0.1) * 0.3))
            ctrl.post_touch_up(contact=0).wait()
        else:
            d_flag = f"-d {self.display_id}" if self.display_id > 0 else ""
            self._run_rish(f"input {d_flag} swipe {rx1} {ry1} {rx2} {ry2} {dur_ms}")
        self.wait_pause()

    def mouse_drag_down(self, x, y, reverse=1, move_back=True) -> None:
        scale = cfg.set_win_size / 1080
        dy = int(300 * scale * reverse)
        self.mouse_drag(x, y, drag_time=0.4, dx=0, dy=dy, move_back=move_back)

    def mouse_swipe_for_scroll(self, x, y, duration=0.3, dx=0, dy=0, move_back=True) -> None:
        self._swipe_for_scroll(x, y, duration, dx, dy, start_settle_seconds=0.0)

    def mouse_swipe_for_team_scroll(self, x, y, duration=0.3, dx=0, dy=0, move_back=True) -> None:
        self._swipe_for_scroll(
            x,
            y,
            duration,
            dx,
            dy,
            start_settle_seconds=TEAM_SCROLL_START_SETTLE_SECONDS,
        )

    def _swipe_for_scroll(
        self,
        x: float,
        y: float,
        duration: float = 0.3,
        dx: float = 0,
        dy: float = 0,
        *,
        start_settle_seconds: float = 0.0,
    ) -> None:
        self._check_stopping()
        self._ensure_ready()
        plan = build_scroll_swipe_plan(x, y, dx=dx, dy=dy, duration=duration)
        if len(plan) <= 1:
            self.wait_pause()
            return

        if self.maa_context is not None:
            ctrl = self.maa_context.tasker.controller
            sx, sy = self._map_xy(*plan[0][0])
            ctrl.post_touch_down(sx, sy, contact=0, pressure=1).wait()
            if start_settle_seconds > 0:
                sleep(start_settle_seconds)
            prev_x, prev_y = sx, sy
            for point, seg_dur in plan[1:]:
                tx, ty = self._map_xy(*point)
                steps = max(2, int(max(seg_dur, 0.02) / 0.015))
                step_sleep = max(0.005, seg_dur / steps)
                for s in range(1, steps + 1):
                    ix = int(round(prev_x + (tx - prev_x) * s / steps))
                    iy = int(round(prev_y + (ty - prev_y) * s / steps))
                    ctrl.post_touch_move(ix, iy, contact=0, pressure=1).wait()
                    sleep(step_sleep)
                prev_x, prev_y = tx, ty
            sleep(0.12)
            ctrl.post_touch_up(contact=0).wait()
        else:
            rx1, ry1 = self._map_xy(x, y)
            rx2, ry2 = self._map_xy(x + dx, y + dy)
            dur_ms = max(150, int(duration * 1000))
            d_flag = f"-d {self.display_id}" if self.display_id > 0 else ""
            self._run_rish(f"input {d_flag} swipe {rx1} {ry1} {rx2} {ry2} {dur_ms}")
        self.wait_pause()

    def mouse_drag_link(self, position: list, drag_time=0.1, move_back=False) -> None:
        if not position:
            return
        if len(position) == 1:
            self.mouse_click(position[0][0], position[0][1])
            return
        self._check_stopping()
        self._ensure_ready()
        interpolated: list[tuple[int, int]] = []
        for idx in range(len(position) - 1):
            p0 = self._map_xy(position[idx][0], position[idx][1])
            p1 = self._map_xy(position[idx + 1][0], position[idx + 1][1])
            dist = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
            steps = max(3, int(dist // 40))
            for s in range(steps):
                t = s / float(steps)
                ix = int(round(p0[0] + (p1[0] - p0[0]) * t))
                iy = int(round(p0[1] + (p1[1] - p0[1]) * t))
                interpolated.append((ix, iy))
        interpolated.append(self._map_xy(position[-1][0], position[-1][1]))

        if self.maa_context is not None:
            ctrl = self.maa_context.tasker.controller
            x0, y0 = interpolated[0]
            ctrl.post_touch_down(x0, y0, contact=0, pressure=1).wait()
            sleep(0.02)
            step_delay = max(0.008, float(drag_time or 0.1) / max(len(interpolated), 1))
            for pt in interpolated[1:]:
                ctrl.post_touch_move(pt[0], pt[1], contact=0, pressure=1).wait()
                sleep(step_delay)
            sleep(0.2)
            ctrl.post_touch_up(contact=0).wait()
        else:
            d_flag = f"-d {self.display_id}" if self.display_id > 0 else ""
            x0, y0 = interpolated[0]
            cmds = [f"input {d_flag} motionevent DOWN {x0} {y0}"]
            for pt in interpolated[1:]:
                cmds.append(f"input {d_flag} motionevent MOVE {pt[0]} {pt[1]}")
            cmds.append("sleep 0.2")
            cmds.append(f"input {d_flag} motionevent UP {interpolated[-1][0]} {interpolated[-1][1]}")
            self._run_rish(" && ".join(cmds))
        self.wait_pause()

    def key_press(self, key: str) -> None:
        self._check_stopping()
        self._ensure_ready()
        keycode = ANDROID_KEY_MAP.get(key.lower())
        if keycode is None:
            log.warning(f"未知的 Android 按键映射: {key}")
            return
        log.debug(f"发送按键: {key} (keycode={keycode})", stacklevel=2)
        if self.maa_context is not None:
            self.maa_context.tasker.controller.post_click_key(keycode).wait()
        else:
            d_flag = f"-d {self.display_id}" if self.display_id > 0 else ""
            self._run_rish(f"input {d_flag} keyevent {keycode}")
        self.wait_pause()

    def input_text(self, text: str) -> None:
        if not text:
            return
        self._check_stopping()
        self._ensure_ready()
        log.debug(f"输入文本: {text}", stacklevel=2)
        if self.maa_context is not None:
            self.maa_context.tasker.controller.post_input_text(text).wait()
        else:
            d_flag = f"-d {self.display_id}" if self.display_id > 0 else ""
            safe_text = text.replace("'", "")
            self._run_rish(f"input {d_flag} text '{safe_text}'")
        self.wait_pause()
