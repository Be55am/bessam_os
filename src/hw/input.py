import atexit
from typing import Dict

try:
    import RPi.GPIO as GPIO
except Exception as e:  # pragma: no cover
    raise RuntimeError(f"RPi.GPIO not available: {e}")


class Inputs:
    def __init__(self, back_gpio: int, confirm_gpio: int, push_gpio: int, pull_up: bool = True) -> None:
        self._pull_up = pull_up
        GPIO.setmode(GPIO.BCM)
        pud = GPIO.PUD_UP if pull_up else GPIO.PUD_OFF
        self._pins: Dict[str, int] = {
            "back": back_gpio,
            "confirm": confirm_gpio,
            "push": push_gpio,
        }
        for pin in self._pins.values():
            GPIO.setup(pin, GPIO.IN, pull_up_down=pud)
        atexit.register(self.close)

    def read_states(self) -> Dict[str, bool]:
        states: Dict[str, bool] = {}
        for name, pin in self._pins.items():
            val = GPIO.input(pin)
            pressed = (val == GPIO.LOW) if self._pull_up else (val == GPIO.HIGH)
            states[name] = pressed
        return states

    def close(self) -> None:
        try:
            GPIO.cleanup()
        except Exception:
            pass
