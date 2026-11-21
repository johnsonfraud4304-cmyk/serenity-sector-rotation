#!/usr/bin/env python3
"""高级分析引擎 v2 — 止损止盈/仓位管理/宏观指标/组合优化"""
import json, os, math
from datetime import datetime


def compute_stop_loss_levels(closes, rsi, mom_20, ma20, ma60):
    """计算止损止盈价位"""
    price = closes[-1]
    
    # 止损线（基于ATR和支撑位）
    atr = _compute_atr(closes, 14)
    stop_loss = round(price - 2 * atr, 2)
    stop_loss_pct = round((stop_loss / price - 1) * 100, 1)
    
    # 止盈线（基于阻力位和动量）
    if rsi < 30:
        take_profit = round(price * 1.15, 2)  # 超卖反弹目标15%
    elif rsi < 50:
        take_profit = round(price * 1.10, 2)  # 中性目标10%
    else:
        take_profit = round(price * 1.05, 2)  # 已涨目标5%
    take_profit_pct = round((take_profit / price - 1) * 100, 1)
    
    # 移动止损（跟踪止损）
    trail_stop = round(max(stop_loss, price * 0.92), 2)  # 最低8%止损
    
    # 支撑位/阻力位
    recent_low = min(closes[-20:])
    recent_high = max(closes[-20:])
    support = round(recent_low, 2)
    resistance = round(recent_high, 2)
    
    return {
        'stop_loss': stop_loss,
        'stop_loss_pct': stop_loss_pct,
        'take_profit': take_profit,
        'take_profit_pct': take_profit_pct,
        'trail_stop': trail_stop,
        'support': support,
        'resistance': resistance,
        'risk_reward': round(abs(take_profit_pct) / abs(stop_loss_pct), 2) if stop_loss_pct != 0 else 0,
    }


def _compute_atr(closes, period=14):
    """计算ATR（平均真实波幅）"""
    if len(closes) < period + 1:
        return abs(closes[-1] - closes[-2]) if len(closes) > 1 else 0
    true_ranges = []
    for i in range(1, len(closes)):
        tr = max(abs(closes[i] - closes[i-1]),
                 abs(closes[i] - closes[max(0, i-1)]),
                 abs(closes[i-1] - closes[max(0, i-1)]))
        true_ranges.append(tr)
    return sum(true_ranges[-period:]) / period


def compute_position_sizing(total_capital, price, stop_loss_pct, risk_per_trade=0.02):
    """
    仓位管理 — 基于风险的仓位计算
    risk_per_trade: 每笔交易最大亏损占总资金的比例（默认2%）
    """
    if stop_loss_pct >= 0:
        stop_loss_pct = -5  # 默认5%止损
    
    # 计算可承受亏损金额
    max_loss = total_capital * risk_per_trade
    
    # 计算止损距离
    stop_distance = abs(stop_loss_pct) / 100 * price
    
    # 计算仓位
    if stop_distance > 0:
        shares = int(max_loss / stop_distance)
        position_value = shares * price
        position_pct = round(position_value / total_capital * 100, 1)
    else:
        shares = 0
        position_value = 0
        position_pct = 0
    
    return {
        'total_capital': total_capital,
        'risk_per_trade': f'{risk_per_trade*100:.0f}%',
        'max_loss': round(max_loss, 2),
        'position_value': round(position_value, 2),
        'position_pct': position_pct,
        'shares': shares,
        'entry_price': price,
        'stop_loss_price': round(price * (1 + stop_loss_pct/100), 2),
        'take_profit_price': round(price * 1.1, 2),
    }


