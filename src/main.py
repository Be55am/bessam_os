import threading
import time
import os
from queue import Queue
from typing import Callable, List, Optional

from src.core.events import Button as ButtonEvent, Rotate, Tick, TaskDone, Event
from src.core.docker_actions import DockerManager
from src.core import system_actions
from src.games.snake import SnakeGame
from src.hw.display import OledDisplay
from src.hw.input import Inputs, EncoderPoller


def _env_int(name: str, default: int) -> int:
    try:
        v = os.getenv(name)
        return int(v) if v is not None and v != "" else default
    except Exception:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        v = os.getenv(name)
        return float(v) if v is not None and v != "" else default
    except Exception:
        return default


def _env_bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None or v == "":
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


BACK_GPIO = _env_int("BESSAM_BACK_GPIO", 17)
CONFIRM_GPIO = _env_int("BESSAM_CONFIRM_GPIO", 5)
PUSH_GPIO = _env_int("BESSAM_PUSH_GPIO", 10)
ENC_A_GPIO = _env_int("BESSAM_ENC_A_GPIO", 22)
ENC_B_GPIO = _env_int("BESSAM_ENC_B_GPIO", 27)
ENC_TICKS_PER_DETENT = _env_int("BESSAM_ENC_TICKS_PER_DETENT", 4)
POLL_INTERVAL_SEC = _env_float("BESSAM_POLL_INTERVAL_SEC", 0.005)
DEBOUNCE_SEC = _env_float("BESSAM_DEBOUNCE_SEC", 0.03)
PULL_UP = _env_bool("BESSAM_PULL_UP", True)
ENC_REVERSE = _env_bool("BESSAM_ENC_REVERSE", False)
DEBUG = _env_bool("BESSAM_DEBUG", False)
USE_PUSH_AS_CONFIRM = _env_bool("BESSAM_USE_PUSH_AS_CONFIRM", True)
BACK_INVERT = _env_bool("BESSAM_BACK_INVERT", False)
CONFIRM_INVERT = _env_bool("BESSAM_CONFIRM_INVERT", False)
PUSH_INVERT = _env_bool("BESSAM_PUSH_INVERT", False)


class BackgroundWorker:
    def __init__(self, queue: Queue) -> None:
        self._queue = queue
        self._thread: Optional[threading.Thread] = None

    def run(self, func: Callable[[], str]) -> None:
        if self._thread and self._thread.is_alive():
            return
        def target() -> None:
            ok = True
            msg = None
            try:
                msg = func()
            except Exception as e:
                ok = False
                msg = str(e)
            self._queue.put(TaskDone(type="task_done", ok=ok, message=msg))
        self._thread = threading.Thread(target=target, daemon=True)
        self._thread.start()


