import subprocess
from typing import List, Dict, Optional


class DockerManager:
    def __init__(self) -> None:
        self._client = None
        try:
            import docker  # type: ignore

            self._client = docker.from_env()
        except Exception:
            self._client = None

    def _cli(self, args: List[str]) -> str:
        result = subprocess.check_output(["docker", *args], stderr=subprocess.STDOUT)
        return result.decode().strip()

    def list_containers(self, all_containers: bool = True) -> List[Dict[str, str]]:
        containers: List[Dict[str, str]] = []
        if self._client is not None:
            try:
                for c in self._client.containers.list(all=all_containers):  # type: ignore[attr-defined]
                    containers.append({
                        "id": c.short_id,
                        "name": c.name,
                        "status": getattr(c, "status", "unknown"),
                        "image": getattr(c.image, "tags", ["<none>"])[0] if getattr(c, "image", None) else "<none>",
                    })
                return containers
            except Exception:
                pass
        # CLI fallback
        fmt = "{{.ID}}\t{{.Names}}\t{{.Status}}\t{{.Image}}"
        output = self._cli(["ps", "-a" if all_containers else "", "--format", fmt])
        for line in [ln for ln in output.split("\n") if ln.strip()]:
            parts = line.split("\t")
            if len(parts) >= 4:
                containers.append({
                    "id": parts[0],
                    "name": parts[1],
                    "status": parts[2],
                    "image": parts[3],
                })
        return containers

    def start(self, ident: str) -> str:
        if self._client is not None:
            try:
                c = self._client.containers.get(ident)  # type: ignore[attr-defined]
                c.start()
                return f"Started {c.name}"
            except Exception:
                pass
        self._cli(["start", ident])
        return f"Started {ident}"

    def stop(self, ident: str) -> str:
        if self._client is not None:
            try:
                c = self._client.containers.get(ident)  # type: ignore[attr-defined]
                c.stop()
                return f"Stopped {c.name}"
            except Exception:
                pass
        self._cli(["stop", ident])
        return f"Stopped {ident}"

    def restart(self, ident: str) -> str:
        if self._client is not None:
            try:
                c = self._client.containers.get(ident)  # type: ignore[attr-defined]
                c.restart()
                return f"Restarted {c.name}"
            except Exception:
                pass
        self._cli(["restart", ident])
        return f"Restarted {ident}"
