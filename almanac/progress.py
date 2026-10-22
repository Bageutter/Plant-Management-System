"""Small, owner-scoped progress snapshots shared across Flask workers.

Only real execution phases are published. No questions, answers or credentials
are stored here; the durable workflow/loop records remain authoritative.
"""
import json
import os
import re
import tempfile
import time
from pathlib import Path


class ProgressStore:
    lifetime = 1200

    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)

    def path(self, key):
        if not re.fullmatch(r"[a-f0-9]{32}", key or ""):
            raise ValueError("Invalid progress identifier")
        return self.directory / (key + ".json")

    def start(self, key, owner, mode):
        path = self.path(key)
        now = time.time()
        for old in self.directory.glob("*.json"):
            try:
                if old.stat().st_mtime < now - self.lifetime:
                    old.unlink(missing_ok=True)
            except FileNotFoundError:
                pass
        if len(list(self.directory.glob("*.json"))) >= 512:
            raise ValueError("Progress capacity reached; try again shortly")
        if path.exists():
            raise ValueError("Progress identifier already used")
        value = {"owner": owner, "mode": mode, "phase": "queued", "phases": [], "created": now}
        self.write(key, value)

    def read(self, key, owner):
        try:
            value = json.loads(self.path(key).read_text())
        except (FileNotFoundError, ValueError):
            return None
        if value["owner"] != owner or time.time() - value["created"] > self.lifetime:
            return None
        return value

    def write(self, key, value):
        with tempfile.NamedTemporaryFile(mode="w", dir=self.directory, delete=False) as output:
            json.dump(value, output)
            name = output.name
        os.replace(name, self.path(key))

    def update(self, key, owner, phase=None, **fields):
        value = self.read(key, owner)
        if value is None:
            return
        if phase:
            if phase == "act" and value["phase"] == "adapt":
                value["phases"] = ["plan"]
            value["phase"] = phase
            value["phases"].append(phase)
        value.update(fields)
        self.write(key, value)
