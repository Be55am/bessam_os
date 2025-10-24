import threading
import time
from typing import Optional

try:
    from evdev import InputDevice, list_devices, ecodes
except Exception:  # pragma: no cover
    InputDevice = None  # type: ignore
    list_devices = None  # type: ignore
    ecodes = None  # type: ignore


class EvdevConfirm:
    """Listen for KEY_POWER from gpio-keys (gpio-shutdown overlay) as confirm.

    Non-fatal if evdev is unavailable or device not found.
    """

    def __init__(self) -> None:
        self._device_path: Optional[str] = None
        self._device: Optional[InputDevice] = None
        self._pressed: bool = False
        self._thread: Optional[threading.Thread] = None
        self._stop = False
        if InputDevice is None or list_devices is None or ecodes is None:
            return
        self._device_path = self._find_device_path()
        if self._device_path:
            self._start_thread()

    @property
    def available(self) -> bool:
        return self._device_path is not None

    def is_pressed(self) -> bool:
        return bool(self._pressed)

    def close(self) -> None:
        self._stop = True
        try:
            if self._device is not None:
                self._device.close()
        except Exception:
            pass

    def _find_device_path(self) -> Optional[str]:
        try:
            for path in list_devices():
                dev = InputDevice(path)
                name = (dev.name or "").lower()
                if "gpio" in name and "key" in name:
                    caps = dev.capabilities().get(ecodes.EV_KEY, [])
                    if ecodes.KEY_POWER in caps:
                        dev.close()
                        return path
                dev.close()
        except Exception:
            return None
        return None

    def _start_thread(self) -> None:
        def loop() -> None:
            while not self._stop:
                try:
                    self._device = InputDevice(self._device_path) if self._device_path else None
                    if self._device is None:
                        time.sleep(1.0)
                        continue
                    for event in self._device.read_loop():
                        if self._stop:
                            break
                        if event.type == ecodes.EV_KEY and event.code == ecodes.KEY_POWER:
                            self._pressed = (event.value != 0)
                except Exception:
                    time.sleep(1.0)
                finally:
                    try:
                        if self._device is not None:
                            self._device.close()
                    except Exception:
                        pass
                    self._device = None
        self._thread = threading.Thread(target=loop, daemon=True)
        self._thread.start()
