#!/usr/bin/env python3
"""个股推荐引擎 — 多指标综合评分，给出买入/持有/卖出/观望概率"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from stock_backtest import fetch_stock_kline, _search_stock_tencent
from data_engine import compute_rsi, rolling_momentum, compute_returns, compute_ma
from advanced_analysis import compute_macd, compute_bollinger, compute_drawdown_analysis, compute_ema


def analyze_stock(code_or_name):
    """分析单只股票/ETF，返回推荐结果"""
    # 获取数据
    data, full_code = fetch_stock_kline(code_or_name, count=500)
    if not data or len(data['closes']) < 60:
        return {"error": f"无法获取 {code_or_name} 的数据，请检查代码是否正确"}
    
    closes = data['closes']
    dates = data['dates']
    n = len(closes)
    
    # 计算所有指标
    rets = compute_returns(closes)
    rsi = compute_rsi(closes)
    
    mom20_list = rolling_momentum(rets, 20)
    mom60_list = rolling_momentum(rets, 60)
    mom5_list = rolling_momentum(rets, 5)
    cur_mom20 = mom20_list[-1] if mom20_list else 0
    cur_mom60 = mom60_list[-1] if mom60_list else 0
    cur_mom5 = mom5_list[-1] if mom5_list else 0
    
    macd = compute_macd(closes)
    bb = compute_bollinger(closes)
    dd = compute_drawdown_analysis(closes)
    
    ma5 = compute_ma(closes, 5)
    ma20 = compute_ma(closes, 20)
    ma60 = compute_ma(closes, 60)
    
    # 趋势判断
    above_ma5 = closes[-1] > ma5
    above_ma20 = closes[-1] > ma20
    above_ma60 = closes[-1] > ma60
    ma5_up = ma5 > compute_ma(closes[:-1], 5) if n > 6 else True
    ma20_up = ma20 > compute_ma(closes[:-1], 20) if n > 21 else True
    
    # ====== 多维度评分 ======
    buy_score = 0
    sell_score = 0
    hold_score = 0
    watch_score = 0
    reasons = []
    
    # 1. RSI (权重25)
    if rsi < 25:
        buy_score += 25
        reasons.append(("RSI极度超卖", "buy", 25))
    elif rsi < 30:
        buy_score += 20
        reasons.append(("RSI超卖", "buy", 20))
    elif rsi < 40:
        buy_score += 10
        reasons.append(("RSI偏低", "buy", 10))
    elif rsi > 80:
        sell_score += 25
        reasons.append(("RSI极度超买", "sell", 25))
    elif rsi > 70:
        sell_score += 20
        reasons.append(("RSI超买", "sell", 20))
    elif rsi > 60:
        sell_score += 5
        reasons.append(("RSI偏高", "sell", 5))
    else:
        hold_score += 5
        reasons.append(("RSI中性", "hold", 5))
    
    # 2. 动量 (权重20)
    if cur_mom20 > 5 and cur_mom60 > 10:
        buy_score += 15
        reasons.append(("强势上涨趋势", "buy", 15))
    elif cur_mom20 > 0 and cur_mom60 > 0:
        buy_score += 10
        reasons.append(("上升趋势", "buy", 10))
    elif cur_mom20 > 0 and cur_mom60 < 0:
        buy_score += 5
        reasons.append(("短期反弹", "buy", 5))
    elif cur_mom20 < -10 and cur_mom60 < -15:
        sell_score += 15
        reasons.append(("持续下跌", "sell", 15))
    elif cur_mom20 < 0 and cur_mom60 < 0:
        sell_score += 10
        reasons.append(("下降趋势", "sell", 10))
    else:
        hold_score += 5
        reasons.append(("趋势不明", "hold", 5))
    
    # 3. MACD (权重20)
    if macd.get('golden_cross'):
        buy_score += 20
        reasons.append(("MACD金叉", "buy", 20))
    elif macd.get('hist', 0) > 0 and macd.get('hist', 0) > macd.get('hist', 0) * 0.8:
        buy_score += 10
        reasons.append(("MACD柱线扩大", "buy", 10))
    elif macd.get('dead_cross'):
        sell_score += 20
        reasons.append(("MACD死叉", "sell", 20))
    elif macd.get('hist', 0) < 0:
        sell_score += 8
        reasons.append(("MACD柱线为负", "sell", 8))
    else:
        hold_score += 5
    
    # 4. 布林带 (权重15)
    bb_pos = bb.get('position', 0.5)
    if bb_pos < 0.1:
        buy_score += 15
        reasons.append(("触及布林带下轨", "buy", 15))
    elif bb_pos < 0.2:
        buy_score += 10
        reasons.append(("接近布林带下轨", "buy", 10))
    elif bb_pos > 0.9:
        sell_score += 15
        reasons.append(("触及布林带上轨", "sell", 15))
    elif bb_pos > 0.8:
        sell_score += 10
        reasons.append(("接近布林带上轨", "sell", 10))
    else:
        hold_score += 3
    
    if bb.get('squeeze'):
        watch_score += 5
        reasons.append(("布林带收窄，即将变盘", "watch", 5))
    
    # 5. 均线系统 (权重10)
    if above_ma5 and above_ma20 and above_ma60:
        buy_score += 8
        reasons.append(("站上所有均线", "buy", 8))
    elif above_ma5 and above_ma20:
        buy_score += 5
        reasons.append(("站上MA5和MA20", "buy", 5))
    elif not above_ma5 and not above_ma20 and not above_ma60:
        sell_score += 8
        reasons.append(("跌破所有均线", "sell", 8))
    elif not above_ma5 and not above_ma20:
        sell_score += 5
        reasons.append(("跌破MA5和MA20", "sell", 5))
    else:
        hold_score += 3
    
    # 6. 回撤 (权重10)
    cur_dd = dd.get('current_drawdown', 0)
    max_dd = dd.get('max_drawdown', 0)
    if cur_dd < 5 and max_dd > 20:
        buy_score += 8
        reasons.append(("从大幅回撤中恢复", "buy", 8))
    elif cur_dd > max_dd * 0.8:
        sell_score += 8
        reasons.append(("接近历史最大回撤", "sell", 8))
    elif cur_dd > max_dd * 0.5:
        watch_score += 5
        reasons.append(("回撤较深，观望", "watch", 5))
    
    # 7. 动量加速 (权重5)
    if cur_mom5 > 0 and cur_mom20 < 0:
        buy_score += 5
        reasons.append(("短期动量转正", "buy", 5))
    elif cur_mom5 < 0 and cur_mom20 > 0:
        sell_score += 5
        reasons.append(("短期动量转负", "sell", 5))
    
    # 归一化为概率
    total = buy_score + sell_score + hold_score + watch_score
    if total == 0:
        total = 1
    
    buy_prob = round(buy_score / total * 100)
    sell_prob = round(sell_score / total * 100)
    hold_prob = round(hold_score / total * 100)
    watch_prob = 100 - buy_prob - sell_prob - hold_prob
    
    # 确保概率合理
    if watch_prob < 0:
        watch_prob = 0
        remaining = 100 - buy_prob - sell_prob - hold_prob
        if remaining > 0:
            watch_prob = remaining
    
    # 综合建议
    if buy_prob >= 50:
        recommendation = "强烈建议买入"
        rec_color = "#22c55e"
        rec_detail = "多项指标共振看多，可分批建仓"
    elif buy_prob >= 35:
        recommendation = "建议买入"
        rec_color = "#4ade80"
        rec_detail = "指标偏多，可轻仓试探"
    elif sell_prob >= 50:
        recommendation = "强烈建议卖出"
        rec_color = "#ef4444"
        rec_detail = "多项指标看空，建议减仓或清仓"
    elif sell_prob >= 35:
        recommendation = "建议卖出"
        rec_color = "#f87171"
        rec_detail = "指标偏空，建议减仓"
    elif hold_prob >= 40:
        recommendation = "建议持有观望"
        rec_color = "#f59e0b"
        rec_detail = "指标中性，维持当前仓位"
    else:
        recommendation = "暂不操作"
        rec_color = "#9ca3af"
        rec_detail = "信号不明确，等待更清晰的方向"
    
    # 获取股票名称
    stock_name = code_or_name
    if full_code.startswith('sh'):
        stock_name = full_code[2:]
    elif full_code.startswith('sz'):
        stock_name = full_code[2:]
    
    # 从反查表获取名称
    try:
        from stock_backtest import STOCK_NAME_MAP
        reverse_map = {v: k for k, v in STOCK_NAME_MAP.items()}
        pure = full_code.replace('sh', '').replace('sz', '')
        if pure in reverse_map:
            stock_name = reverse_map[pure]
    except:
        pass
    
    return {
        "stock_name": stock_name,
        "stock_code": full_code,
        "current_price": round(closes[-1], 2),
        "_closes": closes[-30:],
        "rsi": round(rsi, 1),
        "mom_5": round(cur_mom5, 2),
        "mom_20": round(cur_mom20, 2),
        "mom_60": round(cur_mom60, 2),
        "macd_hist": round(macd.get('hist', 0), 4),
        "macd_signal": "金叉" if macd.get('golden_cross') else "死叉" if macd.get('dead_cross') else "柱正" if macd.get('hist', 0) > 0 else "柱负",
        "bb_position": round(bb_pos, 3),
        "bb_squeeze": bb.get('squeeze', False),
        "max_drawdown": round(max_dd, 1),
        "current_drawdown": round(cur_dd, 1),
        "above_ma5": above_ma5,
        "above_ma20": above_ma20,
        "above_ma60": above_ma60,
        "recommendation": recommendation,
        "rec_color": rec_color,
        "rec_detail": rec_detail,
        "probabilities": {
            "buy": buy_prob,
            "hold": hold_prob,
            "sell": sell_prob,
            "watch": watch_prob,
        },
        "reasons": sorted(reasons, key=lambda x: x[2], reverse=True),
        "data_range": f"{dates[0]} ~ {dates[-1]}",
        "data_points": n,
    }


if __name__ == '__main__':
    import sys
    code = sys.argv[1] if len(sys.argv) > 1 else '600519'
    result = analyze_stock(code)
    if 'error' in result:
        print(f"错误: {result['error']}")
    else:
        print(f"\n{'='*50}")
        print(f"  {result['stock_name']} ({result['stock_code']})")
        print(f"  现价: ¥{result['current_price']}  RSI: {result['rsi']}")
        print(f"{'='*50}")
        print(f"\n📊 操作建议: {result['recommendation']}")
        print(f"   {result['rec_detail']}")
        print(f"\n📈 概率分布:")
        p = result['probabilities']
        print(f"   买入: {p['buy']}%  持有: {p['hold']}%  卖出: {p['sell']}%  观望: {p['watch']}%")
        print(f"\n📋 关键因子:")
        for reason, direction, score in result['reasons'][:8]:
            icon = "🟢" if direction == "buy" else "🔴" if direction == "sell" else "🟡" if direction == "hold" else "⚪"
            print(f"   {icon} {reason} ({score}分)")
