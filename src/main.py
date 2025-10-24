import threading
import time
import os
from queue import Queue
from typing import Callable, List, Optional

from gpiozero import RotaryEncoder
from src.core.events import Button as ButtonEvent, Rotate, Tick, TaskDone, Event
from src.core.docker_actions import DockerManager
from src.core import system_actions
from src.games.snake import SnakeGame
from src.hw.display import OledDisplay
from src.hw.input import Inputs

try:
    from gpiozero.pins.rpigpio import RPiGPIOFactory  # Prefer RPi.GPIO for encoder
except Exception:
    RPiGPIOFactory = None  # type: ignore
try:
    from gpiozero.pins.lgpio import LGPIOFactory
except Exception:
    LGPIOFactory = None  # type: ignore
try:
    from gpiozero.pins.pigpio import PiGPIOFactory
except Exception:
    PiGPIOFactory = None  # type: ignore


def _env_int(name: str, default: int) -> int:
    try:
        v = os.getenv(name)
        return int(v) if v is not None and v != "" else default
    except Exception:
        return default


BACK_GPIO = _env_int("BESSAM_BACK_GPIO", 17)
CONFIRM_GPIO = _env_int("BESSAM_CONFIRM_GPIO", 5)
PUSH_GPIO = _env_int("BESSAM_PUSH_GPIO", 10)
ENC_A_GPIO = _env_int("BESSAM_ENC_A_GPIO", 22)
ENC_B_GPIO = _env_int("BESSAM_ENC_B_GPIO", 27)


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
        self.inputs = Inputs(BACK_GPIO, CONFIRM_GPIO, PUSH_GPIO, pull_up=True)
        self._init_encoder()
        self._last_steps = self.encoder.steps
        # State
        self.mode: str = "menu"
        self.spinner_frame = 0
        self.menu_stack: List[tuple[str, List[tuple[str, Callable[[], None]]], int]] = []
        self.current_menu_items: List[tuple[str, Callable[[], None]]] = []
        self.current_index = 0
        self.current_container_id: Optional[str] = None
        self.game: Optional[SnakeGame] = None
        # Button polling state
        self._btn_state = {"back": False, "confirm": False, "push": False}
        # Init UI
        self._init_menus()
        self.display.draw_text("Pi Control\nSystem v2.0\n\nInitializing...")
        time.sleep(1.0)
        self._show_menu()

    def _candidate_factories(self) -> List:
        order = []
        env = os.getenv("GPIOZERO_PIN_FACTORY", "").strip().lower()
        mapping = {
            "rpigpio": RPiGPIOFactory,
            "lgpio": LGPIOFactory,
            "pigpio": PiGPIOFactory,
        }
        if env in mapping and mapping[env] is not None:
            order.append(mapping[env])
        for f in (RPiGPIOFactory, LGPIOFactory, PiGPIOFactory):
            if f is not None and f not in order:
                order.append(f)
        return order

    def _init_encoder(self) -> None:
        last_error: Optional[Exception] = None
        for Factory in self._candidate_factories():
            try:
                pf = Factory()  # type: ignore[call-arg]
                encoder = RotaryEncoder(ENC_A_GPIO, ENC_B_GPIO, bounce_time=0.002, pin_factory=pf)
                self.pin_factory = pf  # type: ignore[attr-defined]
                self.encoder = encoder
                return
            except Exception as e:
                last_error = e
                try:
                    encoder.close()  # type: ignore[name-defined]
                except Exception:
                    pass
                continue
        self.display.draw_text(f"Encoder init failed:\n{str(last_error)[:22]}")
        time.sleep(2.0)
        raise last_error if last_error else RuntimeError("Encoder init failed")

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

        items: List[tuple[str, Callable[[], None]]] = [
            ("Docker", docker_menu),
            ("System Info", show_info),
            ("Check IP", show_ip),
            ("CPU Temp", show_cpu),
            ("Disk Usage", show_disk),
            ("Memory Info", show_mem),
            ("Update System", do_update),
            ("Games", games_menu),
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

    def _handle_button(self, name: str) -> None:
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
        elif self.mode == "game_snake" and self.game:
            self.game.change_direction_clockwise(clockwise=(delta > 0))
            self._render_game()

    def _poll_buttons(self) -> None:
        states = self.inputs.read_states()
        back = states.get("back", False)
        confirm = states.get("confirm", False)
        push = states.get("push", False)
        now = time.monotonic()
        if back and confirm:
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
        if back and not self._btn_state["back"]:
            self._handle_button("back")
        if confirm and not self._btn_state["confirm"]:
            self._handle_button("confirm")
        if push and not self._btn_state["push"]:
            self._handle_button("push")
        self._btn_state["back"] = back
        self._btn_state["confirm"] = confirm
        self._btn_state["push"] = push

    def _handle_tick(self) -> None:
        steps = self.encoder.steps
        if steps != self._last_steps:
            delta = 1 if steps > self._last_steps else -1
            self._last_steps = steps
            self._handle_rotate(delta)
        self._poll_buttons()
        if self.mode == "progress":
            self.spinner_frame = (self.spinner_frame + 1) % 12
            self.display.draw_spinner(self._progress_message, self.spinner_frame)
        elif self.mode == "game_snake" and self.game:
            self.game.update()
            self._render_game()

    def run(self) -> None:
        while True:
            try:
                try:
                    event = self.events.get(timeout=0.05)
                except Exception:
                    event = Tick(type="tick")
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
                else:
                    self._handle_tick()
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
