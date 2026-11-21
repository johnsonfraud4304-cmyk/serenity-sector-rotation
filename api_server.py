#!/usr/bin/env python3
"""
个股回测API服务器
在8081端口运行，接收前端请求，返回回测结果JSON
"""

import http.server
import json, os, sys
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(__file__))
from stock_backtest import run_stock_backtest

class BacktestHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        
        if parsed.path == '/api/backtest':
            params = parse_qs(parsed.query)
            code = params.get('code', [''])[0]
            
            if not code:
                self.send_json({'error': '请输入股票代码或名称'}, 400)
                return
            
            result = run_stock_backtest(code)
            self.send_json(result)
        
        elif parsed.path == '/api/guide':
            from stock_backtest import STRATEGY_GUIDE
            self.send_json(STRATEGY_GUIDE)
        
        else:
            self.send_json({'error': '未知接口'}, 404)
    
    def send_json(self, data, status=200):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))
    
    def log_message(self, *args):
        pass

if __name__ == '__main__':
    PORT = 8081
    with http.server.HTTPServer(('', PORT), BacktestHandler) as httpd:
        print(f'个股回测API运行在 http://localhost:{PORT}')
        httpd.serve_forever()
