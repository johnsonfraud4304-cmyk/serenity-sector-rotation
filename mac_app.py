#!/usr/bin/env python3
"""
板块轮动分析仪 — macOS桌面应用
使用 pywebview 创建原生窗口，内置Python服务器
"""

import sys
import os
import json
import time
import socket
import signal
import threading
import webbrowser
import http.server
import socketserver
import subprocess
from pathlib import Path

# ============================================================
# 配置
# ============================================================
APP_NAME = "A股板块轮动分析仪"
APP_DIR = os.path.dirname(os.path.abspath(__file__))
PORT = 8080
DATA_FILE = os.path.join(APP_DIR, "analysis_data.json")

# ============================================================
# 1. 数据更新引擎
# ============================================================
def update_data(progress_callback=None):
    """运行完整数据流水线"""
    steps = [
        ("技术分析", "data_engine.py"),
        ("深度学习训练", "train_and_predict.py"),
    ]

    for step_name, script in steps:
        if progress_callback:
            progress_callback(f"正在运行: {step_name}...")
        try:
            r = subprocess.run(
                [sys.executable, os.path.join(APP_DIR, script)],
                capture_output=True, text=True, timeout=600,
                cwd=APP_DIR
            )
            if r.returncode != 0:
                print(f"⚠ {step_name} 失败: {r.stderr[:200]}")
        except subprocess.TimeoutExpired:
            print(f"⚠ {step_name} 超时")
        except Exception as e:
            print(f"⚠ {step_name} 错误: {e}")

    # 合并所有模块
    if progress_callback:
        progress_callback("合并数据模块...")
    try:
        r = subprocess.run(
            [sys.executable, "-c", "import merge_all; merge_all.merge()"],
            capture_output=True, text=True, timeout=60, cwd=APP_DIR
        )
        if r.returncode != 0:
            # 手动合并
            _merge_all()
    except:
        _merge_all()

    if progress_callback:
        progress_callback("数据更新完成")


def _merge_all():
    """手动合并所有数据到 analysis_data.json"""
    import importlib.util

    sys.path.insert(0, APP_DIR)

    # 确保 data_engine 已运行
    if not os.path.exists(DATA_FILE):
        return

    with open(DATA_FILE) as f:
        analysis = json.load(f)

    # 合并 DL 预测
    dl_path = os.path.join(APP_DIR, "dl_predictions.json")
    if os.path.exists(dl_path):
        with open(dl_path) as f:
            dl = json.load(f)
        for name, pred in dl.get("predictions", {}).items():
            if name in analysis.get("sectors", {}):
                analysis["sectors"][name]["dl"] = {
                    "pred_mom": pred.get("pred_mom", 0),
                    "pred_phase": pred.get("pred_phase", ""),
                    "rotation_score": pred.get("rotation_score", 0),
                    "confidence": pred.get("confidence", 0),
                    "pred_phase_probs": pred.get("pred_phase_probs", {}),
                }
        analysis["dl_model"] = dl.get("model_info", {})
        analysis["top_picks"] = dl.get("top_picks", [])
        analysis["avoid_list"] = dl.get("avoid_list", [])

    # 合并周期分析
    cycle_path = os.path.join(APP_DIR, "cycle_analysis.json")
    if os.path.exists(cycle_path):
        with open(cycle_path) as f:
            cycles = json.load(f)
        analysis["cycle_summary"] = {
            name: {
                "period": c.get("consensus_period"),
                "phase": c.get("current_phase"),
                "progress": c.get("phase_progress"),
                "confidence": c.get("confidence"),
                "stability": c.get("cycle_stability"),
                "next_signal": c.get("next_buy_estimate", c.get("next_sell_estimate", "")),
                "methods": {k: v for k, v in c.get("methods", {}).items()
                           if k in ["acf_primary", "burg_primary", "time_varying"] and isinstance(v, dict)},
            }
            for name, c in cycles.items()
        }

    # 合并仪表盘
    try:
        from dashboard_engine import generate_market_dashboard
        db = generate_market_dashboard(analysis)
        if db:
            analysis["dashboard"] = db
    except:
        pass

    # 合并回测
    bt_path = os.path.join(APP_DIR, "backtest_results.json")
    if os.path.exists(bt_path):
        with open(bt_path) as f:
            bt = json.load(f)
        analysis["backtest"] = {
            "strategies": bt.get("strategies", []),
            "recommendations": bt.get("recommendations", {}),
        }

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(analysis, f, ensure_ascii=False, indent=2)


# ============================================================
# 2. HTTP 服务器
# ============================================================
class AppHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=APP_DIR, **kwargs)

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def log_message(self, format, *args):
        pass  # 静默日志


def is_port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("localhost", port)) == 0


def start_server(port=PORT):
    """启动HTTP服务器"""
    if is_port_in_use(port):
        print(f"端口 {port} 已被占用，尝试 {port+1}")
        port += 1

    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("", port), AppHandler)
    print(f"服务器启动: http://localhost:{port}")
    httpd.serve_forever()
    return port


# ============================================================
# 3. 主应用 (pywebview)
# ============================================================
def run_app():
    """启动桌面应用"""
    import webview

    # 启动服务器线程
    server_port = PORT
    if is_port_in_use(server_port):
        server_port = PORT + 1

    server_thread = threading.Thread(target=start_server, args=(server_port,), daemon=True)
    server_thread.start()
    time.sleep(1)

    url = f"http://localhost:{server_port}"

    # 创建原生窗口
    window = webview.create_window(
        title=APP_NAME,
        url=url,
        width=1400,
        height=900,
        min_size=(1000, 600),
        text_select=True,
    )

    print(f"应用启动: {url}")
    webview.start(debug=False)


# ============================================================
# 4. 菜单栏应用 (rumps)
# ============================================================
def run_menu_bar():
    """启动菜单栏应用"""
    import rumps

    rumps.debug_mode = False

    class SectorApp(rumps.App):
        def __init__(self):
            super().__init__(APP_NAME, quit_button=None)
            self.server_port = PORT
            if is_port_in_use(self.server_port):
                self.server_port = PORT + 1

            # 启动服务器
            self.server_thread = threading.Thread(target=start_server, args=(self.server_port,), daemon=True)
            self.server_thread.start()
            time.sleep(0.5)

            self.url = f"http://localhost:{self.server_port}"

            # 菜单项
            self.menu = [
                rumps.MenuItem("打开面板", callback=self.open_panel),
                rumps.MenuItem("在浏览器中打开", callback=self.open_browser),
                None,  # 分隔线
                rumps.MenuItem("刷新数据", callback=self.refresh_data),
                None,
                rumps.MenuItem("退出", callback=self.quit_app),
            ]

            # 自动打开窗口
            time.sleep(1)
            webbrowser.open(self.url)

        def open_panel(self, _):
            webbrowser.open(self.url)

        def open_browser(self, _):
            webbrowser.open(self.url)

        def refresh_data(self, _):
            threading.Thread(target=self._do_refresh, daemon=True).start()

        def _do_refresh(self):
            update_data()
            webbrowser.open(self.url)

        def quit_app(self, _):
            rumps.quit_application()

    app = SectorApp()
    app.run()


# ============================================================
# 入口
# ============================================================
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--menu", action="store_true", help="菜单栏模式")
    parser.add_argument("--port", type=int, default=PORT, help="服务器端口")
    args = parser.parse_args()

    PORT = args.port

    if args.menu:
        run_menu_bar()
    else:
        run_app()
