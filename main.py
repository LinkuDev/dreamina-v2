#!/usr/bin/env python3
"""
GUI for Jimeng API - Image Generation Tool
"""

import threading
import requests
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from pathlib import Path
from datetime import datetime
import re
import hashlib

# Constants
DEFAULT_API_HOST = "localhost:5100"
API_PATH = "/v1/images/generations"
RESOLUTION = "2k"
MODELS = ["jimeng-3.0", "jimeng-4.0", "nanobanana", "nanobananapro"]
RATIOS = ["1:1", "4:3", "3:4", "16:9", "9:16", "3:2", "2:3", "21:9"]

# Error messages mapping for friendly display
ERROR_MESSAGES = {
    -2009: "Hết credit! Session này đã hết điểm, chuyển sang session khác...",
    -2001: "Session không hợp lệ hoặc đã hết hạn",
    -2002: "Lỗi xác thực, session có thể đã bị khóa",
    -2003: "Tài khoản bị giới hạn",
    -1001: "Lỗi hệ thống, thử lại với session khác",
}

# Error codes that should trigger session switch
SESSION_ERROR_CODES = [-2009, -2001, -2002, -2003, -1001]

# Get the directory where the exe/script is located
# When running as PyInstaller exe, use exe's directory
# When running as script, use script's directory
import sys

if getattr(sys, 'frozen', False):
    # Running as compiled exe
    SCRIPT_DIR = Path(sys.executable).parent.resolve()
else:
    # Running as script
    SCRIPT_DIR = Path(__file__).parent.resolve()

PROMPT_FOLDER = SCRIPT_DIR / "prompt"
SESSION_FOLDER = SCRIPT_DIR / "session"
OUTPUT_FOLDER = SCRIPT_DIR / "outputs"


def sanitize_filename(name: str, max_length: int = 80) -> str:
    """Sanitize a string to be used as a filename (replace spaces with dashes)."""
    # Replace spaces with dashes
    sanitized = name.replace(' ', '-')
    # Remove or replace invalid characters
    sanitized = re.sub(r'[<>:"/\\|?*]', '', sanitized)
    # Remove multiple dashes
    sanitized = re.sub(r'-+', '-', sanitized)
    # Remove leading/trailing dashes and dots
    sanitized = sanitized.strip('-.')
    # Truncate if too long
    if len(sanitized) > max_length:
        hash_suffix = hashlib.md5(name.encode()).hexdigest()[:8]
        sanitized = sanitized[:max_length - 9] + '_' + hash_suffix
    return sanitized.lower() if sanitized else "unnamed"