def compute_portfolio_optimization(sectors, total_capital=100000):
    """
    组合优化 — 基于相关性和风险的最优配置
    """
    # 筛选可投资板块（排除超买和深度套牢的）
    candidates = []
    for name, s in sectors.items():
        cs = s.get('composite_signal', {})
        score = cs.get('score', 0)
        rsi = s.get('rsi', 50)
        dd = s.get('drawdown', {}).get('current_drawdown', 0)
        mom = s.get('mom_20', 0)
        
        # 排除条件
        if rsi > 70:  # 超买
            continue
        if dd > 40:  # 深度套牢
            continue
        if score < -20:  # 综合信号太差
            continue
        
        candidates.append({
            'name': name,
            'score': score,
            'rsi': rsi,
            'mom_20': mom,
            'drawdown': dd,
            'category': s.get('category', ''),
            'color': s.get('color', '#666'),
        })
    
    # 按综合评分排序
    candidates.sort(key=lambda x: x['score'], reverse=True)
    
    # 选取Top 10
    top = candidates[:10]
    
    # 风险平价权重（基于RSI和动量的反向加权）
    total_weight = 0
    for c in top:
        # RSI越低权重越高（超卖机会）
        rsi_weight = max(0, (50 - c['rsi']) / 50)
        # 动量反转加分
        mom_weight = max(0, (5 - abs(c['mom_20'])) / 5)
        c['raw_weight'] = (rsi_weight + mom_weight + max(0, c['score']/100)) / 3
        total_weight += c['raw_weight']
    
    if total_weight > 0:
        for c in top:
            c['weight'] = round(c['raw_weight'] / total_weight * 100, 1)
            c['amount'] = round(total_capital * c['weight'] / 100, 0)
    
    # 计算预期风险指标
    avg_rsi = sum(c['rsi'] for c in top) / len(top) if top else 50
    avg_mom = sum(c['mom_20'] for c in top) / len(top) if top else 0
    max_position = max(c['weight'] for c in top) if top else 0
    
    return {
        'total_capital': total_capital,
        'candidates_count': len(candidates),
        'selected_count': len(top),
        'allocations': top,
        'avg_rsi': round(avg_rsi, 1),
        'avg_momentum': round(avg_mom, 2),
        'max_single_position': max_position,
        'diversification': '高' if len(set(c['category'] for c in top)) >= 4 else '中' if len(set(c['category'] for c in top)) >= 2 else '低',
    }


def compute_backtest_with_costs(closes, dates, strategy_func, commission=0.001, slippage=0.001):
    """
    带交易成本的回测
    commission: 佣金率（默认0.1%）
    slippage: 滑点（默认0.1%）
    """
    initial_capital = 100000
    capital = initial_capital
    position = 0
    entry_price = 0
    trades = []
    equity_curve = []
    
    for i in range(60, len(closes)):
        price = closes[i]
        signal = strategy_func(closes[:i+1], i)
        
        if signal == 'BUY' and position == 0:
            # 买入（扣成本）
            cost = price * commission + price * slippage
            shares = int(capital / (price + cost))
            if shares > 0:
                entry_price = price + cost
                position = shares
                capital -= shares * entry_price
                trades.append({'date': dates[i], 'action': 'BUY', 'price': price, 'shares': shares})
        
        elif signal == 'SELL' and position > 0:
            # 卖出（扣成本）
            sell_price = price - price * slippage - price * commission
            capital += position * sell_price
            pnl = (sell_price - entry_price) / entry_price * 100
            trades.append({'date': dates[i], 'action': 'SELL', 'price': price, 'pnl': round(pnl, 2)})
            position = 0
        
        # 记录净值
        equity = capital + position * price
        equity_curve.append({'date': dates[i], 'equity': round(equity, 2)})
    
    # 最终净值
    final_equity = capital + position * closes[-1]
    total_return = (final_equity / initial_capital - 1) * 100
    
    # 计算最大回撤
    max_eq = initial_capital
    max_dd = 0
    for pt in equity_curve:
        if pt['equity'] > max_eq:
            max_eq = pt['equity']
        dd = (max_eq - pt['equity']) / max_eq * 100
        if dd > max_dd:
            max_dd = dd
    
    return {
        'initial_capital': initial_capital,
        'final_equity': round(final_equity, 2),
        'total_return': round(total_return, 2),
        'total_trades': len(trades),
        'max_drawdown': round(max_dd, 2),
        'equity_curve': equity_curve[-100:],  # 最近100个点
        'trades': trades[-20:],  # 最近20笔交易
        'costs_applied': f'佣金{commission*100}% + 滑点{slippage*100}%',
    }


