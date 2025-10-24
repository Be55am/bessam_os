import threading
import time
from queue import Queue
from typing import Callable, List, Optional

from gpiozero import Button, RotaryEncoder

from src.core.events import Button as ButtonEvent, Rotate, Tick, TaskDone, Event
from src.core.docker_actions import DockerManager
from src.core import system_actions
from src.games.snake import SnakeGame
from src.hw.display import OledDisplay


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
        # GPIO setup
        self.btn_back = Button(17, pull_up=True, bounce_time=0.1)
        self.btn_confirm = Button(5, pull_up=True, bounce_time=0.1)
        self.btn_push = Button(10, pull_up=True, bounce_time=0.1)
        self.encoder = RotaryEncoder(22, 27, bounce_time=0.002)
        self._last_steps = self.encoder.steps
        # Register input callbacks -> queue events only
        self.btn_back.when_pressed = lambda: self.events.put(ButtonEvent(type="button", name="back"))
        self.btn_confirm.when_pressed = lambda: self.events.put(ButtonEvent(type="button", name="confirm"))
        self.btn_push.when_pressed = lambda: self.events.put(ButtonEvent(type="button", name="push"))
        # State
        self.mode: str = "menu"  # menu | progress | game_snake | docker_list | docker_container
        self.spinner_frame = 0
        self.menu_stack: List[tuple[str, List[tuple[str, Callable[[], None]]], int]] = []
        self.current_menu_items: List[tuple[str, Callable[[], None]]] = []
        self.current_index = 0
        self.current_container_id: Optional[str] = None
        self.game: Optional[SnakeGame] = None
        # Init UI
        self._init_menus()
        self.display.draw_text("Pi Control\nSystem v2.0\n\nInitializing...")
        time.sleep(1.0)
        self._show_menu()

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
                # Pause toggle could be implemented; keep simple
                pass
            elif name == "back":
                self._show_menu()
                self.game = None
        elif self.mode == "progress":
            # ignore buttons during progress
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

    def _handle_tick(self) -> None:
        # Poll encoder steps -> convert to rotate events
        steps = self.encoder.steps
        if steps != self._last_steps:
            delta = 1 if steps > self._last_steps else -1
            self._last_steps = steps
            self._handle_rotate(delta)
        # Periodic UI updates
        if self.mode == "progress":
            self.spinner_frame = (self.spinner_frame + 1) % 12
            self.display.draw_spinner(self._progress_message, self.spinner_frame)
        elif self.mode == "game_snake" and self.game:
            self.game.update()
            self._render_game()

    def run(self) -> None:
        hold_start: Optional[float] = None
        while True:
            try:
                try:
                    event = self.events.get(timeout=0.05)
                except Exception:
                    event = Tick(type="tick")
                if isinstance(event, ButtonEvent):
                    # Support hold Back+Confirm to exit
                    if event.name in ("back", "confirm"):
                        now = time.monotonic()
                        if self.btn_back.is_pressed and self.btn_confirm.is_pressed:
                            if hold_start is None:
                                hold_start = now
                            elif now - hold_start > 2.0:
                                self.display.draw_text("Exiting...")
                                time.sleep(0.5)
                                self.display.clear()
                                return
                        else:
                            hold_start = None
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
