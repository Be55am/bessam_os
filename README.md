# Pi OLED Controller with Rotary Encoder, Docker Control, and Mini-Games

## Features
- Rotary encoder + buttons UI on 1.3" 128x64 I2C OLED
- Smooth, non-blocking UI loop with event queue
- System actions: restart, shutdown, IP, CPU temp, disk, mem, update
- Docker control: list, start, stop, restart containers (SDK with CLI fallback)
- Mini-game: Snake optimized for 128x64 display
- Simple animations (spinner during long tasks)

## Hardware
- OLED 128x64 I2C: SCL (Pin 5), SDA (Pin 3), 3.3V, GND
- EC11 Rotary Encoder: A (GPIO27, Pin 13), B (GPIO22, Pin 15), Button (GPIO10, Pin 19)
- Back Button: GPIO17 (Pin 11)
- Confirm Button: GPIO5 (Pin 29)

Adjust GPIOs in `src/main.py` if wired differently.

## Install
```bash
sudo apt update
sudo apt install -y python3-pip python3-dev python3-venv libopenjp2-7 libtiff5
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip wheel
pip install -r requirements.txt
```

Enable I2C in raspi-config and reboot.

## Run
```bash
source .venv/bin/activate
python3 -u src/main.py
```

## Optional: systemd service
Create `/etc/systemd/system/bessam-os.service`:
```ini
[Unit]
Description=Pi OLED Controller (bessam-os)
After=network.target docker.service

[Service]
User=pi
WorkingDirectory=/home/pi/bessam_os
ExecStart=/home/pi/bessam_os/.venv/bin/python -u src/main.py
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
```
Then:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now bessam-os
```

## Notes
- Docker SDK preferred; falls back to CLI. Ensure `docker` group membership for your user.
- Font fallback uses PIL default if DejaVuSans not found.
- Quit the app with Back+Confirm held for 2 seconds.
