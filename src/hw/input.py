import atexit
from typing import Dict, Tuple

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


class EncoderPoller:
    """Simple quadrature encoder poller.

    Accumulates transitions and emits +/-1 per detent (approx 2 ticks by default).
    """

    _TRANSITIONS: Dict[Tuple[int, int], int] = {
        (0, 1): +1,
        (1, 3): +1,
        (3, 2): +1,
        (2, 0): +1,
        (0, 2): -1,
        (2, 3): -1,
        (3, 1): -1,
        (1, 0): -1,
    }

    def __init__(self, a_gpio: int, b_gpio: int, pull_up: bool = True, ticks_per_detent: int = 2) -> None:
        self._a = a_gpio
        self._b = b_gpio
        self._pull_up = pull_up
        self._ticks_per_detent = max(1, ticks_per_detent)
        pud = GPIO.PUD_UP if pull_up else GPIO.PUD_OFF
        # Assume GPIO.setmode already called in Inputs; if not, set BCM
        try:
            GPIO.getmode()
        except Exception:
            GPIO.setmode(GPIO.BCM)
        GPIO.setup(self._a, GPIO.IN, pull_up_down=pud)
        GPIO.setup(self._b, GPIO.IN, pull_up_down=pud)
        self._last_state = self._read_state()
        self._accumulator = 0

    def _read_state(self) -> int:
        a = GPIO.input(self._a)
        b = GPIO.input(self._b)
        a_bit = 0 if (a == GPIO.LOW and self._pull_up) else (1 if (a == GPIO.HIGH and self._pull_up) else a)
        b_bit = 0 if (b == GPIO.LOW and self._pull_up) else (1 if (b == GPIO.HIGH and self._pull_up) else b)
        return (a_bit << 1) | b_bit

    def read_delta(self) -> int:
        """Return -n..+n steps since last call."""
        state = self._read_state()
        if state == self._last_state:
            return 0
        delta = self._TRANSITIONS.get((self._last_state, state), 0)
        self._last_state = state
        if delta == 0:
            return 0
        self._accumulator += delta
        steps = 0
        while abs(self._accumulator) >= self._ticks_per_detent:
            steps += 1 if self._accumulator > 0 else -1
            self._accumulator -= self._ticks_per_detent if self._accumulator > 0 else -self._ticks_per_detent
        return steps