def compute_daily_summary(sectors, portfolios, bt_results):
    """生成每日摘要"""
    # 统计
    total = len(sectors)
    oversold = sum(1 for s in sectors.values() if s.get('rsi', 50) < 30)
    overbought = sum(1 for s in sectors.values() if s.get('rsi', 50) > 70)
    rising = sum(1 for s in sectors.values() if s.get('mom_20', 0) > 0)
    falling = sum(1 for s in sectors.values() if s.get('mom_20', 0) < 0)
    avg_rsi = sum(s.get('rsi', 50) for s in sectors.values()) / total
    avg_mom = sum(s.get('mom_20', 0) for s in sectors.values()) / total
    
    # 情绪判断
    if oversold > 5:
        mood = '极度恐慌（逆向买入机会）'
        mood_color = '#22c55e'
    elif oversold > 2:
        mood = '恐慌（关注超卖板块）'
        mood_color = '#f59e0b'
    elif overbought > 5:
        mood = '极度贪婪（注意风险）'
        mood_color = '#ef4444'
    elif overbought > 2:
        mood = '贪婪（谨慎追高）'
        mood_color = '#f97316'
    else:
        mood = '中性'
        mood_color = '#9ca3af'
    
    # 操作建议
    suggestions = []
    if oversold > 3:
        suggestions.append(f'🟢 {oversold}个板块超卖，可分批建仓')
    if overbought > 3:
        suggestions.append(f'🔴 {overbought}个板块超买，注意止盈')
    if avg_rsi < 35:
        suggestions.append('📊 整体超卖，市场恐慌中，逆向布局机会')
    elif avg_rsi > 65:
        suggestions.append('📊 整体超买，市场过热，控制仓位')
    if avg_mom < -5:
        suggestions.append('📉 短期动量转负，等待企稳信号')
    elif avg_mom > 5:
        suggestions.append('📈 短期动量强劲，趋势跟踪策略')
    
    return {
        'date': datetime.now().strftime('%Y-%m-%d'),
        'mood': mood,
        'mood_color': mood_color,
        'stats': {
            'total': total,
            'oversold': oversold,
            'overbought': overbought,
            'rising': rising,
            'falling': falling,
            'avg_rsi': round(avg_rsi, 1),
            'avg_momentum': round(avg_mom, 2),
        },
        'suggestions': suggestions,
    }


if __name__ == '__main__':
    # 测试
    with open('analysis_data.json') as f:
        d = json.load(f)
    
    sectors = d['sectors']
    
    # 测试止损止盈
    s = sectors.get('医疗', {})
    closes = s.get('closes', [10, 11, 12, 11, 10, 9, 8, 9, 10, 11])
    if len(closes) < 2:
        closes = [100, 101, 102, 101, 100, 99, 98, 99, 100, 101]
    levels = compute_stop_loss_levels(closes, s.get('rsi', 50), s.get('mom_20', 0), 0, 0)
    print(f"止损止盈: {levels}")
    
    # 测试仓位管理
    position = compute_position_sizing(100000, 1.0, -5)
    print(f"仓位管理: {position}")
    
    # 测试组合优化
    portfolio = compute_portfolio_optimization(sectors, 100000)
    print(f"组合优化: {len(portfolio['allocations'])} 板块")
    
    # 测试每日摘要
    summary = compute_daily_summary(sectors, portfolio, {})
    print(f"每日摘要: {summary['mood']}")
