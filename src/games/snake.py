import random
from dataclasses import dataclass
from typing import List, Tuple

from PIL import ImageDraw


@dataclass
class Point:
    x: int
    y: int


class SnakeGame:
    def __init__(self, width_px: int = 128, height_px: int = 64) -> None:
        self.cell_size = 8
        self.cols = width_px // self.cell_size
        self.rows = height_px // self.cell_size
        self.reset()

    def reset(self) -> None:
        midx = self.cols // 2
        midy = self.rows // 2
        self.snake: List[Point] = [Point(midx, midy), Point(midx - 1, midy)]
        self.direction: Tuple[int, int] = (1, 0)  # Right
        self.spawn_food()
        self.game_over = False
        self.score = 0
        self._tick_counter = 0
        self.speed_ticks = 5  # lower is faster

    def spawn_food(self) -> None:
        while True:
            p = Point(random.randint(0, self.cols - 1), random.randint(0, self.rows - 1))
            if p not in self.snake:
                self.food = p
                return

    def change_direction_clockwise(self, clockwise: bool) -> None:
        dx, dy = self.direction
        if clockwise:
            self.direction = (dy, -dx)
        else:
            self.direction = (-dy, dx)

    def update(self) -> None:
        if self.game_over:
            return
        self._tick_counter += 1
        if self._tick_counter % self.speed_ticks != 0:
            return
        head = self.snake[0]
        nx = (head.x + self.direction[0]) % self.cols
        ny = (head.y + self.direction[1]) % self.rows
        new_head = Point(nx, ny)
        if new_head in self.snake:
            self.game_over = True
            return
        self.snake.insert(0, new_head)
        if new_head == self.food:
            self.score += 1
            if self.speed_ticks > 2 and self.score % 3 == 0:
                self.speed_ticks -= 1
            self.spawn_food()
        else:
            self.snake.pop()

    def render(self, image, draw: ImageDraw.ImageDraw) -> None:
        # Draw grid elements
        # Food
        draw.rectangle(self._cell_rect(self.food), outline=255, fill=0)
        # Snake
        for idx, p in enumerate(self.snake):
            rect = self._cell_rect(p)
            if idx == 0:
                draw.rectangle(rect, outline=255, fill=255)
            else:
                draw.rectangle(rect, outline=255, fill=0)
        # Score
        draw.text((2, 2), f"Score: {self.score}", fill=255)
        if self.game_over:
            draw.text((32, 28), "GAME OVER", fill=255)

    def _cell_rect(self, p: Point) -> Tuple[int, int, int, int]:
        x1 = p.x * self.cell_size
        y1 = p.y * self.cell_size
        return (x1 + 1, y1 + 1, x1 + self.cell_size - 2, y1 + self.cell_size - 2)
