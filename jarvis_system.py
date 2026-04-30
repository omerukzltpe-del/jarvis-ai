"""
J.A.R.V.I.S. — Sistem Yönetimi
Ubuntu komutlarını onay alarak çalıştırır, dosya yönetimi yapar.
"""

import os, subprocess, shutil, stat, datetime
from pathlib import Path
import re

# Onaysız çalışabilecek GÜVENLİ komutlar
SAFE_COMMANDS = {
    "ls", "pwd", "echo", "cat", "head", "tail", "grep", "find",
    "df", "du", "free", "top", "ps", "uname", "whoami", "date",
    "uptime", "lsblk", "lscpu", "lsusb", "lspci", "ip", "ifconfig",
    "ping", "curl", "wget", "systemctl status", "journalctl",
    "python3 --version", "node --version", "npm --version",
    "pip3 list", "dpkg -l", "apt list",
}

# Onay GEREKTİREN komutlar (tehlikeli)
APPROVAL_REQUIRED = {
    "rm", "rmdir", "dd", "mkfs", "fdisk", "parted",
    "apt install", "apt remove", "apt purge", "apt upgrade",
    "pip install", "pip uninstall", "npm install", "npm uninstall",
    "systemctl start", "systemctl stop", "systemctl restart",
    "systemctl enable", "systemctl disable",
    "chmod", "chown", "sudo", "su",
    "mv", "cp", "mkdir",
    "useradd", "userdel", "usermod", "passwd",
    "crontab", "at",
}

# Kesinlikle yasak
FORBIDDEN_PATTERNS = [
    r"rm\s+-rf\s+/",
    r"dd\s+if=.*of=/dev/sd",
    r"mkfs.*\/dev\/sd[a-z]$",
    r">\s*/dev/sd",
    r":(){ :|:& };:",   # fork bomb
    r"chmod\s+777\s+/",
]


def is_safe(cmd: str) -> bool:
    """Komutun onaysız çalışıp çalışamayacağını kontrol et."""
    cmd_lower = cmd.strip().lower()
    for safe in SAFE_COMMANDS:
        if cmd_lower.startswith(safe):
            return True
    return False


def is_forbidden(cmd: str) -> bool:
    """Kesinlikle yasak komutları tespit et."""
    for pattern in FORBIDDEN_PATTERNS:
        if re.search(pattern, cmd, re.IGNORECASE):
            return True
    return False


def needs_approval(cmd: str) -> bool:
    """Onay gerektiren komutları tespit et."""
    cmd_lower = cmd.strip().lower()
    for danger in APPROVAL_REQUIRED:
        if cmd_lower.startswith(danger) or f" {danger} " in cmd_lower:
            return True
    return False


def run_command(cmd: str, timeout: int = 30) -> dict:
    """Komutu çalıştır ve sonucu döndür."""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True,
            text=True, timeout=timeout,
            env={**os.environ, "TERM": "xterm"}
        )
        return {
            "ok": result.returncode == 0,
            "stdout": result.stdout.strip()[:3000],
            "stderr": result.stderr.strip()[:1000],
            "returncode": result.returncode
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "stdout": "", "stderr": "Komut zaman aşımına uğradı.", "returncode": -1}
    except Exception as e:
        return {"ok": False, "stdout": "", "stderr": str(e), "returncode": -1}


def get_system_info() -> dict:
    """Sistem bilgilerini topla."""
    info = {}
    cmds = {
        "os":      "lsb_release -d 2>/dev/null | cut -f2 || uname -a",
        "uptime":  "uptime -p",
        "cpu":     "grep 'model name' /proc/cpuinfo | head -1 | cut -d: -f2",
        "memory":  "free -h | grep Mem",
        "disk":    "df -h / | tail -1",
        "ip":      "hostname -I | awk '{print $1}'",
        "services":"systemctl list-units --state=running --no-pager --no-legend | wc -l",
    }
    for key, cmd in cmds.items():
        r = run_command(cmd, timeout=5)
        info[key] = r["stdout"].strip() if r["ok"] else "—"
    return info


def list_directory(path: str = "~") -> dict:
    """Dizini listele."""
    expanded = os.path.expanduser(path)
    try:
        entries = []
        for item in sorted(Path(expanded).iterdir()):
            try:
                stat_info = item.stat()
                entries.append({
                    "name": item.name,
                    "type": "dir" if item.is_dir() else "file",
                    "size": stat_info.st_size,
                    "modified": datetime.datetime.fromtimestamp(
                        stat_info.st_mtime).strftime("%d.%m.%Y %H:%M"),
                    "permissions": oct(stat.S_IMODE(stat_info.st_mode))
                })
            except PermissionError:
                continue
        return {"ok": True, "path": expanded, "entries": entries[:50]}
    except Exception as e:
        return {"ok": False, "error": str(e), "entries": []}


def read_file(path: str, max_bytes: int = 8000) -> dict:
    """Dosya içeriğini oku."""
    try:
        p = Path(os.path.expanduser(path))
        if not p.exists():
            return {"ok": False, "error": "Dosya bulunamadı."}
        if p.stat().st_size > 10_000_000:
            return {"ok": False, "error": "Dosya çok büyük (>10MB)."}
        content = p.read_text(encoding="utf-8", errors="ignore")[:max_bytes]
        return {"ok": True, "path": str(p), "content": content,
                "lines": content.count("\n"), "size": p.stat().st_size}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def write_file(path: str, content: str, backup: bool = True) -> dict:
    """Dosyaya yaz (opsiyonel yedek alır)."""
    try:
        p = Path(os.path.expanduser(path))
        if backup and p.exists():
            bak = str(p) + f".bak.{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"
            shutil.copy2(str(p), bak)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return {"ok": True, "path": str(p),
                "backup": bak if backup and p.exists() else None}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def install_package(package: str, manager: str = "apt") -> dict:
    """Paket kurulum komutu oluştur (çalıştırmaz, onay gerektirir)."""
    if manager == "apt":
        cmd = f"sudo apt install -y {package}"
    elif manager == "pip":
        cmd = f"pip3 install {package} --break-system-packages"
    elif manager == "npm":
        cmd = f"npm install -g {package}"
    else:
        return {"ok": False, "error": "Bilinmeyen paket yöneticisi."}
    return {"ok": True, "cmd": cmd, "requires_approval": True}


def get_service_status(service: str) -> dict:
    """Systemd servis durumunu getir."""
    r = run_command(f"systemctl status {service} --no-pager -l", timeout=5)
    return {"ok": r["ok"], "output": r["stdout"] or r["stderr"]}


def parse_command_from_ai(text: str) -> list[dict]:
    """
    AI yanıtından komut bloklarını çıkar.
    Format: ```bash\nkomut\n``` veya [CMD:komut]
    """
    commands = []
    # Markdown kod blokları
    for m in re.finditer(r'```(?:bash|shell|sh)?\n(.*?)```', text, re.DOTALL):
        cmd = m.group(1).strip()
        if cmd:
            commands.append({
                "cmd": cmd,
                "safe": is_safe(cmd),
                "forbidden": is_forbidden(cmd),
                "needs_approval": needs_approval(cmd)
            })
    # [CMD:...] formatı
    for m in re.finditer(r'\[CMD:(.*?)\]', text):
        cmd = m.group(1).strip()
        if cmd:
            commands.append({
                "cmd": cmd,
                "safe": is_safe(cmd),
                "forbidden": is_forbidden(cmd),
                "needs_approval": needs_approval(cmd)
            })
    return commands
