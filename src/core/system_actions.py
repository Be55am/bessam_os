import subprocess
import time
from typing import Tuple


def get_hostname_kernel() -> str:
    hostname = subprocess.check_output(["hostname"]).decode().strip()
    kernel = subprocess.check_output(["uname", "-r"]).decode().strip()
    return f"Host: {hostname}\nKernel: {kernel}"


def get_ip() -> str:
    ip = subprocess.check_output(["hostname", "-I"]).decode().strip().split()[0]
    return f"IP Address:\n{ip}"


def get_cpu_temp() -> str:
    try:
        temp = subprocess.check_output(["vcgencmd", "measure_temp"]).decode().strip()
        return f"CPU Temp:\n{temp}"
    except Exception:
        # Fallback using thermal zone
        with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
            milli = int(f.read().strip())
        return f"CPU Temp:\n{milli/1000.0:.1f} C"


def get_disk_usage() -> str:
    df = subprocess.check_output(["df", "-h", "/"]).decode().split("\n")[1]
    parts = df.split()
    return f"Disk:\nUsed: {parts[2]}\nFree: {parts[3]}\n{parts[4]} used"


def get_memory_info() -> str:
    mem = subprocess.check_output(["free", "-h"]).decode().split("\n")[1]
    parts = mem.split()
    return f"Memory:\nTotal: {parts[1]}\nUsed: {parts[2]}\nFree: {parts[3]}"


def apt_update() -> str:
    subprocess.run(["sudo", "apt-get", "update"], check=True)
    return "Update complete!"


def reboot(countdown_sec: int = 3) -> None:
    time.sleep(countdown_sec)
    subprocess.run(["sudo", "reboot"], check=True)


def shutdown(countdown_sec: int = 3) -> None:
    time.sleep(countdown_sec)
    subprocess.run(["sudo", "shutdown", "-h", "now"], check=True)