class App:
    def __init__(self) -> None:
        self.events: Queue[Event] = Queue()
        self.display = OledDisplay()
        self.docker = DockerManager()
        self.worker = BackgroundWorker(self.events)
        self.inputs = Inputs(BACK_GPIO, CONFIRM_GPIO, PUSH_GPIO, pull_up=PULL_UP)
        self.encoder = EncoderPoller(ENC_A_GPIO, ENC_B_GPIO, pull_up=PULL_UP, ticks_per_detent=ENC_TICKS_PER_DETENT)
        # State
        self.mode: str = "menu"
        self.spinner_frame = 0
        self.menu_stack: List[tuple[str, List[tuple[str, Callable[[], None]]], int]] = []
        self.current_menu_items: List[tuple[str, Callable[[], None]]] = []
        self.current_index = 0
        self.current_container_id: Optional[str] = None
        self.game: Optional[SnakeGame] = None
        # Button debouncing
        self._btn_state = {"back": False, "confirm": False, "push": False}
        self._btn_last_change = {"back": 0.0, "confirm": 0.0, "push": 0.0}
        # Diagnostics
        self._input_test_enc_total = 0
        self._input_test_last_draw = 0.0
        # Init UI
        self._init_menus()
        self.display.draw_text("Pi Control\nSystem v2.0\n\nInitializing...")
        time.sleep(1.0)
        self._show_menu()

    def _debug(self, msg: str) -> None:
        if DEBUG:
            print(msg, flush=True)

    def _init_menus(self) -> None:
        def push_menu(title: str, items: List[tuple[str, Callable[[], None]]]) -> None:
            self.menu_stack.append((title, self.current_menu_items, self.current_index))
            self.current_menu_items = items
            self.current_index = 0
            self._show_menu()

        def pop_menu() -> None:
            if self.menu_stack:
                title, items, idx = self.menu_stack.pop()
                self.current_menu_items = items
                self.current_index = idx
                self._show_menu()

        self.push_menu = push_menu  # type: ignore[attr-defined]
        self.pop_menu = pop_menu    # type: ignore[attr-defined]

        def do_reboot() -> None:
            self._start_progress(lambda: (system_actions.reboot() or "Rebooting..."), "Rebooting in 3s...")

        def do_shutdown() -> None:
            self._start_progress(lambda: (system_actions.shutdown() or "Shutting down..."), "Shutting down in 3s...")

        def show_info() -> None:
            self.display.draw_text(system_actions.get_hostname_kernel())

        def show_ip() -> None:
            self.display.draw_text(system_actions.get_ip())

        def show_cpu() -> None:
            self.display.draw_text(system_actions.get_cpu_temp())

        def show_disk() -> None:
            self.display.draw_text(system_actions.get_disk_usage())

        def show_mem() -> None:
            self.display.draw_text(system_actions.get_memory_info())

        def do_update() -> None:
            self._start_progress(system_actions.apt_update, "Updating... This may take a while")

        def exit_app() -> None:
            self.display.draw_text("Goodbye!")
            time.sleep(0.8)
            self.display.clear()
            raise SystemExit(0)

        def docker_menu() -> None:
            self.mode = "docker_list"
            self._refresh_docker_list()

        def games_menu() -> None:
            items: List[tuple[str, Callable[[], None]]] = [
                ("Snake", self._start_snake),
            ]
            self.push_menu("Games", items)

        def input_test() -> None:
            self.mode = "input_test"
            self._input_test_enc_total = 0
            self._input_test_last_draw = 0.0
            self._render_input_test(force=True)

        items: List[tuple[str, Callable[[], None]]] = [
            ("Docker", docker_menu),
            ("System Info", show_info),
            ("Check IP", show_ip),
            ("CPU Temp", show_cpu),
            ("Disk Usage", show_disk),
            ("Memory Info", show_mem),
            ("Update System", do_update),
            ("Games", games_menu),
            ("Input Test", input_test),
            ("Restart Pi", do_reboot),
            ("Shutdown", do_shutdown),
            ("Exit", exit_app),
        ]
        self.current_menu_items = items
        self.current_index = 0

    def _show_menu(self) -> None:
        self.mode = "menu"
        labels = [name for name, _ in self.current_menu_items]
        self.display.draw_menu(labels, self.current_index)

    def _start_progress(self, func: Callable[[], str], message: str) -> None:
        self.mode = "progress"
        self._progress_message = message
        self.spinner_frame = 0
        self.worker.run(func)
        self.display.draw_spinner(message, self.spinner_frame)

    def _refresh_docker_list(self) -> None:
        self.mode = "docker_list"
        try:
            containers = self.docker.list_containers(all_containers=True)
            self._docker_list = containers
            labels = [f"{c['name']} [{c['status']}]" for c in containers]
            if not labels:
                labels = ["<no containers>"]
            self.display.draw_menu(labels, self.current_index)
        except Exception as e:
            self.display.draw_text(f"Docker error:\n{str(e)[:20]}")

    def _open_container_actions(self, idx: int) -> None:
        if not hasattr(self, "_docker_list") or not self._docker_list:
            return
        c = self._docker_list[idx]
        self.current_container_id = c["id"]
        name = c["name"]
        def do_start() -> None:
            ident = self.current_container_id or name
            self._start_progress(lambda: self.docker.start(ident), f"Starting {name}...")
        def do_stop() -> None:
            ident = self.current_container_id or name
            self._start_progress(lambda: self.docker.stop(ident), f"Stopping {name}...")
        def do_restart() -> None:
            ident = self.current_container_id or name
            self._start_progress(lambda: self.docker.restart(ident), f"Restarting {name}...")
        items = [("Start", do_start), ("Stop", do_stop), ("Restart", do_restart), ("Back", self.pop_menu)]
        self.push_menu(f"{name}", items)

    def _start_snake(self) -> None:
        self.mode = "game_snake"
        self.game = SnakeGame(self.display.width, self.display.height)
        self._render_game()

    def _render_game(self) -> None:
        if not self.game:
            return
        image = self.display.new_image()
        draw = __import__("PIL").ImageDraw.Draw(image)
        self.game.render(image, draw)
        self.display.show_image(image)

    def _render_input_test(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._input_test_last_draw < 0.1:
            return
        self._input_test_last_draw = now
        raw = self.inputs.read_states()
        # Apply invert flags for display
        back = raw.get("back", False)
        conf = raw.get("confirm", False)
        push = raw.get("push", False)
        if BACK_INVERT:
            back = not back
        if CONFIRM_INVERT:
            conf = not conf
        if PUSH_INVERT:
            push = not push
        text = (
            f"Back:{'1' if back else '0'} Conf:{'1' if conf else '0'}\n"
            f"Push:{'1' if push else '0'} Enc:{self._input_test_enc_total}"
        )
        self.display.draw_text(text)

    def _handle_button(self, name: str) -> None:
        self._debug(f"button:{name}")
        if self.mode == "menu":
            if name == "confirm" and self.current_menu_items:
                _, action = self.current_menu_items[self.current_index]
                action()
            elif name == "back":
                self.pop_menu()
        elif self.mode == "docker_list":
            if name == "confirm" and hasattr(self, "_docker_list") and self._docker_list:
                self._open_container_actions(self.current_index)
            elif name == "back":
                self._show_menu()
        elif self.mode == "input_test":
            if name == "back":
                self._show_menu()
        elif self.mode == "game_snake":
            if not self.game:
                return
            if name == "confirm":
                pass
            elif name == "back":
                self._show_menu()
                self.game = None
        elif self.mode == "progress":
            pass

    def _handle_rotate(self, delta: int) -> None:
        if ENC_REVERSE:
            delta = -delta
        self._debug(f"enc:{delta}")
        if self.mode in ("menu", "docker_list"):
            items_len = len(self.current_menu_items) if self.mode == "menu" else len(getattr(self, "_docker_list", [])) or 1
            if delta > 0:
                self.current_index = (self.current_index + 1) % items_len
            else:
                self.current_index = (self.current_index - 1) % items_len
            if self.mode == "menu":
                labels = [name for name, _ in self.current_menu_items]
                self.display.draw_menu(labels, self.current_index)
            else:
                self._refresh_docker_list()
        elif self.mode == "input_test":
            self._input_test_enc_total += delta
            self._render_input_test(force=True)
        elif self.mode == "game_snake" and self.game:
            self.game.change_direction_clockwise(clockwise=(delta > 0))
            self._render_game()

    def _poll_buttons(self) -> None:
        raw_states = self.inputs.read_states()
        if DEBUG:
            self._debug(f"raw:{raw_states}")
        # Apply per-button invert
        back = raw_states.get("back", False)
        confirm = raw_states.get("confirm", False)
        push = raw_states.get("push", False)
        if BACK_INVERT:
            back = not back
        if CONFIRM_INVERT:
            confirm = not confirm
        if PUSH_INVERT:
            push = not push
        # Optionally treat push as confirm
        if USE_PUSH_AS_CONFIRM:
            confirm = confirm or push
        now = time.monotonic()
        for name, pressed in ("back", back), ("confirm", confirm):
            last_pressed = self._btn_state[name]
            if pressed != last_pressed:
                last_change = self._btn_last_change[name]
                if now - last_change >= DEBOUNCE_SEC:
                    self._btn_last_change[name] = now
                    self._btn_state[name] = pressed
                    if pressed:
                        self._handle_button(name)
        # Exit on hold Back+Confirm
        if self._btn_state["back"] and self._btn_state["confirm"]:
            hold = getattr(self, "_hold_start", None)
            if hold is None:
                self._hold_start = now
            elif now - hold > 2.0:
                self.display.draw_text("Exiting...")
                time.sleep(0.5)
                self.display.clear()
                raise SystemExit(0)
        else:
            self._hold_start = None  # type: ignore[assignment]

    def _handle_tick(self) -> None:
        delta = self.encoder.read_delta()
        if delta:
            self._handle_rotate(delta)
        self._poll_buttons()
        if self.mode == "progress":
            self.spinner_frame = (self.spinner_frame + 1) % 12
            self.display.draw_spinner(self._progress_message, self.spinner_frame)
        elif self.mode == "game_snake" and self.game:
            self.game.update()
            self._render_game()
        elif self.mode == "input_test":
            self._render_input_test()

    def run(self) -> None:
        while True:
            try:
                time.sleep(POLL_INTERVAL_SEC)
                self._handle_tick()
                while not self.events.empty():
                    event = self.events.get_nowait()
                    if isinstance(event, ButtonEvent):
                        self._handle_button(event.name)
                    elif isinstance(event, Rotate):
                        self._handle_rotate(event.delta)
                    elif isinstance(event, TaskDone):
                        msg = event.message or ("Done" if event.ok else "Failed")
                        self.display.draw_text(msg)
                        time.sleep(1.0)
                        if self.mode == "docker_list":
                            self._refresh_docker_list()
                        else:
                            self._show_menu()
            except KeyboardInterrupt:
                break
            except SystemExit:
                break
            except Exception as e:
                self.display.draw_text(f"Error: {str(e)[:20]}")
                time.sleep(1.0)
        self.display.clear()


if __name__ == "__main__":
    App().run()