class WorkerThread:
    """Represents a worker thread for processing prompts."""

    def __init__(self, prompt_file: Path, session_file: Path, ratio_var: tk.StringVar,
                 model_var: tk.StringVar, api_host_var: tk.StringVar,
                 log_widget: scrolledtext.ScrolledText,
                 status_label: ttk.Label, run_button: ttk.Button):
        self.prompt_file = prompt_file
        self.session_file = session_file
        self.ratio_var = ratio_var
        self.model_var = model_var
        self.api_host_var = api_host_var
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

    def call_api(self, prompt: str, session: str) -> tuple[dict | None, bool]:
        """
        Call the image generation API.
        Returns: (result_dict, should_switch_session)
        """
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer sg-{session}"
        }
        payload = {
            "model": self.model_var.get(),
            "prompt": prompt,
            "ratio": self.ratio_var.get(),
            "resolution": RESOLUTION
        }

        try:
            api_url = f"http://{self.api_host_var.get()}{API_PATH}"
            response = requests.post(api_url, headers=headers, json=payload, timeout=1200)
            result = response.json()

            # Check for API error response (status 200 but error in body)
            if "code" in result and result["code"] != 0:
                error_code = result.get("code", 0)
                # Use friendly message if available
                friendly_msg = ERROR_MESSAGES.get(error_code)
                if friendly_msg:
                    self.log(f"⚠️ {friendly_msg}")
                else:
                    error_msg = result.get("message", "Unknown error")
                    self.log(f"API Error [{error_code}]: {error_msg[:100]}")

                # Check if this error should trigger session switch
                should_switch = error_code in SESSION_ERROR_CODES or error_code < 0
                return None, should_switch

            # Check for valid data response
            if "data" in result and result["data"]:
                return result, False

            # Empty or invalid response
            self.log(f"Invalid API response: {str(result)[:100]}")
            return None, True

        except requests.exceptions.HTTPError as e:
            self.log(f"HTTP Error: {e.response.status_code}")
            return None, True
        except requests.exceptions.JSONDecodeError as e:
            self.log(f"JSON Decode Error: {e}")
            return None, True
        except Exception as e:
            self.log(f"API Error: {e}")
            return None, True

    def process_prompt(self, prompt: str, prompt_index: int) -> bool:
        """Process a single prompt, trying different sessions on failure."""
        # Create filename from prompt: "a man is drinking beer" -> "a-man-is-drinking-beer"
        base_filename = sanitize_filename(prompt)
        # Output folder: outputs/<prompt_file_name>/
        output_dir = OUTPUT_FOLDER / self.prompt_file.stem

        tried_sessions = 0

        while self.running and tried_sessions < len(self.sessions):
            session = self.sessions[self.current_session_index]
            self.log(f"Using session [{self.current_session_index + 1}/{len(self.sessions)}]: {session[:20]}...")

            result, should_switch = self.call_api(prompt, session)

            if result is not None and "data" in result and result["data"]:
                # Success - download images
                self.log(f"✅ Thành công! Nhận được {len(result['data'])} ảnh")
                output_dir.mkdir(parents=True, exist_ok=True)

                for i, item in enumerate(result['data']):
                    url = item.get('url')
                    if url:
                        ext = '.jpeg'
                        if 'format=' in url:
                            ext = url.split('format=')[-1].split('&')[0]
                            if not ext.startswith('.'):
                                ext = '.' + ext

                        # Save as: outputs/<prompt_file_name>/a-man-is-drinking-beer_1.jpeg
                        filename = f"{base_filename}_{i+1}{ext}"
                        save_path = output_dir / filename

                        if self.download_image(url, save_path):
                            self.log(f"💾 Đã lưu: {filename}")
                        else:
                            self.log(f"❌ Lưu thất bại: {filename}")
                return True

            if should_switch:
                # Switch to next session
                self.current_session_index = (self.current_session_index + 1) % len(self.sessions)
                tried_sessions += 1

                if tried_sessions < len(self.sessions):
                    self.log(f"Switching to next session...")
                else:
                    self.log(f"All {len(self.sessions)} sessions exhausted for this prompt!")
            else:
                # Other error, don't switch session
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
        self.api_host_var = tk.StringVar(value=DEFAULT_API_HOST)

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

        # API URL input at the top
        api_frame = ttk.Frame(main_frame)
        api_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(api_frame, text="API Server:", font=('Helvetica', 10, 'bold')).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Label(api_frame, text="http://").pack(side=tk.LEFT)
        api_entry = ttk.Entry(api_frame, textvariable=self.api_host_var, width=30)
        api_entry.pack(side=tk.LEFT)
        ttk.Label(api_frame, text=API_PATH, foreground="gray").pack(side=tk.LEFT, padx=(0, 10))

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

        # Model dropdown
        ttk.Label(ctrl_frame, text="Model:").pack(side=tk.LEFT, padx=(0, 5))
        model_var = tk.StringVar(value=MODELS[1])  # Default jimeng-4.0
        model_combo = ttk.Combobox(ctrl_frame, textvariable=model_var, values=MODELS,
                                    width=14, state="readonly")
        model_combo.pack(side=tk.LEFT, padx=(0, 10))

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
        worker = WorkerThread(prompt_file, session_file, ratio_var, model_var,
                             self.api_host_var, log_widget, status_label, run_btn)
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
