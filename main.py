#!/usr/bin/env python3
"""
GUI for Jimeng API - Image Generation Tool
"""

import os
import sys
import json
import threading
import requests
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse, unquote
import re
import hashlib

# Constants
API_URL = "http://localhost:5100/v1/images/generations"
MODEL = "jimeng-4.0"
RESOLUTION = "2k"
RATIOS = ["1:1", "4:3", "3:4", "16:9", "9:16", "3:2", "2:3", "21:9"]

# Get the directory where this script is located
SCRIPT_DIR = Path(__file__).parent.resolve()
PROMPT_FOLDER = SCRIPT_DIR / "prompt"
SESSION_FOLDER = SCRIPT_DIR / "session"
OUTPUT_FOLDER = SCRIPT_DIR / "outputs"


def sanitize_folder_name(name: str, max_length: int = 50) -> str:
    """Sanitize a string to be used as a folder name."""
    # Remove or replace invalid characters
    sanitized = re.sub(r'[<>:"/\\|?*]', '_', name)
    # Remove leading/trailing spaces and dots
    sanitized = sanitized.strip(' .')
    # Truncate if too long
    if len(sanitized) > max_length:
        # Keep first part and add hash for uniqueness
        hash_suffix = hashlib.md5(name.encode()).hexdigest()[:8]
        sanitized = sanitized[:max_length - 9] + '_' + hash_suffix
    return sanitized if sanitized else "unnamed"


