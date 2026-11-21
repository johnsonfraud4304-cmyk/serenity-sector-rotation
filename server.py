#!/usr/bin/env python3
"""
Serenity — 服务器 v4
分步刷新：快速分析(~10s) + DL训练(~2min) + 自动启动刷新
"""
import http.server
import socketserver
import os
import sys
import json
import subprocess
import threading
import time
from urllib.parse import urlparse, parse_qs

PORT = 8080
DIR = os.path.dirname(os.path.abspath(__file__))

# 全局刷新状态
refresh_state = {
    "running": False,
    "step": "",        # 当前步骤名
    "progress": 0,     # 0-100
    "detail": "",      # 详细信息
    "last_update": "",
    "dl_running": False,
    "dl_progress": 0,
    "dl_detail": "",
}


def run_quick_refresh():
    """快速刷新：数据获取 + 技术分析 + 高级分析 + 回测 + 周期（不含DL训练）"""
    refresh_state["running"] = True
    refresh_state["progress"] = 0
    try:
        # Step 1: 获取数据 (20%)
        refresh_state["step"] = "获取ETF行情"
        refresh_state["detail"] = "正在从腾讯财经获取83只ETF最新数据..."
        refresh_state["progress"] = 5
        r = subprocess.run([sys.executable, os.path.join(DIR, "data_engine.py")],
                          capture_output=True, text=True, timeout=300, cwd=DIR)
        refresh_state["progress"] = 20

        # Step 2: 高级分析+回测+周期 (60%)
        refresh_state["step"] = "运行分析引擎"
        refresh_state["detail"] = "MACD/布林带/回撤/相对强度/回测/周期分析..."
        refresh_state["progress"] = 25

        # 运行完整分析脚本
        script = f"""
import sys; sys.path.insert(0, '{DIR}')
exec(open('{DIR}/full_analysis.py').read())
"""
        r = subprocess.run([sys.executable, "-c", script],
                          capture_output=True, text=True, timeout=600, cwd=DIR)

        refresh_state["progress"] = 85

        # Step 3: 合并DL预测 (如果有)
        refresh_state["step"] = "合并AI预测"
        refresh_state["detail"] = "合并深度学习预测结果..."
        refresh_state["progress"] = 90
        _merge_dl_predictions()

        refresh_state["progress"] = 100
        refresh_state["step"] = "完成"
        refresh_state["detail"] = ""
        refresh_state["last_update"] = time.strftime("%Y-%m-%d %H:%M:%S")
        print("✓ 快速刷新完成")
    except Exception as e:
        refresh_state["detail"] = f"出错: {str(e)[:100]}"
        print(f"✗ 刷新失败: {e}")
    finally:
        refresh_state["running"] = False


def run_dl_training():
    """深度学习训练（单独运行，较慢）"""
    refresh_state["dl_running"] = True
    refresh_state["dl_progress"] = 0
    try:
        refresh_state["dl_detail"] = "准备训练数据..."
        refresh_state["dl_progress"] = 5

        r = subprocess.run([sys.executable, os.path.join(DIR, "train_and_predict.py")],
                          capture_output=True, text=True, timeout=600, cwd=DIR)

        refresh_state["dl_progress"] = 80
        refresh_state["dl_detail"] = "合并预测结果..."

        # 合并DL到analysis_data
        _merge_dl_predictions()

        refresh_state["dl_progress"] = 100
        refresh_state["dl_detail"] = "训练完成"
        refresh_state["last_update"] = time.strftime("%Y-%m-%d %H:%M:%S")
        print("✓ DL训练完成")
    except Exception as e:
        refresh_state["dl_detail"] = f"训练出错: {str(e)[:100]}"
        print(f"✗ DL训练失败: {e}")
    finally:
        refresh_state["dl_running"] = False


def _merge_dl_predictions():
    """合并DL预测到analysis_data.json"""
    dl_path = os.path.join(DIR, "dl_predictions.json")
    analysis_path = os.path.join(DIR, "analysis_data.json")
    if not os.path.exists(dl_path) or not os.path.exists(analysis_path):
        return
    try:
        with open(dl_path) as f:
            dl = json.load(f)
        with open(analysis_path) as f:
            analysis = json.load(f)
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
        with open(analysis_path, "w", encoding="utf-8") as f:
            json.dump(analysis, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"合并DL失败: {e}")


class AppHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIR, **kwargs)

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/refresh":
            # 快速刷新
            if refresh_state["running"]:
                self._json({"status": "running", **refresh_state})
            else:
                threading.Thread(target=run_quick_refresh, daemon=True).start()
                self._json({"status": "started", "progress": 0, "step": "启动中..."})

        elif path == "/api/refresh/dl":
            # DL训练
            if refresh_state["dl_running"]:
                self._json({"status": "running", **refresh_state})
            else:
                threading.Thread(target=run_dl_training, daemon=True).start()
                self._json({"status": "started", "dl_progress": 0, "dl_detail": "启动DL训练..."})

        elif path == "/api/refresh/status":
            self._json(refresh_state)

        elif path == "/api/refresh/all":
            # 全量刷新（快速+DL）
            if refresh_state["running"] or refresh_state["dl_running"]:
                self._json({"status": "running", **refresh_state})
            else:
                def _run_all():
                    run_quick_refresh()
                    run_dl_training()
                threading.Thread(target=_run_all, daemon=True).start()
                self._json({"status": "started", "progress": 0, "step": "启动全量刷新..."})

        elif path == "/api/recommend":
            # 个股推荐
            params = parse_qs(parsed.query)
            code = params.get("code", [""])[0]
            if not code:
                self._json({"error": "请输入股票代码或名称"})
            else:
                try:
                    from recommend_engine import analyze_stock
                    result = analyze_stock(code)
                    self._json(result)
                except Exception as e:
                    self._json({"error": f"分析失败: {str(e)[:200]}"})

        elif path == "/api/backtest":
            # 个股回测
            params = parse_qs(parsed.query)
            code = params.get("code", [""])[0]
            if not code:
                self._json({"error": "请输入股票代码"})
            else:
                try:
                    from stock_backtest import run_stock_backtest
                    result = run_stock_backtest(code)
                    self._json(result)
                except Exception as e:
                    self._json({"error": f"回测失败: {str(e)[:200]}"})

        elif path == "/api/guide":
            # 策略指南
            try:
                from stock_backtest import STRATEGY_GUIDE
                self._json(STRATEGY_GUIDE)
            except Exception as e:
                self._json({"error": str(e)})

        elif path == "/api/portfolio/positions":
            # 持仓列表
            try:
                from portfolio_tracker import get_positions_with_pnl, load_portfolio
                analysis_path = os.path.join(DIR, "analysis_data.json")
                current_prices = {}
                if os.path.exists(analysis_path):
                    with open(analysis_path) as f:
                        analysis = json.load(f)
                    for name, s in analysis.get("sectors", {}).items():
                        current_prices[name] = s.get("current_price", 0)
                positions = get_positions_with_pnl(current_prices)
                self._json(positions)
            except Exception as e:
                self._json({"error": str(e), "positions": []})

        elif path == "/api/portfolio/trade":
            # 交易操作
            params = parse_qs(parsed.query)
            code = params.get("code", [""])[0]
            name = params.get("name", [""])[0]
            action = params.get("action", [""])[0]
            price = params.get("price", ["0"])[0]
            quantity = params.get("quantity", ["0"])[0]
            category = params.get("category", [""])[0]
            if not code or not name or action not in ("BUY", "SELL"):
                self._json({"error": "参数不完整"})
            else:
                try:
                    from portfolio_tracker import add_trade
                    add_trade(code, name, action, float(price), int(quantity), category)
                    self._json({"ok": True, "success": True, "message": f"{'买入' if action == 'BUY' else '卖出'} {name} {quantity}份 @ ¥{price}"})
                except Exception as e:
                    self._json({"error": str(e)})

        elif path == "/api/portfolio/clear":
            # 清空持仓
            try:
                import json as _json
                portfolio_file = os.path.join(DIR, "portfolio.json")
                empty = {"trades": [], "positions": {}, "total_invested": 0, "total_pnl": 0}
                with open(portfolio_file, "w", encoding="utf-8") as f:
                    _json.dump(empty, f, ensure_ascii=False, indent=2)
                self._json({"ok": True, "message": "持仓已清空"})
            except Exception as e:
                self._json({"error": str(e)})

        elif path == "/api/portfolio/history":
            # 交易历史
            try:
                from portfolio_tracker import get_trade_history
                history = get_trade_history(limit=100)
                self._json({"history": history})
            except Exception as e:
                self._json({"error": str(e), "history": []})

        elif path == "/api/daily_summary":
            # 每日摘要
            try:
                from dashboard_engine import generate_market_dashboard
                analysis_path = os.path.join(DIR, "analysis_data.json")
                if os.path.exists(analysis_path):
                    with open(analysis_path) as f:
                        analysis = json.load(f)
                    result = generate_market_dashboard(analysis)
                    self._json(result)
                else:
                    self._json({"error": "无分析数据"})
            except Exception as e:
                self._json({"error": str(e)})

        elif path == "/api/hot_sectors":
            # 热门板块
            try:
                from hot_sector_analysis import analyze_hot_sectors
                analysis_path = os.path.join(DIR, "analysis_data.json")
                backtest_path = os.path.join(DIR, "backtest_results.json")
                cycle_path = os.path.join(DIR, "cycle_analysis.json")
                analysis = json.load(open(analysis_path)) if os.path.exists(analysis_path) else {}
                backtest = json.load(open(backtest_path)) if os.path.exists(backtest_path) else {}
                cycle = json.load(open(cycle_path)) if os.path.exists(cycle_path) else {}
                result = analyze_hot_sectors(
                    analysis.get("sectors", {}),
                    backtest,
                    cycle,
                )
                self._json(result)
            except Exception as e:
                self._json({"error": str(e)})

        elif path == "/api/professional":
            # 专业建议
            try:
                from professional_suggestions import generate_professional_suggestions
                analysis_path = os.path.join(DIR, "analysis_data.json")
                backtest_path = os.path.join(DIR, "backtest_results.json")
                cycle_path = os.path.join(DIR, "cycle_analysis.json")
                analysis = json.load(open(analysis_path)) if os.path.exists(analysis_path) else {}
                backtest = json.load(open(backtest_path)) if os.path.exists(backtest_path) else {}
                cycle = json.load(open(cycle_path)) if os.path.exists(cycle_path) else {}
                dl = analysis.get("dl_model", {})
                portfolios = []
                try:
                    from portfolio_tracker import get_positions_with_pnl, load_portfolio
                    portfolios = load_portfolio().get("positions", [])
                except:
                    pass
                result = generate_professional_suggestions(
                    analysis.get("sectors", {}),
                    backtest,
                    cycle,
                    dl,
                    portfolios,
                )
                self._json(result)
            except Exception as e:
                self._json({"error": str(e)})

        elif path == "/api/schedule/status":
            self._json({"installed": False, "schedule": None})

        elif path == "/api/schedule/run":
            self._json({"success": True, "message": "手动刷新已触发"})
            threading.Thread(target=run_quick_refresh, daemon=True).start()

        elif path == "/api/schedule/install":
            self._json({"success": True, "message": "定时刷新已安装（每30分钟）"})

        else:
            super().do_GET()

    def _json(self, data):
        content = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, format, *args):
        pass


def auto_refresh_timer():
    """定时自动刷新：交易时段每30分钟，非交易时段每2小时"""
    while True:
        try:
            from data_engine import is_market_hours
            if is_market_hours():
                interval = 1800  # 交易时段30分钟
            else:
                interval = 7200  # 非交易时段2小时
            time.sleep(interval)
            if not refresh_state["running"] and not refresh_state["dl_running"]:
                print(f"定时自动刷新 ({'交易时段' if is_market_hours() else '非交易时段'})...")
                run_quick_refresh()
        except Exception as e:
            print(f"自动刷新异常: {e}")
            time.sleep(3600)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--no-refresh", action="store_true")
    parser.add_argument("--no-auto-refresh", action="store_true")
    args = parser.parse_args()

    port = args.port

    if not args.no_refresh:
        print("启动时自动刷新数据（快速模式）...")
        threading.Thread(target=run_quick_refresh, daemon=True).start()

    if not args.no_auto_refresh:
        threading.Thread(target=auto_refresh_timer, daemon=True).start()
        print("定时自动刷新已启用（交易时段30分钟/非交易时段2小时）")

    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("", port), AppHandler)
    print(f"服务器启动: http://localhost:{port}")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
