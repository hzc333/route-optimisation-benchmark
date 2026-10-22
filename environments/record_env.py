"""Record the benchmark machine/environment to results/metadata.json.

Run once per environment change; every results CSV should be traceable to a
metadata snapshot (plan §3: same machine, same power mode, versions recorded).
"""

from __future__ import annotations

import datetime as dt
import json
import os
import platform
import subprocess
import sys
from importlib import metadata
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "metadata.json"

PACKAGES = ["ortools", "pyvrp", "pyvroom", "numpy", "pandas", "pydantic", "psutil", "vrplib"]
TOOLS = ROOT.parent / "tools"  # portable JDK / Maven (see environments/java_env.*)


def _run(cmd: list[str]) -> str | None:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def cpu_name() -> str:
    if sys.platform == "win32":
        name = _run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-CimInstance Win32_Processor | Select-Object -First 1).Name"]
        )
        if name:
            return name
    return platform.processor() or "unknown"


def power_scheme() -> str | None:
    if sys.platform == "win32":
        return _run(["powercfg", "/getactivescheme"])
    gov = Path("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor")
    return gov.read_text().strip() if gov.exists() else None


# Windows 11 "power mode" slider is an overlay on top of the power scheme and
# is not reported by powercfg.
_OVERLAYS = {
    "961cc777-2547-4f9d-8174-7d86181b8a7a": "best_power_efficiency",
    "00000000-0000-0000-0000-000000000000": "balanced",
    "ded574b5-45a0-4f42-8737-46345c09c238": "best_performance",
}


def power_mode_overlay() -> dict | None:
    if sys.platform != "win32":
        return None
    import winreg

    key_path = r"SYSTEM\CurrentControlSet\Control\Power\User\PowerSchemes"
    out = {}
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
            for src, name in (("ac", "ActiveOverlayAcPowerScheme"),
                              ("dc", "ActiveOverlayDcPowerScheme")):
                guid = winreg.QueryValueEx(key, name)[0].lower()
                out[src] = _OVERLAYS.get(guid, guid)
    except OSError:
        return None
    return out


def on_ac_power() -> bool | None:
    battery = psutil.sensors_battery()
    return None if battery is None else battery.power_plugged


def java_toolchain() -> dict:
    """Versions of the portable JDK and Maven, if installed."""
    jdk = next(TOOLS.glob("jdk-21*"), None)
    mvn = next(TOOLS.glob("apache-maven-*"), None)
    out = {"jdk": None, "maven": mvn.name.removeprefix("apache-maven-") if mvn else None}
    if jdk:
        java = jdk / "bin" / ("java.exe" if sys.platform == "win32" else "java")
        try:
            res = subprocess.run([str(java), "-version"], capture_output=True, text=True, timeout=30)
            out["jdk"] = res.stderr.splitlines()[1].strip() if res.stderr else jdk.name
        except (OSError, subprocess.SubprocessError, IndexError):
            out["jdk"] = jdk.name
    return out


def collect() -> dict:
    freq = psutil.cpu_freq()
    return {
        "recorded_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "os": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
        },
        "cpu": {
            "name": cpu_name(),
            "physical_cores": psutil.cpu_count(logical=False),
            "logical_cores": psutil.cpu_count(logical=True),
            "max_freq_mhz": freq.max if freq else None,
        },
        "ram_gb": round(psutil.virtual_memory().total / 2**30, 1),
        "power_scheme": power_scheme(),
        "power_mode_overlay": power_mode_overlay(),
        "on_ac_power": on_ac_power(),
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "executable": sys.executable,
        },
        "packages": {p: metadata.version(p) for p in PACKAGES},
        "java": java_toolchain(),
        "env": {k: os.environ.get(k) for k in ("OMP_NUM_THREADS",)},
    }


if __name__ == "__main__":
    OUT.parent.mkdir(parents=True, exist_ok=True)
    data = collect()
    OUT.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(json.dumps(data, indent=2))