class WorkerThread:
    """Represents a worker thread for processing prompts."""

    def __init__(self, prompt_file: Path, session_file: Path, ratio_var: tk.StringVar,
                 log_widget: scrolledtext.ScrolledText, status_label: ttk.Label,
                 run_button: ttk.Button):
        self.prompt_file = prompt_file
        self.session_file = session_file
        self.ratio_var = ratio_var
        self.log_widget = log_widget
        self.status_label = status_label
        self.run_button = run_button
        self.sessions: list[str] = []
        self.current_session_index = 0
        self.running = False
        self.thread: threading.Thread | None = None

    def log(self, message: str):
        """Thread-safe logging to the text widget."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        def append():
            self.log_widget.insert(tk.END, f"[{timestamp}] {message}\n")
            self.log_widget.see(tk.END)
        self.log_widget.after(0, append)

    def update_status(self, status: str):
        """Thread-safe status update."""
        def update():
            self.status_label.config(text=status)
        self.status_label.after(0, update)

    def load_sessions(self) -> bool:
        """Load session IDs from the session file."""
        try:
            with open(self.session_file, 'r', encoding='utf-8') as f:
                self.sessions = [line.strip() for line in f if line.strip()]
            if not self.sessions:
                self.log(f"No sessions found in {self.session_file.name}")
                return False
            self.log(f"Loaded {len(self.sessions)} sessions")
            return True
        except Exception as e:
            self.log(f"Error loading sessions: {e}")
            return False

    def get_next_session(self) -> str | None:
        """Get the next available session."""
        if self.current_session_index >= len(self.sessions):
            return None
        session = self.sessions[self.current_session_index]
        self.current_session_index += 1
        return session

    def download_image(self, url: str, save_path: Path) -> bool:
        """Download an image from URL."""
        try:
            response = requests.get(url, timeout=60)
            response.raise_for_status()
            save_path.parent.mkdir(parents=True, exist_ok=True)
            with open(save_path, 'wb') as f:
                f.write(response.content)
            return True
        except Exception as e:
            self.log(f"Error downloading image: {e}")
            return False

    def call_api(self, prompt: str, session: str) -> dict | None:
        """Call the image generation API."""
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer sg-{session}"
        }
        payload = {
            "model": MODEL,
            "prompt": prompt,
            "ratio": self.ratio_var.get(),
            "resolution": RESOLUTION
        }

        try:
            response = requests.post(API_URL, headers=headers, json=payload, timeout=120)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            self.log(f"API HTTP Error: {e.response.status_code} - {e.response.text[:200]}")
            return None
        except Exception as e:
            self.log(f"API Error: {e}")
            return None

    def process_prompt(self, prompt: str, prompt_index: int) -> bool:
        """Process a single prompt, trying different sessions on failure."""
        prompt_folder_name = sanitize_folder_name(prompt)
        output_dir = OUTPUT_FOLDER / self.prompt_file.stem / prompt_folder_name

        while self.running:
            session = self.sessions[self.current_session_index % len(self.sessions)]
            self.log(f"Trying session {self.current_session_index + 1}/{len(self.sessions)}")

            result = self.call_api(prompt, session)

            if result and "data" in result:
                # Success - download images
                self.log(f"Got {len(result['data'])} images")
                for i, item in enumerate(result['data']):
                    url = item.get('url')
                    if url:
                        # Extract file extension from URL
                        parsed = urlparse(url)
                        path_part = parsed.path
                        ext = '.jpeg'
                        if 'format=' in url:
                            ext = url.split('format=')[-1].split('&')[0]
                            if not ext.startswith('.'):
                                ext = '.' + ext

                        filename = f"image_{i+1}{ext}"
                        save_path = output_dir / filename

                        if self.download_image(url, save_path):
                            self.log(f"Saved: {save_path.name}")
                        else:
                            self.log(f"Failed to save: {filename}")
                return True
            else:
                # Failed - try next session
                self.current_session_index += 1
                if self.current_session_index >= len(self.sessions):
                    self.log("All sessions exhausted!")
                    self.current_session_index = 0  # Reset for next prompt
                    return False

        return False

    def run(self):
        """Main worker function."""
        if not self.load_sessions():
            self.update_status("Error: No sessions")
            return

        try:
            with open(self.prompt_file, 'r', encoding='utf-8') as f:
                prompts = [line.strip() for line in f if line.strip()]
        except Exception as e:
            self.log(f"Error reading prompts: {e}")
            self.update_status("Error")
            return

        if not prompts:
            self.log("No prompts found!")
            self.update_status("Error: No prompts")
            return

        self.log(f"Processing {len(prompts)} prompts...")
        self.update_status("Running...")

        for i, prompt in enumerate(prompts):
            if not self.running:
                self.log("Stopped by user")
                break

            self.log(f"\n--- Prompt {i+1}/{len(prompts)} ---")
            self.log(f"Prompt: {prompt[:80]}...")
            self.update_status(f"Processing {i+1}/{len(prompts)}")

            success = self.process_prompt(prompt, i)
            if success:
                self.log("Completed successfully!")
            else:
                self.log("Failed to process this prompt")

        self.running = False
        self.update_status("Completed" if self.running else "Stopped")
        self.log("\n=== Finished ===")

        # Re-enable run button
        def enable_button():
            self.run_button.config(state=tk.NORMAL, text="Run")
        self.run_button.after(0, enable_button)

    def start(self):
        """Start the worker thread."""
        if self.running:
            return
        self.running = True
        self.current_session_index = 0
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def stop(self):
        """Stop the worker thread."""
        self.running = False


class JimengGUI:
    """Main GUI Application."""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Dreamina Image Generator")
        self.root.geometry("1200x800")
        self.workers: list[WorkerThread] = []

        self.setup_folders()
        self.setup_ui()

    def setup_folders(self):
        """Create necessary folders if they don't exist."""
        PROMPT_FOLDER.mkdir(exist_ok=True)
        SESSION_FOLDER.mkdir(exist_ok=True)
        OUTPUT_FOLDER.mkdir(exist_ok=True)

    def validate_files(self) -> tuple[list[Path], list[Path]] | None:
        """Validate that prompt and session files match."""
        prompt_files = sorted([f for f in PROMPT_FOLDER.glob("*.txt")])
        session_files = sorted([f for f in SESSION_FOLDER.glob("*.txt")])

        if not prompt_files:
            messagebox.showerror("Error", f"No prompt files found in:\n{PROMPT_FOLDER}")
            return None

        if not session_files:
            messagebox.showerror("Error", f"No session files found in:\n{SESSION_FOLDER}")
            return None

        if len(prompt_files) != len(session_files):
            messagebox.showerror(
                "Error",
                f"Mismatch: {len(prompt_files)} prompt files vs {len(session_files)} session files.\n\n"
                f"Each prompt file needs exactly one session file.\n\n"
                f"Prompt folder: {PROMPT_FOLDER}\n"
                f"Session folder: {SESSION_FOLDER}"
            )
            return None

        return prompt_files, session_files

    def setup_ui(self):
        """Setup the main UI."""
        # Main frame with padding
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Header
        header_frame = ttk.Frame(main_frame)
        header_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(header_frame, text="Dreamina Image Generator",
                  font=('Helvetica', 16, 'bold')).pack(side=tk.LEFT)

        # Info labels
        info_frame = ttk.Frame(main_frame)
        info_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(info_frame, text=f"Prompt folder: {PROMPT_FOLDER}").pack(anchor=tk.W)
        ttk.Label(info_frame, text=f"Session folder: {SESSION_FOLDER}").pack(anchor=tk.W)
        ttk.Label(info_frame, text=f"Output folder: {OUTPUT_FOLDER}").pack(anchor=tk.W)

        # Run All button
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=(0, 10))

        self.run_all_btn = ttk.Button(btn_frame, text="Run All", command=self.run_all)
        self.run_all_btn.pack(side=tk.LEFT, padx=(0, 10))

        self.stop_all_btn = ttk.Button(btn_frame, text="Stop All", command=self.stop_all)
        self.stop_all_btn.pack(side=tk.LEFT)

        ttk.Button(btn_frame, text="Refresh", command=self.refresh).pack(side=tk.RIGHT)

        # Scrollable frame for workers
        canvas_frame = ttk.Frame(main_frame)
        canvas_frame.pack(fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(canvas_frame)
        scrollbar = ttk.Scrollbar(canvas_frame, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = ttk.Frame(self.canvas)

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )

        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Bind mouse wheel
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind_all("<Button-4>", self._on_mousewheel)
        self.canvas.bind_all("<Button-5>", self._on_mousewheel)

        # Load workers
        self.load_workers()

    def _on_mousewheel(self, event):
        """Handle mouse wheel scrolling."""
        if event.num == 4:
            self.canvas.yview_scroll(-1, "units")
        elif event.num == 5:
            self.canvas.yview_scroll(1, "units")
        else:
            self.canvas.yview_scroll(int(-1*(event.delta/120)), "units")

    def load_workers(self):
        """Load and display worker rows."""
        # Clear existing workers
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()
        self.workers.clear()

        # Validate files
        result = self.validate_files()
        if not result:
            return

        prompt_files, session_files = result

        # Create worker rows
        for i, (prompt_file, session_file) in enumerate(zip(prompt_files, session_files)):
            self.create_worker_row(i, prompt_file, session_file)

    def create_worker_row(self, index: int, prompt_file: Path, session_file: Path):
        """Create a single worker row."""
        # Main row frame
        row_frame = ttk.LabelFrame(self.scrollable_frame, text=f"Worker {index + 1}", padding="10")
        row_frame.pack(fill=tk.X, pady=5, padx=5)

        # Top row - file info and controls
        top_frame = ttk.Frame(row_frame)
        top_frame.pack(fill=tk.X)

        # File names
        file_frame = ttk.Frame(top_frame)
        file_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)

        ttk.Label(file_frame, text=f"Prompt: {prompt_file.name}",
                  font=('Helvetica', 10, 'bold')).pack(anchor=tk.W)
        ttk.Label(file_frame, text=f"Session: {session_file.name}").pack(anchor=tk.W)

        # Controls frame
        ctrl_frame = ttk.Frame(top_frame)
        ctrl_frame.pack(side=tk.RIGHT)

        # Ratio dropdown
        ttk.Label(ctrl_frame, text="Ratio:").pack(side=tk.LEFT, padx=(0, 5))
        ratio_var = tk.StringVar(value=RATIOS[0])
        ratio_combo = ttk.Combobox(ctrl_frame, textvariable=ratio_var, values=RATIOS,
                                    width=8, state="readonly")
        ratio_combo.pack(side=tk.LEFT, padx=(0, 10))

        # Status label
        status_label = ttk.Label(ctrl_frame, text="Ready", width=15)
        status_label.pack(side=tk.LEFT, padx=(0, 10))

        # Run button
        run_btn = ttk.Button(ctrl_frame, text="Run", width=8)
        run_btn.pack(side=tk.LEFT)

        # Log area
        log_frame = ttk.Frame(row_frame)
        log_frame.pack(fill=tk.X, pady=(10, 0))

        log_widget = scrolledtext.ScrolledText(log_frame, height=6, width=80,
                                                font=('Courier', 9))
        log_widget.pack(fill=tk.X)

        # Create worker
        worker = WorkerThread(prompt_file, session_file, ratio_var,
                             log_widget, status_label, run_btn)
        self.workers.append(worker)

        # Configure run button
        def toggle_run(w=worker, btn=run_btn):
            if w.running:
                w.stop()
                btn.config(text="Run")
            else:
                btn.config(text="Stop", state=tk.NORMAL)
                w.start()

        run_btn.config(command=toggle_run)

    def run_all(self):
        """Start all workers."""
        for worker in self.workers:
            if not worker.running:
                worker.run_button.config(text="Stop")
                worker.start()

    def stop_all(self):
        """Stop all workers."""
        for worker in self.workers:
            if worker.running:
                worker.stop()
                worker.run_button.config(text="Run")

    def refresh(self):
        """Refresh the worker list."""
        self.stop_all()
        self.load_workers()

    def run(self):
        """Start the application."""
        self.root.mainloop()


def main():
    app = JimengGUI()
    app.run()


if __name__ == "__main__":
    main()
