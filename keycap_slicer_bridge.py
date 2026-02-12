#!/usr/bin/env python3
"""
Keycap Slicer Bridge v2.1
ブラウザ(Keycap Generator)からスライサーへモデルを直接転送するブリッジアプリ
"""

import os
import sys
import json
import tempfile
import subprocess
import threading
import time
import shutil
from http.server import HTTPServer, BaseHTTPRequestHandler
import cgi

# === Configuration ===
PORT = 19876
APP_NAME = "Keycap Slicer Bridge"
VERSION = "2.1.0"
APP_DIR_NAME = "KeycapSlicerBridge"
INSTALL_DIR = os.path.join(os.environ.get('LOCALAPPDATA', os.path.expanduser('~')), APP_DIR_NAME)
TEMP_DIR = os.path.join(tempfile.gettempdir(), "keycap-slicer-bridge")
CONFIG_FILE = os.path.join(INSTALL_DIR, "config.json")
REG_KEY_PATH = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run"
REG_VALUE_NAME = "KeycapSlicerBridge"

ALLOWED_ORIGINS = [
    "https://keycapgenerator.com",
    "https://www.keycapgenerator.com",
    "http://localhost",
    "http://127.0.0.1",
    "https://sireai.github.io",
    "null",
]

SLICER_PATHS = {
    "bambu": [
        os.path.expandvars(r"%ProgramFiles%\Bambu Studio\bambu-studio.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Bambu Studio\bambu-studio.exe"),
        os.path.expandvars(r"%LocalAppData%\Programs\Bambu Studio\bambu-studio.exe"),
    ],
    "orca": [
        os.path.expandvars(r"%ProgramFiles%\OrcaSlicer\orca-slicer.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\OrcaSlicer\orca-slicer.exe"),
        os.path.expandvars(r"%LocalAppData%\Programs\OrcaSlicer\orca-slicer.exe"),
    ]
}

ALLOWED_EXTENSIONS = {'.stl', '.3mf', '.obj', '.step', '.stp'}

# Embedded SVG data for icon generation
KEYCAP_SVG = '''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 306.06 217.55">
  <defs><style>
    .c1{stroke:#ccc;stroke-miterlimit:10;fill:none}
    .c2{fill:aqua;stroke:aqua;stroke-miterlimit:10}
    .c3{stroke:aqua;stroke-miterlimit:10;fill:none;stroke-width:4px}
    .c4{fill:#b3b3b3}
  </style></defs>
  <polygon class="c4" points="273.2 41.92 305.59 144.63 149.26 216.93 148.91 216.18 151.25 80.26 273.2 41.92"/>
  <polygon class="c4" points="273.2 41.92 151.25 80.26 35.16 29.06 152.73 .49 273.2 41.92"/>
  <polygon class="c4" points="151.25 80.26 148.91 216.18 .25 136.62 .61 135.77 35.16 29.06 151.25 80.26"/>
  <line class="c1" x1="35.16" y1="29.06" x2=".61" y2="135.77"/>
  <line class="c1" x1=".25" y1="136.62" x2="148.91" y2="216.18"/>
  <line class="c1" x1="151.25" y1="80.26" x2="35.16" y2="29.06"/>
  <line class="c1" x1="148.91" y1="216.18" x2="151.25" y2="80.26"/>
  <line class="c1" x1="273.2" y1="41.92" x2="151.25" y2="80.26"/>
  <line class="c1" x1="305.59" y1="144.63" x2="273.2" y2="41.92"/>
  <polyline class="c1" points="148.91 217.1 149.26 216.93 305.59 144.63"/>
  <line class="c1" x1="152.73" y1=".49" x2="273.2" y2="41.92"/>
  <line class="c1" x1="152.73" y1=".49" x2="35.16" y2="29.06"/>
  <line class="c3" x1="86.1" y1="30.23" x2="119.97" y2="22"/>
  <line class="c3" x1="155.68" y1="60.92" x2="86.1" y2="30.23"/>
  <line class="c3" x1="224.32" y1="40.72" x2="154.45" y2="60.92"/>
  <line class="c3" x1="224.32" y1="41.22" x2="198.07" y2="32.19"/>
  <path class="c2" d="M167.62,24.24s-20.08-4.1-28.79,0c-8.7,4.1,7.85-6.02,3.19-9.13s11.8,5.35,23.8.19c12-5.15-13.25,5.77,1.79,8.94Z"/>
  <path class="c2" d="M169.51,46.26s-18.64-3.8-26.72,0c-8.08,3.8,7.29-5.59,2.96-8.48-4.32-2.88,10.96,4.96,22.1.18,11.14-4.78-12.3,5.36,1.66,8.3Z"/>
  <path class="c2" d="M134.59,37.59s-10.53-2.15-15.09,0,4.12-3.16,1.67-4.79c-2.44-1.63,6.19,2.8,12.48.1,6.29-2.7-6.94,3.03.94,4.69Z"/>
</svg>'''


