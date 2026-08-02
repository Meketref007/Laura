"""Laura Painel de Controle - app desktop para gerenciar os servicos da Laura.

Zero dependencias extras (apenas tkinter, que vem com o Python).
"""

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
import urllib.request
import webbrowser
from pathlib import Path
from tkinter import messagebox

from laura_common import (
    DOT,
    EMPTY,
    git_short_sha,
    health_check,
    parse_status,
    read_version,
    resolve_code_dir,
    tail_lines,
    ver_gt,
)

try:
    import ctypes

    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

APP_TITLE = "Laura — Painel de Controle"

SERVICES = ["webhook", "telegram", "daemon", "watchdog"]


class Painel(tk.Tk):
    def __init__(self, code_dir: Path):
        super().__init__()
        self.code_dir = code_dir
        self.log_path = code_dir / "logs" / "laura_daemon.err.log"
        self.queue = queue.Queue()
        self.busy = False

        self.title(APP_TITLE)
        self.minsize(720, 560)
        self.configure(bg="#f4f6f9")

        icon = Path(__file__).with_name("laura_icon.ico")
        if icon.exists():
            try:
                self.iconbitmap(str(icon))
            except Exception:
                pass

        self._build_ui()
        self._load_static()
        self.after(400, self._poll_queue)
        self.after(200, self.refresh_status)
        self.after(300, self.refresh_log)

    # ---------- UI ----------
    def _build_ui(self):
        pad = {"padx": 14, "pady": 6}
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)

        header = tk.Frame(self, bg="#f4f6f9")
        header.grid(row=0, column=0, sticky="ew", **pad)
        tk.Label(header, text="LAURA", font=("Segoe UI", 22, "bold"), fg="#1a5fb4", bg="#f4f6f9").pack(side="left")
        self.lbl_version = tk.Label(header, font=("Segoe UI", 11), fg="#555", bg="#f4f6f9")
        self.lbl_version.pack(side="left", padx=(10, 0))
        self.lbl_commit = tk.Label(header, font=("Consolas", 9), fg="#888", bg="#f4f6f9")
        self.lbl_commit.pack(side="right")
        self.lbl_path = tk.Label(header, font=("Consolas", 8), fg="#888", bg="#f4f6f9")
        self.lbl_path.pack(side="right", padx=(0, 12))

        status = tk.Frame(self, bg="#ffffff", highlightbackground="#dfe3ea", highlightthickness=1)
        status.grid(row=1, column=0, sticky="ew", **pad)
        self.lbl_health = tk.Label(status, text="health: —", font=("Segoe UI", 10), fg="#666", bg="#ffffff")
        self.lbl_health.pack(anchor="w", padx=12, pady=(8, 0))
        row = tk.Frame(status, bg="#ffffff")
        row.pack(anchor="w", padx=12, pady=(4, 8))
        self.dots = {}
        for i, name in enumerate(SERVICES):
            dot = tk.Label(row, text=EMPTY, font=("Segoe UI", 14), fg="#bbb", bg="#ffffff")
            dot.grid(row=0, column=i * 2, padx=(0, 4))
            tk.Label(row, text=name, font=("Segoe UI", 10), fg="#444", bg="#ffffff").grid(row=0, column=i * 2 + 1, padx=(0, 18))
            self.dots[name] = dot

        actions = tk.Frame(self, bg="#f4f6f9")
        actions.grid(row=2, column=0, sticky="ew", **pad)
        self.buttons = {}
        for col, (key, label, cmd) in enumerate([
            ("start", "Iniciar", self.action_start),
            ("stop", "Parar", self.action_stop),
            ("restart", "Reiniciar", self.action_restart),
            ("update", "Atualizar", self.action_update),
            ("backup", "Backup", self.action_backup),
            ("restore", "Restaurar", self.action_restore),
        ]):
            b = tk.Button(actions, text=label, font=("Segoe UI", 10, "bold"), width=13,
                          command=cmd, bg="#ffffff", activebackground="#e8edf5", relief="solid", bd=1)
            b.grid(row=0, column=col, padx=(0, 8))
            self.buttons[key] = b
        links = tk.Frame(actions, bg="#f4f6f9")
        links.grid(row=0, column=6, sticky="e", padx=(10, 0))
        for text, cmd in [("Dashboard", lambda: webbrowser.open("http://127.0.0.1:8766/")),
                          ("Config (.env)", self.open_env),
                          ("Nova versão?", self.check_new_setup_version),
                          ("Logs", self.open_logs),
                          ("Pasta", self.open_folder)]:
            tk.Button(links, text=text, font=("Segoe UI", 9), command=cmd,
                      bg="#f4f6f9", relief="flat", fg="#1a5fb4").pack(side="left", padx=4)

        self.lbl_status = tk.Label(self, text="pronto", font=("Segoe UI", 9), fg="#666", bg="#f4f6f9")
        self.lbl_status.grid(row=4, column=0, sticky="w", **pad)

        log_box = tk.Frame(self, bg="#1e1e1e")
        log_box.grid(row=3, column=0, sticky="nsew", **pad)
        tk.Label(log_box, text="Logs do daemon", font=("Segoe UI", 9, "bold"), fg="#999", bg="#1e1e1e").pack(anchor="w")
        self.txt_log = tk.Text(log_box, bg="#1e1e1e", fg="#d4d4d4", font=("Consolas", 9),
                               wrap="none", state="disabled", bd=0, highlightthickness=0)
        self.txt_log.pack(fill="both", expand=True, pady=(4, 0))

    def _load_static(self):
        version = read_version(self.code_dir)
        commit = git_short_sha(self.code_dir)
        self.lbl_version.config(text=f"v{version}")
        self.lbl_commit.config(text=commit)
        self.lbl_path.config(text=str(self.code_dir))

    # ---------- Estado ----------
    def set_busy(self, busy: bool, msg: str = ""):
        self.busy = busy
        for b in self.buttons.values():
            b.config(state="disabled" if busy else "normal")
        self.lbl_status.config(text=msg if msg else ("ocupado" if busy else "pronto"))

    def run_ps(self, script_name: str, *args) -> subprocess.CompletedProcess:
        script = self.code_dir / "scripts" / script_name
        return subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)] + list(args),
            capture_output=True, text=True, timeout=90, creationflags=subprocess.CREATE_NO_WINDOW,
        )

    def refresh_status(self):
        if self.busy:
            self.after(4000, self.refresh_status)
            return
        try:
            res = self.run_ps("laura-services.ps1", "status")
            running = parse_status(res.stdout)
        except Exception:
            running = {}
        for name in SERVICES:
            on = name in running
            self.dots[name].config(text=DOT if on else EMPTY,
                                   fg="#2e9e44" if on else ("#bbb" if name != "daemon" else "#e2b93d"))
        ok = health_check()
        self.lbl_health.config(text=f"health (webhook :8766): {'200 OK' if ok else 'offline'}",
                               fg="#2e9e44" if ok else "#c33")
        self.after(4000, self.refresh_status)

    def refresh_log(self):
        lines = tail_lines(self.log_path)
        self.txt_log.config(state="normal")
        self.txt_log.delete("1.0", "end")
        self.txt_log.insert("1.0", lines)
        self.txt_log.see("end")
        self.txt_log.config(state="disabled")
        self.after(3000, self.refresh_log)

    # ---------- Acoes ----------
    def action_start(self):
        self._run_simple("start")

    def action_stop(self):
        self._run_simple("stop")

    def action_restart(self):
        self._run_simple("restart")

    def _run_simple(self, action: str):
        def worker():
            try:
                res = self.run_ps("laura-services.ps1", action)
                self.queue.put(("done", action, (res.stdout or res.stderr or "").strip()))
            except Exception as exc:
                self.queue.put(("done", action, f"erro: {exc}"))

        self.set_busy(True, f"executando {action}...")
        threading.Thread(target=worker, daemon=True).start()

    def action_update(self):
        def worker():
            try:
                self.queue.put(("log", "Atualizando..."))
                proc = subprocess.Popen(
                    ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                     str(self.code_dir / "scripts" / "laura-update.ps1")],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                for line in proc.stdout:
                    line = line.rstrip("\r\n")
                    if line:
                        self.queue.put(("log", line))
                proc.wait()
                self.queue.put(("done", "update", "atualizacao concluida" if proc.returncode == 0 else "atualizacao falhou"))
            except Exception as exc:
                self.queue.put(("done", "update", f"erro: {exc}"))

        self.set_busy(True, "atualizando...")
        threading.Thread(target=worker, daemon=True).start()

    def action_backup(self):
        def worker():
            try:
                res = self.run_ps("laura-backup.ps1")
                self.queue.put(("done", "backup", (res.stdout or res.stderr or "").strip()))
            except Exception as exc:
                self.queue.put(("done", "backup", f"erro: {exc}"))

        self.set_busy(True, "fazendo backup...")
        threading.Thread(target=worker, daemon=True).start()

    def action_restore(self):
        def worker():
            try:
                res = self.run_ps("laura-restore.ps1")
                self.queue.put(("done", "restore", (res.stdout or res.stderr or "").strip()))
            except Exception as exc:
                self.queue.put(("done", "restore", f"erro: {exc}"))

        self.set_busy(True, "restaurando backup...")
        threading.Thread(target=worker, daemon=True).start()

    def open_env(self):
        env_file = self.code_dir / ".env"
        if not env_file.exists():
            env_example = self.code_dir / ".env.example"
            messagebox.showerror(
                "Config (.env)",
                f".env nao encontrado em:\n{env_file}\n\n"
                "Rode o instalador para cria-lo a partir do .env.example.",
            )
            return
        os.startfile(str(env_file))  # noqa: S606

    @staticmethod
    def _ver_gt(a: str, b: str) -> bool:
        return ver_gt(a, b)

    def check_new_setup_version(self):
        import json
        try:
            with urllib.request.urlopen("https://api.github.com/repos/Meketref007/Laura/releases/latest", timeout=8) as r:
                data = json.load(r)
            tag = data.get("tag_name", "")
            current = read_version(self.code_dir)
            if tag.startswith("v") and self._ver_gt(tag[1:], current):
                messagebox.showinfo(
                    "Nova versão disponível",
                    f"Laura {tag[1:]} disponível (você tem {current}).\n\n"
                    "Baixe o Setup.exe na página de Releases.",
                )
                webbrowser.open(data.get("html_url", "https://github.com/Meketref007/Laura/releases"))
            else:
                messagebox.showinfo("Laura", f"Você já está na versão mais recente ({current}).")
        except Exception as exc:
            messagebox.showerror("Verificação", f"Não foi possível verificar: {exc}")

    def open_logs(self):
        logs_dir = self.code_dir / "logs"
        os.startfile(str(logs_dir))  # noqa: S606

    def open_folder(self):
        os.startfile(str(self.code_dir))  # noqa: S606

    def _poll_queue(self):
        try:
            while True:
                item = self.queue.get_nowait()
                if item[0] == "done":
                    _, action, out = item
                    self.set_busy(False)
                    if out:
                        messagebox.showinfo(f"Laura — {action}", out)
                elif item[0] == "log":
                    _, text = item
                    self.txt_log.config(state="normal")
                    self.txt_log.insert("end", f"\n> {text}\n")
                    self.txt_log.see("end")
                    self.txt_log.config(state="disabled")
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)


def main():
    code_dir = resolve_code_dir()
    if not code_dir.exists():
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            APP_TITLE,
            f"Laura nao foi encontrada em:\n{code_dir}\n\n"
            "Rode o instalador (Setup.exe) ou powershell -File installer\\install.ps1",
        )
        root.destroy()
        return 1
    app = Painel(code_dir)
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
