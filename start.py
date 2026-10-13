from __future__ import annotations

import os
import queue
import re
import shutil
import subprocess
import sys
import hashlib
import json
import tempfile
import threading
import time
from pathlib import Path
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
REQUIREMENTS = ROOT / "requirements.txt"
MAIN = ROOT / "main.py"
TUNNEL_EXE = ROOT / "runtime_tools" / "cloudflared.exe"
# cloudflared also logs its API endpoint (api.trycloudflare.com) while creating
# the tunnel. That host is not the public app URL; accept only generated hosts.
TUNNEL_URL_RE = re.compile(
    r"https://(?!api\.)[a-zA-Z0-9]+(?:-[a-zA-Z0-9]+)*\.trycloudflare\.com",
    re.IGNORECASE,
)


def install_requirements() -> None:
    """Install/update the packages listed for this project in the active Python."""
    if not REQUIREMENTS.is_file():
        raise FileNotFoundError(f"requirements.txt topilmadi: {REQUIREMENTS}")

    print("Python kutubxonalari tekshirilmoqda...", flush=True)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "-r",
            str(REQUIREMENTS),
        ],
        cwd=ROOT,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "Kutubxonalarni o‘rnatib bo‘lmadi. Internet va PyCharm interpreterini tekshiring."
        )


def resolve_cloudflared() -> Path:
    """Find cloudflared locally, or download and verify the official Windows release."""
    if TUNNEL_EXE.is_file():
        return TUNNEL_EXE
    on_path = shutil.which("cloudflared") or shutil.which("cloudflared.exe")
    if on_path:
        return Path(on_path)

    print("cloudflared topilmadi; rasmiy Windows versiyasi yuklanmoqda...", flush=True)
    api_url = "https://api.github.com/repos/cloudflare/cloudflared/releases/latest"
    request = Request(api_url, headers={"Accept": "application/vnd.github+json",
                                        "User-Agent": "telegram-business-archive-launcher"})
    with urlopen(request, timeout=30) as response:
        release = json.load(response)

    asset_name = "cloudflared-windows-amd64.exe"
    asset = next((item for item in release.get("assets", []) if item.get("name") == asset_name), None)
    if not asset:
        raise RuntimeError(f"Rasmiy release ichida {asset_name} topilmadi")
    download_url = asset.get("browser_download_url", "")
    if not download_url.startswith("https://github.com/cloudflare/cloudflared/releases/download/"):
        raise RuntimeError("cloudflared yuklash manbasi kutilgan rasmiy GitHub manzili emas")

    checksum_pattern = rf"(?im)^\s*{re.escape(asset_name)}:\s*([0-9a-f]{{64}})\s*$"
    checksum_match = re.search(checksum_pattern, release.get("body") or "")
    if not checksum_match:
        raise RuntimeError("Rasmiy release tavsifida cloudflared SHA-256 nazorat summasi topilmadi")
    expected_sha256 = checksum_match.group(1).lower()

    TUNNEL_EXE.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=TUNNEL_EXE.parent, prefix="cloudflared-",
                                         suffix=".download", delete=False) as temporary:
            temp_path = Path(temporary.name)
            download_request = Request(download_url, headers={"User-Agent": "telegram-business-archive-launcher"})
            with urlopen(download_request, timeout=90) as response:
                for chunk in iter(lambda: response.read(1024 * 1024), b""):
                    temporary.write(chunk)

        hasher = hashlib.sha256()
        with temp_path.open("rb") as downloaded:
            for chunk in iter(lambda: downloaded.read(1024 * 1024), b""):
                hasher.update(chunk)
        digest = hasher.hexdigest()
        if digest != expected_sha256:
            raise RuntimeError("cloudflared SHA-256 tekshiruvi muvaffaqiyatsiz tugadi")
        os.replace(temp_path, TUNNEL_EXE)
        temp_path = None
    finally:
        if temp_path:
            temp_path.unlink(missing_ok=True)

    print(f"cloudflared yuklandi va SHA-256 tekshirildi ({release.get('tag_name', 'latest')}).", flush=True)
    return TUNNEL_EXE


def _read_lines(pipe, output: queue.Queue[str]) -> None:
    try:
        for line in iter(pipe.readline, ""):
            output.put(line.rstrip())
    finally:
        pipe.close()


def start_quick_tunnel(cloudflared: Path, host: str, port: int) -> tuple[subprocess.Popen, str]:
    """Start a Cloudflare Quick Tunnel and return its process and public HTTPS URL."""
    command = [
        str(cloudflared),
        "tunnel",
        "--no-autoupdate",
        "--url",
        f"http://{host}:{port}",
    ]
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    lines: queue.Queue[str] = queue.Queue()
    reader = threading.Thread(target=_read_lines, args=(process.stdout, lines), daemon=True)
    reader.start()

    print("HTTPS tunnel ochilmoqda. Biroz kuting...", flush=True)
    deadline = time.monotonic() + 60
    recent_lines: list[str] = []
    while time.monotonic() < deadline:
        if process.poll() is not None:
            break
        try:
            line = lines.get(timeout=0.25)
        except queue.Empty:
            continue
        if line:
            recent_lines.append(line)
            recent_lines = recent_lines[-12:]
            match = TUNNEL_URL_RE.search(line)
            if match:
                return process, match.group(0)

    stop_process(process)
    details = "\n".join(recent_lines)
    raise RuntimeError(
        "Cloudflare tunnel manzili olinmadi. Internetni tekshiring."
        + (f"\ncloudflared javobi:\n{details}" if details else "")
    )


def stop_process(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def run_main(public_url: str) -> int:
    env = os.environ.copy()
    env["MINI_APP_URL"] = public_url
    env["PYTHONUNBUFFERED"] = "1"
    print(f"Mini App HTTPS manzili: {public_url}", flush=True)
    print("Bot va Mini App ishga tushirilmoqda...", flush=True)
    return subprocess.call([sys.executable, "-u", str(MAIN)], cwd=ROOT, env=env)


def main() -> int:
    tunnel_process: subprocess.Popen | None = None
    try:
        install_requirements()

        # Load settings after dependencies are ready. A configured stable HTTPS URL
        # is reused; otherwise a temporary Cloudflare Quick Tunnel is created.
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
        configured_url = os.getenv("MINI_APP_URL", "").strip().rstrip("/")
        if configured_url:
            if not configured_url.startswith("https://"):
                raise RuntimeError(".env dagi MINI_APP_URL HTTPS bilan boshlanishi kerak.")
            public_url = configured_url
            print(f"Sozlangan Mini App HTTPS manzili ishlatilmoqda: {public_url}", flush=True)
        else:
            port = int(os.getenv("MINI_APP_PORT", "8080"))
            if not 1 <= port <= 65535:
                raise RuntimeError("MINI_APP_PORT 1 dan 65535 gacha bo‘lishi kerak.")
            host = os.getenv("MINI_APP_HOST", "127.0.0.1").strip() or "127.0.0.1"
            cloudflared = resolve_cloudflared()
            tunnel_process, public_url = start_quick_tunnel(cloudflared, host, port)

        return run_main(public_url)
    except KeyboardInterrupt:
        print("To‘xtatish so‘rovi qabul qilindi.", flush=True)
        return 130
    except Exception as exc:
        print(f"Ishga tushirishda xato: {exc}", flush=True)
        return 1
    finally:
        stop_process(tunnel_process)
        if tunnel_process:
            print("HTTPS tunnel yopildi.", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