# =====================================================
# Icon Generation
# =====================================================
def create_keycap_icon(size=64):
    """Render keycap icon using PIL at any size with high quality"""
    from PIL import Image, ImageDraw

    # Render at 4x then downscale for anti-aliasing
    render_size = size * 4
    img = Image.new('RGBA', (render_size, render_size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # SVG viewBox: 0 0 306.06 217.55
    # We need to fit this into a square with padding
    vw, vh = 306.06, 217.55
    padding = 0.08  # 8% padding
    usable = render_size * (1 - 2 * padding)
    scale = min(usable / vw, usable / vh)
    ox = (render_size - vw * scale) / 2
    oy = (render_size - vh * scale) / 2

    def p(x, y):
        """Transform SVG coords to pixel coords"""
        return (ox + x * scale, oy + y * scale)

    def poly(points, fill=None, outline=None, width=1):
        coords = [p(x, y) for x, y in points]
        if fill:
            draw.polygon(coords, fill=fill)
        if outline:
            for i in range(len(coords)):
                j = (i + 1) % len(coords)
                draw.line([coords[i], coords[j]], fill=outline, width=max(1, int(width * scale / 80)))

    def line(x1, y1, x2, y2, fill, width):
        w = max(1, int(width * scale / 80))
        draw.line([p(x1, y1), p(x2, y2)], fill=fill, width=w)

    # Background (dark circle for tray visibility)
    margin = int(render_size * 0.02)
    draw.ellipse([margin, margin, render_size - margin, render_size - margin],
                 fill=(26, 26, 46, 240))

    # Gray keycap faces
    gray = (179, 179, 179, 255)
    # Right face
    poly([(273.2, 41.92), (305.59, 144.63), (149.26, 216.93), (148.91, 216.18), (151.25, 80.26)], fill=(140, 140, 140, 255))
    # Top face
    poly([(273.2, 41.92), (151.25, 80.26), (35.16, 29.06), (152.73, 0.49)], fill=gray)
    # Left face
    poly([(151.25, 80.26), (148.91, 216.18), (0.25, 136.62), (0.61, 135.77), (35.16, 29.06)], fill=(120, 120, 120, 255))

    # Gray edge lines
    edge_color = (204, 204, 204, 255)
    lw = 1.0
    line(35.16, 29.06, 0.61, 135.77, edge_color, lw)
    line(0.25, 136.62, 148.91, 216.18, edge_color, lw)
    line(151.25, 80.26, 35.16, 29.06, edge_color, lw)
    line(148.91, 216.18, 151.25, 80.26, edge_color, lw)
    line(273.2, 41.92, 151.25, 80.26, edge_color, lw)
    line(305.59, 144.63, 273.2, 41.92, edge_color, lw)
    line(148.91, 217.1, 305.59, 144.63, edge_color, lw)
    line(152.73, 0.49, 273.2, 41.92, edge_color, lw)
    line(152.73, 0.49, 35.16, 29.06, edge_color, lw)

    # Cyan legend lines (thicker)
    cyan = (0, 255, 255, 255)
    lw_thick = 4.0
    line(86.1, 30.23, 119.97, 22.0, cyan, lw_thick)
    line(155.68, 60.92, 86.1, 30.23, cyan, lw_thick)
    line(224.32, 40.72, 154.45, 60.92, cyan, lw_thick)
    line(224.32, 41.22, 198.07, 32.19, cyan, lw_thick)

    # Cyan decorative shapes (simplified as ellipses/ovals on the top face)
    # Large shape around (150, 24)
    cx1, cy1 = p(150, 20)
    rx1 = 30 * scale / 80
    ry1 = 8 * scale / 80
    draw.ellipse([cx1 - rx1, cy1 - ry1, cx1 + rx1, cy1 + ry1], fill=cyan)

    # Medium shape around (152, 44)
    cx2, cy2 = p(152, 43)
    rx2 = 26 * scale / 80
    ry2 = 7 * scale / 80
    draw.ellipse([cx2 - rx2, cy2 - ry2, cx2 + rx2, cy2 + ry2], fill=cyan)

    # Small shape around (127, 36)
    cx3, cy3 = p(127, 36)
    rx3 = 15 * scale / 80
    ry3 = 5 * scale / 80
    draw.ellipse([cx3 - rx3, cy3 - ry3, cx3 + rx3, cy3 + ry3], fill=cyan)

    # Downscale with high-quality resampling
    img = img.resize((size, size), Image.LANCZOS)
    return img


def create_keycap_icon_from_svg(size=64):
    """Try to use cairosvg for perfect SVG rendering, fallback to PIL"""
    try:
        import cairosvg
        from PIL import Image
        import io
        png_data = cairosvg.svg2png(bytestring=KEYCAP_SVG.encode(), output_width=size, output_height=size)
        # Add dark circle background for tray visibility
        svg_img = Image.open(io.BytesIO(png_data)).convert('RGBA')
        bg = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        draw_bg = __import__('PIL.ImageDraw', fromlist=['ImageDraw']).Draw(bg)
        m = max(1, size // 32)
        draw_bg.ellipse([m, m, size - m, size - m], fill=(26, 26, 46, 240))
        # Paste SVG on top with padding
        pad = int(size * 0.1)
        svg_resized = svg_img.resize((size - 2 * pad, size - 2 * pad), Image.LANCZOS)
        bg.paste(svg_resized, (pad, pad + int(size * 0.05)), svg_resized)
        return bg
    except Exception:
        return create_keycap_icon(size)


def create_icon_file(path, sizes=None):
    """Create .ico file with multiple sizes"""
    from PIL import Image
    if sizes is None:
        sizes = [16, 24, 32, 48, 64, 128, 256]
    images = [create_keycap_icon_from_svg(sz) for sz in sizes]
    images[0].save(path, format='ICO', sizes=[(s, s) for s in sizes], append_images=images[1:])
    return path


# =====================================================
# Windows API helpers (thread-safe message boxes)
# =====================================================
def win_msgbox(text, title, flags=0):
    """Thread-safe Windows MessageBox using ctypes"""
    try:
        import ctypes
        MB_OK = 0x00
        MB_YESNO = 0x04
        MB_ICONINFO = 0x40
        MB_ICONWARNING = 0x30
        MB_ICONERROR = 0x10
        IDYES = 6
        result = ctypes.windll.user32.MessageBoxW(0, text, title, flags)
        return result
    except Exception:
        print(f"[MsgBox] {title}: {text}")
        return 0


def win_yesno(text, title):
    """Thread-safe Yes/No dialog, returns True if Yes"""
    try:
        import ctypes
        MB_YESNO = 0x04
        MB_ICONWARNING = 0x30
        IDYES = 6
        result = ctypes.windll.user32.MessageBoxW(0, text, title, MB_YESNO | MB_ICONWARNING)
        return result == IDYES
    except Exception:
        return False


def win_info(text, title):
    """Thread-safe info dialog"""
    try:
        import ctypes
        MB_OK = 0x00
        MB_ICONINFO = 0x40
        ctypes.windll.user32.MessageBoxW(0, text, title, MB_OK | MB_ICONINFO)
    except Exception:
        print(f"[Info] {title}: {text}")


# =====================================================
# Registry / Autostart
# =====================================================
def get_exe_path():
    if getattr(sys, 'frozen', False):
        return sys.executable
    return os.path.abspath(__file__)


def is_autostart_enabled():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEY_PATH, 0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, REG_VALUE_NAME)
            return True
    except Exception:
        return False


def set_autostart(enable):
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEY_PATH, 0,
                            winreg.KEY_SET_VALUE | winreg.KEY_READ) as key:
            if enable:
                exe = get_exe_path()
                winreg.SetValueEx(key, REG_VALUE_NAME, 0, winreg.REG_SZ, f'"{exe}" --silent')
            else:
                try:
                    winreg.DeleteValue(key, REG_VALUE_NAME)
                except FileNotFoundError:
                    pass
            return True
    except Exception as e:
        print(f"[Autostart] Error: {e}")
        return False


# =====================================================
# Config
# =====================================================
def load_config():
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
    except Exception:
        pass
    return {"installed": False, "autostart": False}


def save_config(config):
    try:
        os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
    except Exception as e:
        print(f"[Config] Save error: {e}")


# =====================================================
# Installer UI (tkinter)
# =====================================================
def show_installer():
    """Show installer dialog"""
    import tkinter as tk
    from PIL import ImageTk

    result = {"action": None, "autostart": True}

    WIN_W, WIN_H = 540, 560

    root = tk.Tk()
    root.title(f"{APP_NAME} - Setup")
    root.geometry(f"{WIN_W}x{WIN_H}")
    root.resizable(False, False)
    root.configure(bg="#1a1a2e")

    # Set titlebar icon
    try:
        ico_img = create_keycap_icon_from_svg(32)
        _tk_icon = ImageTk.PhotoImage(ico_img)
        root.iconphoto(True, _tk_icon)
    except Exception:
        pass

    # Center on screen
    root.update_idletasks()
    x = (root.winfo_screenwidth() - WIN_W) // 2
    y = (root.winfo_screenheight() - WIN_H) // 2
    root.geometry(f"{WIN_W}x{WIN_H}+{x}+{y}")

    # Icon area - use PIL rendered icon instead of emoji
    try:
        header_img = create_keycap_icon_from_svg(72)
        _tk_header = ImageTk.PhotoImage(header_img)
        tk.Label(root, image=_tk_header, bg="#1a1a2e").pack(pady=(20, 4))
        root._keep_header = _tk_header  # prevent GC
    except Exception:
        tk.Label(root, text="⌨", font=("Segoe UI Emoji", 36),
                 bg="#1a1a2e", fg="#00ffff").pack(pady=(20, 4))

    tk.Label(root, text=APP_NAME, font=("Segoe UI", 18, "bold"),
             bg="#1a1a2e", fg="#ffffff").pack()
    tk.Label(root, text=f"Version {VERSION}", font=("Segoe UI", 9),
             bg="#1a1a2e", fg="#888888").pack(pady=(2, 0))

    # Description
    desc = (
        "Keycap Generator のブラウザから\n"
        "Bambu Studio / OrcaSlicer へ\n"
        "モデルを直接転送するブリッジアプリです。"
    )
    tk.Label(root, text=desc, font=("Segoe UI", 10), bg="#1a1a2e", fg="#cccccc",
             justify="center").pack(pady=(12, 8))

    # Install location
    loc_frame = tk.Frame(root, bg="#1a1a2e")
    loc_frame.pack(fill="x", padx=40, pady=(4, 0))
    tk.Label(loc_frame, text="インストール先:", font=("Segoe UI", 9),
             bg="#1a1a2e", fg="#999999", anchor="w").pack(anchor="w")
    tk.Label(loc_frame, text=INSTALL_DIR, font=("Segoe UI", 8),
             bg="#222244", fg="#4fc3f7", relief="flat", padx=8, pady=3,
             anchor="w", wraplength=450).pack(fill="x", pady=(2, 0))

    # Autostart checkbox
    autostart_var = tk.BooleanVar(value=True)
    cb = tk.Checkbutton(root, text="  Windows 起動時に自動起動する",
                        variable=autostart_var,
                        font=("Segoe UI", 10), bg="#1a1a2e", fg="#cccccc",
                        selectcolor="#2a2a4e", activebackground="#1a1a2e",
                        activeforeground="#cccccc", anchor="w")
    cb.pack(pady=(10, 6))

    # Slicer detection
    det_frame = tk.Frame(root, bg="#1e1e38", relief="flat", bd=0)
    det_frame.pack(fill="x", padx=40, pady=(4, 0))
    tk.Label(det_frame, text="スライサー検出状況", font=("Segoe UI", 9, "bold"),
             bg="#1e1e38", fg="#999999").pack(anchor="w", padx=10, pady=(6, 2))
    for name, stype in [("Bambu Studio", "bambu"), ("OrcaSlicer", "orca")]:
        path = find_slicer(stype)
        if path:
            status_text = f"  ✓  {name} — 検出済み"
            color = "#4caf50"
        else:
            status_text = f"  ✗  {name} — 未検出"
            color = "#f44336"
        tk.Label(det_frame, text=status_text, font=("Segoe UI", 9),
                 bg="#1e1e38", fg=color, anchor="w").pack(anchor="w", padx=10, pady=1)
    tk.Label(det_frame, text="", bg="#1e1e38", font=("Segoe UI", 1)).pack(pady=(0, 4))

    # Buttons
    btn_frame = tk.Frame(root, bg="#1a1a2e")
    btn_frame.pack(pady=(18, 12))

    def on_install():
        result["action"] = "install"
        result["autostart"] = autostart_var.get()
        root.destroy()

    def on_cancel():
        result["action"] = "cancel"
        root.destroy()

    install_btn = tk.Button(btn_frame, text="  インストール  ", command=on_install,
                            font=("Segoe UI", 12, "bold"), bg="#4fc3f7", fg="#000000",
                            relief="flat", padx=20, pady=7, cursor="hand2")
    install_btn.pack(side="left", padx=10)

    cancel_btn = tk.Button(btn_frame, text="  キャンセル  ", command=on_cancel,
                           font=("Segoe UI", 12), bg="#444444", fg="#cccccc",
                           relief="flat", padx=14, pady=7, cursor="hand2")
    cancel_btn.pack(side="left", padx=10)

    root.mainloop()
    return result


def do_install(autostart=True):
    try:
        os.makedirs(INSTALL_DIR, exist_ok=True)

        src = get_exe_path()
        if getattr(sys, 'frozen', False):
            dst = os.path.join(INSTALL_DIR, os.path.basename(src))
            if os.path.abspath(src).lower() != os.path.abspath(dst).lower():
                shutil.copy2(src, dst)

        try:
            create_icon_file(os.path.join(INSTALL_DIR, "icon.ico"))
        except Exception as e:
            print(f"[Install] Icon error: {e}")

        if autostart:
            set_autostart(True)

        config = load_config()
        config["installed"] = True
        config["autostart"] = autostart
        save_config(config)

        try:
            create_shortcut()
        except Exception as e:
            print(f"[Install] Shortcut error: {e}")

        print(f"[Install] Installed to {INSTALL_DIR}")
        return True
    except Exception as e:
        print(f"[Install] Error: {e}")
        return False


def create_shortcut():
    try:
        start_menu = os.path.join(os.environ.get('APPDATA', ''),
                                   'Microsoft', 'Windows', 'Start Menu', 'Programs')
        shortcut_path = os.path.join(start_menu, f"{APP_NAME}.lnk")
        exe_path = get_exe_path()
        if getattr(sys, 'frozen', False):
            exe_path = os.path.join(INSTALL_DIR, os.path.basename(exe_path))
        ico_path = os.path.join(INSTALL_DIR, "icon.ico")

        ps_cmd = (
            f'$ws = New-Object -ComObject WScript.Shell; '
            f'$s = $ws.CreateShortcut("{shortcut_path}"); '
            f'$s.TargetPath = "{exe_path}"; '
            f'$s.Arguments = "--silent"; '
            f'$s.WorkingDirectory = "{INSTALL_DIR}"; '
            f'$s.Description = "{APP_NAME}"; '
            f'if (Test-Path "{ico_path}") {{ $s.IconLocation = "{ico_path}" }}; '
            f'$s.Save()'
        )
        subprocess.run(['powershell', '-Command', ps_cmd],
                       capture_output=True, timeout=10,
                       creationflags=0x08000000 if sys.platform == 'win32' else 0)
    except Exception as e:
        print(f"[Shortcut] Error: {e}")


# =====================================================
# Uninstaller
# =====================================================
def do_uninstall():
    try:
        set_autostart(False)

        # Remove shortcut
        start_menu = os.path.join(os.environ.get('APPDATA', ''),
                                   'Microsoft', 'Windows', 'Start Menu', 'Programs')
        shortcut_path = os.path.join(start_menu, f"{APP_NAME}.lnk")
        if os.path.exists(shortcut_path):
            os.remove(shortcut_path)

        # Remove temp
        if os.path.exists(TEMP_DIR):
            shutil.rmtree(TEMP_DIR, ignore_errors=True)

        # Schedule self-deletion
        bat_content = (
            '@echo off\n'
            'timeout /t 3 /nobreak >nul\n'
            f'rmdir /s /q "{INSTALL_DIR}"\n'
            'del "%~f0"\n'
        )
        bat_path = os.path.join(tempfile.gettempdir(), "uninstall_ksb.bat")
        with open(bat_path, 'w') as f:
            f.write(bat_content)

        subprocess.Popen(
            ['cmd', '/c', bat_path],
            creationflags=0x08000000 if sys.platform == 'win32' else 0
        )

        win_info(
            f"{APP_NAME} をアンインストールしました。\nアプリを終了します。",
            APP_NAME
        )
        return True
    except Exception as e:
        print(f"[Uninstall] Error: {e}")
        return False


# =====================================================
# Slicer Detection
# =====================================================
def find_slicer(slicer_type):
    paths = SLICER_PATHS.get(slicer_type, [])
    for p in paths:
        if os.path.isfile(p):
            return p
    try:
        import winreg
        reg_keys = []
        if slicer_type == "bambu":
            reg_keys = [
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Bambu Studio"),
                (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Bambu Studio"),
                (winreg.HKEY_CLASSES_ROOT, r"bambustudio\shell\open\command"),
            ]
        else:
            reg_keys = [
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\OrcaSlicer"),
                (winreg.HKEY_CURRENT_USER, r"SOFTWARE\OrcaSlicer"),
                (winreg.HKEY_CLASSES_ROOT, r"orcaslicer\shell\open\command"),
            ]
        for hive, key_path in reg_keys:
            try:
                with winreg.OpenKey(hive, key_path) as key:
                    val, _ = winreg.QueryValueEx(key, "")
                    exe_path = val.strip('"').split('"')[0]
                    if os.path.isfile(exe_path):
                        return exe_path
            except (FileNotFoundError, OSError):
                continue
    except Exception:
        pass
    exe_name = "bambu-studio.exe" if slicer_type == "bambu" else "orca-slicer.exe"
    return shutil.which(exe_name)


def is_origin_allowed(origin):
    if not origin:
        return True
    return any(origin.startswith(a) for a in ALLOWED_ORIGINS)


# =====================================================
# HTTP Server
# =====================================================
class BridgeHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _set_cors_headers(self):
        origin = self.headers.get('Origin', '')
        if is_origin_allowed(origin):
            self.send_header('Access-Control-Allow-Origin', origin if origin else '*')
        else:
            self.send_header('Access-Control-Allow-Origin', 'null')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Access-Control-Max-Age', '86400')

    def _send_json(self, status, data):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self._set_cors_headers()
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))

    def do_OPTIONS(self):
        self.send_response(204)
        self._set_cors_headers()
        self.end_headers()

    def do_GET(self):
        if self.path == '/health':
            bambu = find_slicer("bambu")
            orca = find_slicer("orca")
            self._send_json(200, {
                "status": "ok", "version": VERSION, "app": APP_NAME,
                "slicers": {
                    "bambu": {"available": bambu is not None, "path": bambu or ""},
                    "orca": {"available": orca is not None, "path": orca or ""},
                }
            })
        else:
            self._send_json(404, {"error": "Not found"})

    def do_POST(self):
        origin = self.headers.get('Origin', '')
        if not is_origin_allowed(origin):
            self._send_json(403, {"error": "Origin not allowed"})
            return
        if self.path != '/open':
            self._send_json(404, {"error": "Not found"})
            return
        try:
            content_type = self.headers.get('Content-Type', '')
            if 'multipart/form-data' not in content_type:
                self._send_json(400, {"error": "Expected multipart/form-data"})
                return

            form = cgi.FieldStorage(
                fp=self.rfile, headers=self.headers,
                environ={'REQUEST_METHOD': 'POST', 'CONTENT_TYPE': content_type}
            )

            slicer_type = form.getvalue('slicer', 'bambu').lower()
            if slicer_type not in ('bambu', 'orca'):
                self._send_json(400, {"error": f"Unknown slicer: {slicer_type}"})
                return

            slicer_path = find_slicer(slicer_type)
            if not slicer_path:
                name = "Bambu Studio" if slicer_type == "bambu" else "OrcaSlicer"
                self._send_json(404, {"error": f"{name} not found",
                                       "message": f"{name}が見つかりません。"})
                return

            if 'file' not in form:
                self._send_json(400, {"error": "No file provided"})
                return

            file_item = form['file']
            filename = os.path.basename(file_item.filename or "model.3mf")
            _, ext = os.path.splitext(filename)
            if ext.lower() not in ALLOWED_EXTENSIONS:
                self._send_json(400, {"error": f"File type not allowed: {ext}"})
                return

            os.makedirs(TEMP_DIR, exist_ok=True)
            file_path = os.path.join(TEMP_DIR, filename)
            file_data = file_item.file.read()
            if len(file_data) > 100 * 1024 * 1024:
                self._send_json(400, {"error": "File too large (max 100MB)"})
                return

            with open(file_path, 'wb') as f:
                f.write(file_data)

            subprocess.Popen([slicer_path, file_path])
            name = "Bambu Studio" if slicer_type == "bambu" else "OrcaSlicer"
            self._send_json(200, {
                "success": True,
                "message": f"{name}でモデルを開きました",
                "slicer": name, "file": filename
            })
        except Exception as e:
            self._send_json(500, {"error": "Internal error", "detail": str(e)})


