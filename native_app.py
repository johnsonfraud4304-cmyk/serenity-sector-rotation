#!/usr/bin/env python3
"""
Serenity — 原生 macOS 应用
pywebview 创建独立原生窗口，启动时自动刷新数据
"""
import sys
import os
import json
import time
import socket
import subprocess
import threading
import http.server
import socketserver
import webview
from urllib.parse import urlparse

APP_DIR = os.path.dirname(os.path.abspath(__file__))
PORT = 8080

# 刷新状态
refresh_state = {
    "running": False, "step": "", "progress": 0, "detail": "", "last_update": "",
    "dl_running": False, "dl_progress": 0, "dl_detail": "",
}


def run_quick_refresh():
    refresh_state["running"] = True
    refresh_state["progress"] = 0
    try:
        refresh_state["step"] = "获取ETF行情"
        refresh_state["detail"] = "正在获取83只ETF最新数据..."
        refresh_state["progress"] = 5
        subprocess.run([sys.executable, os.path.join(APP_DIR, "data_engine.py")],
                      capture_output=True, text=True, timeout=300, cwd=APP_DIR)
        refresh_state["progress"] = 20
        refresh_state["step"] = "运行分析引擎"
        refresh_state["detail"] = "MACD/布林带/回撤/回测/周期分析..."
        subprocess.run([sys.executable, os.path.join(APP_DIR, "full_analysis.py")],
                      capture_output=True, text=True, timeout=600, cwd=APP_DIR)
        refresh_state["progress"] = 90
        refresh_state["step"] = "合并AI预测"
        _merge_dl()
        refresh_state["progress"] = 100
        refresh_state["step"] = "完成"
        refresh_state["detail"] = ""
        refresh_state["last_update"] = time.strftime("%Y-%m-%d %H:%M:%S")
    except Exception as e:
        refresh_state["detail"] = f"出错: {str(e)[:100]}"
    finally:
        refresh_state["running"] = False


def run_dl_training():
    refresh_state["dl_running"] = True
    refresh_state["dl_progress"] = 0
    try:
        refresh_state["dl_detail"] = "准备训练数据..."
        refresh_state["dl_progress"] = 5
        subprocess.run([sys.executable, os.path.join(APP_DIR, "train_and_predict.py")],
                      capture_output=True, text=True, timeout=600, cwd=APP_DIR)
        refresh_state["dl_progress"] = 80
        refresh_state["dl_detail"] = "合并预测结果..."
        _merge_dl()
        refresh_state["dl_progress"] = 100
        refresh_state["dl_detail"] = "训练完成"
        refresh_state["last_update"] = time.strftime("%Y-%m-%d %H:%M:%S")
    except Exception as e:
        refresh_state["dl_detail"] = f"出错: {str(e)[:100]}"
    finally:
        refresh_state["dl_running"] = False


def _merge_dl():
    dl_path = os.path.join(APP_DIR, "dl_predictions.json")
    analysis_path = os.path.join(APP_DIR, "analysis_data.json")
    if not os.path.exists(dl_path) or not os.path.exists(analysis_path):
        return
    try:
        with open(dl_path) as f: dl = json.load(f)
        with open(analysis_path) as f: analysis = json.load(f)
        for name, pred in dl.get("predictions", {}).items():
            if name in analysis.get("sectors", {}):
                analysis["sectors"][name]["dl"] = {
                    "pred_mom": pred.get("pred_mom", 0), "pred_phase": pred.get("pred_phase", ""),
                    "rotation_score": pred.get("rotation_score", 0), "confidence": pred.get("confidence", 0),
                    "pred_phase_probs": pred.get("pred_phase_probs", {}),
                }
        analysis["dl_model"] = dl.get("model_info", {})
        with open(analysis_path, "w", encoding="utf-8") as f:
            json.dump(analysis, f, ensure_ascii=False, indent=2)
    except: pass


class AppHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=APP_DIR, **kw)
    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()
    def do_GET(self):
        from urllib.parse import parse_qs
        parsed = urlparse(self.path)
        p = parsed.path
        if p == "/api/refresh":
            if refresh_state["running"]:
                self._j({"status": "running", **refresh_state})
            else:
                threading.Thread(target=run_quick_refresh, daemon=True).start()
                self._j({"status": "started"})
        elif p == "/api/refresh/dl":
            if refresh_state["dl_running"]:
                self._j({"status": "running", **refresh_state})
            else:
                threading.Thread(target=run_dl_training, daemon=True).start()
                self._j({"status": "started"})
        elif p == "/api/refresh/status":
            self._j(refresh_state)
        elif p == "/api/refresh/all":
            if refresh_state["running"] or refresh_state["dl_running"]:
                self._j({"status": "running", **refresh_state})
            else:
                def _all():
                    run_quick_refresh()
                    run_dl_training()
                threading.Thread(target=_all, daemon=True).start()
                self._j({"status": "started"})
        elif p == "/api/backtest":
            params = parse_qs(parsed.query)
            code = params.get("code", [""])[0]
            if not code:
                self._j({"error": "请输入股票代码"})
            else:
                try:
                    from stock_backtest import run_stock_backtest
                    result = run_stock_backtest(code)
                    self._j(result)
                except Exception as e:
                    self._j({"error": f"回测失败: {str(e)[:200]}"})
        elif p == "/api/guide":
            try:
                from stock_backtest import STRATEGY_GUIDE
                self._j(STRATEGY_GUIDE)
            except Exception as e:
                self._j({"error": str(e)})
        elif p == "/api/recommend":
            params = parse_qs(parsed.query)
            code = params.get("code", [""])[0]
            if not code:
                self._j({"error": "请输入股票代码或名称"})
            else:
                try:
                    from recommend_engine import analyze_stock
                    result = analyze_stock(code)
                    # 附加止损止盈
                    from advanced_v2 import compute_stop_loss_levels, compute_position_sizing
                    closes = result.get('_closes', [result['current_price']] * 20)
                    levels = compute_stop_loss_levels(closes, result['rsi'], result['mom_20'], 0, 0)
                    result['stop_loss'] = levels
                    result['position'] = compute_position_sizing(100000, result['current_price'], levels['stop_loss_pct'])
                    self._j(result)
                except Exception as e:
                    self._j({"error": f"分析失败: {str(e)[:200]}"})
        elif p == "/api/portfolio":
            try:
                with open(os.path.join(APP_DIR, 'analysis_data.json')) as f:
                    d = json.load(f)
                from advanced_v2 import compute_portfolio_optimization
                capital = int(parse_qs(parsed.query).get('capital', ['100000'])[0])
                result = compute_portfolio_optimization(d['sectors'], capital)
                self._j(result)
            except Exception as e:
                self._j({"error": str(e)})
        elif p == "/api/daily_summary":
            try:
                with open(os.path.join(APP_DIR, 'analysis_data.json')) as f:
                    d = json.load(f)
                from advanced_v2 import compute_daily_summary
                result = compute_daily_summary(d['sectors'], {}, {})
                self._j(result)
            except Exception as e:
                self._j({"error": str(e)})
        elif p == "/api/portfolio/positions":
            try:
                from portfolio_tracker import get_positions_with_pnl
                with open(os.path.join(APP_DIR, 'analysis_data.json')) as f:
                    d = json.load(f)
                prices = {s['code']: s['current_price'] for s in d['sectors'].values()}
                result = get_positions_with_pnl(prices)
                self._j(result)
            except Exception as e:
                self._j({"error": str(e)})
        elif p == "/api/portfolio/trade":
            params = parse_qs(parsed.query)
            code = params.get("code", [""])[0]
            name = params.get("name", [""])[0]
            action = params.get("action", ["BUY"])[0]
            price = params.get("price", ["0"])[0]
            quantity = params.get("quantity", ["0"])[0]
            category = params.get("category", [""])[0]
            if not code or not name:
                self._j({"error": "缺少参数"})
            else:
                try:
                    from portfolio_tracker import add_trade
                    trade = add_trade(code, name, action, price, quantity, category)
                    self._j({"ok": True, "trade": trade})
                except Exception as e:
                    self._j({"error": str(e)})
        elif p == "/api/portfolio/history":
            try:
                from portfolio_tracker import get_trade_history
                result = get_trade_history()
                self._j(result)
            except Exception as e:
                self._j({"error": str(e)})
        elif p == "/api/portfolio/stats":
            try:
                from portfolio_tracker import get_performance_stats
                result = get_performance_stats()
                self._j(result)
            except Exception as e:
                self._j({"error": str(e)})
        elif p == "/api/portfolio/suggestions":
            try:
                from portfolio_tracker import generate_trading_suggestions
                with open(os.path.join(APP_DIR, 'analysis_data.json')) as f:
                    d = json.load(f)
                prices = {s['code']: s['current_price'] for s in d['sectors'].values()}
                result = generate_trading_suggestions(prices, d)
                self._j(result)
            except Exception as e:
                self._j({"error": str(e)})
        elif p == "/api/professional":
            try:
                with open(os.path.join(APP_DIR, 'analysis_data.json')) as f:
                    d = json.load(f)
                from professional_suggestions import generate_professional_suggestions
                result = generate_professional_suggestions(
                    d['sectors'], d.get('backtest', {}),
                    d.get('cycle_summary', {}), {}, {}
                )
                self._j(result)
            except Exception as e:
                self._j({"error": str(e)})
        elif p == "/api/hot_sectors":
            try:
                with open(os.path.join(APP_DIR, 'analysis_data.json')) as f:
                    d = json.load(f)
                from hot_sector_analysis import analyze_hot_sectors
                result = analyze_hot_sectors(
                    d['sectors'], d.get('backtest', {}),
                    d.get('cycle_summary', {})
                )
                self._j(result)
            except Exception as e:
                self._j({"error": str(e)})
        elif p == "/api/schedule/status":
            try:
                from daily_refresh import get_schedule_status
                result = get_schedule_status()
                self._j(result)
            except Exception as e:
                self._j({"error": str(e)})
        elif p == "/api/schedule/run":
            try:
                from daily_refresh import run_scheduled_task
                threading.Thread(target=run_scheduled_task, daemon=True).start()
                self._j({"status": "started"})
            except Exception as e:
                self._j({"error": str(e)})
        elif p == "/api/schedule/install":
            try:
                from daily_refresh import install_cron
                install_cron()
                self._j({"status": "installed"})
            except Exception as e:
                self._j({"error": str(e)})
        else:
            super().do_GET()
    def _j(self, data):
        c = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(c)))
        self.end_headers()
        self.wfile.write(c)
    def log_message(self, *a): pass


def find_port(start=PORT):
    for p in range(start, start+100):
        with socket.socket() as s:
            if s.connect_ex(("localhost", p)) != 0: return p
    return start


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--no-refresh", action="store_true")
    args = parser.parse_args()

    port = find_port(args.port)
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("", port), AppHandler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.3)

    if not args.no_refresh:
        threading.Thread(target=run_quick_refresh, daemon=True).start()

    window = webview.create_window(
        title="Serenity",
        url=f"http://localhost:{port}",
        width=1440, height=920, min_size=(1000, 600), text_select=True,
    )
    print(f"原生窗口: http://localhost:{port}")
    webview.start()


if __name__ == "__main__":
    main()