def run_server():
    HTTPServer(('127.0.0.1', PORT), BridgeHandler).serve_forever()


# =====================================================
# System Tray
# =====================================================
def create_tray_icon():
    try:
        import pystray

        icon_img = create_keycap_icon_from_svg(64)

        def on_healthcheck(icon, item):
            import webbrowser
            webbrowser.open(f"http://localhost:{PORT}/health")

        def on_toggle_autostart(icon, item):
            new_state = not is_autostart_enabled()
            if set_autostart(new_state):
                config = load_config()
                config["autostart"] = new_state
                save_config(config)
                icon.update_menu()

        def autostart_checked(item):
            return is_autostart_enabled()

        def on_uninstall(icon, item):
            # Run in separate thread to avoid pystray blocking
            def _do():
                import ctypes
                MB_YESNO = 0x04
                MB_ICONWARNING = 0x30
                MB_TOPMOST = 0x40000
                IDYES = 6
                result = ctypes.windll.user32.MessageBoxW(
                    0,
                    f"{APP_NAME} をアンインストールしますか？\n\n"
                    f"以下が削除されます:\n"
                    f"  • インストールフォルダ\n"
                    f"  • 自動起動設定\n"
                    f"  • スタートメニューのショートカット",
                    f"{APP_NAME} - アンインストール",
                    MB_YESNO | MB_ICONWARNING | MB_TOPMOST
                )
                if result == IDYES:
                    icon.stop()
                    do_uninstall()
                    os._exit(0)
            threading.Thread(target=_do, daemon=True).start()

        def on_quit(icon, item):
            icon.stop()
            os._exit(0)

        menu = pystray.Menu(
            pystray.MenuItem(f"{APP_NAME} v{VERSION}", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("ヘルスチェック", on_healthcheck),
            pystray.MenuItem("Windows起動時に自動起動",
                             on_toggle_autostart, checked=autostart_checked),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("アンインストール", on_uninstall),
            pystray.MenuItem("終了", on_quit),
        )

        return pystray.Icon(APP_NAME, icon_img, f"{APP_NAME} - Port {PORT}", menu)
    except Exception as e:
        print(f"[{APP_NAME}] Tray icon failed: {e}")
        return None


# =====================================================
# Main
# =====================================================
def main():
    silent = '--silent' in sys.argv
    config = load_config()

    # First run installer
    if not config.get("installed") and not silent:
        result = show_installer()
        if result["action"] == "install":
            if do_install(autostart=result.get("autostart", True)):
                config = load_config()
                win_info(
                    f"{APP_NAME} をインストールしました！\n\n"
                    f"タスクトレイに常駐します。\n"
                    f"アイコンを右クリックでメニューを表示できます。",
                    APP_NAME
                )
            else:
                win_info("インストールに失敗しました。", APP_NAME)
                sys.exit(1)
        elif result["action"] != "cancel":
            sys.exit(0)

    # Banner
    if not silent:
        print(f"{'=' * 50}")
        print(f"  {APP_NAME} v{VERSION}")
        print(f"  http://127.0.0.1:{PORT}")
        print(f"{'=' * 50}")
        for name, stype in [("Bambu Studio", "bambu"), ("OrcaSlicer", "orca")]:
            path = find_slicer(stype)
            mark = "✓" if path else "✗"
            print(f"  {mark} {name}: {path or 'not found'}")
        print()

    os.makedirs(TEMP_DIR, exist_ok=True)

    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    if not silent:
        print(f"  Server started on port {PORT}")

    icon = create_tray_icon()
    if icon:
        if not silent:
            print(f"  Tray icon active")
        icon.run()
    else:
        if not silent:
            print(f"  Console mode (Ctrl+C to quit)")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            sys.exit(0)


if __name__ == '__main__':
    main()
