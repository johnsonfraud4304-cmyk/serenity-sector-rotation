#!/usr/bin/env python3
"""
板块/ETF回测引擎
支持多种策略：动量轮动、RSI反转、均线交叉、综合评分
"""

import json, os, math
from datetime import datetime

# ============================================================
# 策略定义
# ============================================================

def strategy_momentum_rotation(lookback=20, hold=5, top_n=2):
    """
    动量轮动策略：每hold天选动量最强的top_n个板块
    """
    def _select(sector_mom, _):
        ranked = sorted(sector_mom.items(), key=lambda x: x[1], reverse=True)
        return [s for s, _ in ranked[:top_n]]
    return {
        'name': f'动量轮动(回看{lookback}天/持有{hold}天/选{top_n}个)',
        'lookback': lookback, 'hold': hold, 'select': _select,
        'params': {'lookback': lookback, 'hold': hold, 'top_n': top_n}
    }

def strategy_rsi_reversal(buy_threshold=30, sell_threshold=70):
    """
    RSI反转策略：RSI<buy_threshold买入，RSI>sell_threshold卖出
    """
    def _select(sector_mom, sector_rsi):
        selected = []
        for name, rsi in sector_rsi.items():
            if rsi < buy_threshold:
                selected.append(name)
        return selected[:3] if selected else []
    return {
        'name': f'RSI反转(买<{buy_threshold}/卖>{sell_threshold})',
        'buy_threshold': buy_threshold, 'sell_threshold': sell_threshold,
        'select': _select,
        'params': {'buy_threshold': buy_threshold, 'sell_threshold': sell_threshold}
    }

def strategy_ma_crossover(fast=5, slow=20):
    """
    均线交叉策略：快线上穿慢线买入，下穿卖出
    """
    def _select(sector_mom, _):
        # 用动量正负代替均线交叉
        selected = [name for name, mom in sector_mom.items() if mom > 0]
        return selected[:3]
    return {
        'name': f'均线交叉(MA{fast}/MA{slow})',
        'fast': fast, 'slow': slow, 'select': _select,
        'params': {'fast': fast, 'slow': slow}
    }

def strategy_combined(mom_weight=0.4, rsi_weight=0.3, vol_weight=0.3):
    """
    综合评分策略：动量+RSI+成交量加权
    """
    def _select(sector_mom, sector_rsi):
        scores = {}
        for name in sector_mom:
            mom_score = max(0, min(100, (sector_mom[name] + 20) * 2.5))
            rsi = sector_rsi.get(name, 50)
            rsi_score = max(0, 100 - abs(rsi - 35) * 2)
            scores[name] = mom_weight * mom_score + rsi_weight * rsi_score
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return [s for s, _ in ranked[:3]]
    return {
        'name': f'综合评分(动量{mom_weight:.0%}+RSI{rsi_weight:.0%}+量{vol_weight:.0%})',
        'select': _select,
        'params': {'mom_weight': mom_weight, 'rsi_weight': rsi_weight, 'vol_weight': vol_weight}
    }

def strategy_value_contrarian(rsi_threshold=25, hold_days=20):
    """
    价值逆向策略：RSI极度超卖时买入，持有固定天数
    """
    def _select(sector_mom, sector_rsi):
        selected = []
        for name, rsi in sector_rsi.items():
            if rsi < rsi_threshold:
                selected.append(name)
        return selected[:2] if selected else []
    return {
        'name': f'价值逆向(RSI<{rsi_threshold}/持有{hold_days}天)',
        'select': _select,
        'params': {'rsi_threshold': rsi_threshold, 'hold_days': hold_days}
    }

ALL_STRATEGIES = [
    lambda: strategy_momentum_rotation(20, 5, 2),
    lambda: strategy_momentum_rotation(40, 20, 2),
    lambda: strategy_rsi_reversal(30, 70),
    lambda: strategy_rsi_reversal(25, 75),
    lambda: strategy_ma_crossover(5, 20),
    lambda: strategy_combined(0.4, 0.3, 0.3),
    lambda: strategy_combined(0.3, 0.5, 0.2),
    lambda: strategy_value_contrarian(25, 20),
    lambda: strategy_value_contrarian(20, 30),
]


# ============================================================
# 回测引擎
# ============================================================

def compute_rsi_series(closes, period=14):
    """计算RSI序列"""
    if len(closes) < period + 1:
        return [50] * len(closes)
    rsi_list = [50] * period
    for i in range(period, len(closes)):
        gains = [max(0, closes[j] - closes[j-1]) for j in range(i-period+1, i+1)]
        losses = [max(0, closes[j-1] - closes[j]) for j in range(i-period+1, i+1)]
        avg_g = sum(gains) / period
        avg_l = sum(losses) / period
        if avg_l == 0:
            rsi_list.append(100)
        else:
            rsi_list.append(100 - 100 / (1 + avg_g / avg_l))
    return rsi_list


def compute_momentum_series(closes, window=20):
    """计算动量序列"""
    mom = [0] * window
    for i in range(window, len(closes)):
        if closes[i-window] > 0:
            mom.append((closes[i] / closes[i-window] - 1) * 100)
        else:
            mom.append(0)
    return mom


def backtest_single_etf(closes, dates, strategy, initial_capital=100000):
    """
    单ETF回测
    
    返回: {
        'total_return': float,  # 总收益率
        'annual_return': float, # 年化收益率
        'max_drawdown': float,  # 最大回撤
        'sharpe_ratio': float,  # 夏普比率
        'win_rate': float,      # 胜率
        'trade_count': int,     # 交易次数
        'equity_curve': list,   # 权益曲线
        'trades': list,         # 交易记录
    }
    """
    n = len(closes)
    if n < 50:
        return None
    
    lookback = strategy.get('lookback', 20)
    hold = strategy.get('hold', 5)
    
    # 计算指标
    rsi_series = compute_rsi_series(closes)
    mom_series = compute_momentum_series(closes, lookback)
    
    # 回测
    capital = initial_capital
    position = 0  # 持仓股数
    entry_price = 0
    equity_curve = [(dates[0], capital)]
    trades = []
    
    i = lookback
    while i < n:
        # 当前指标
        current_mom = {0: mom_series[i]}  # 单ETF用0作为key
        current_rsi = {0: rsi_series[i]}
        
        # 检查是否应该卖出
        if position > 0:
            # 持有hold天后检查
            days_held = 0
            for j in range(max(lookback, i - hold), i):
                days_held += 1
            
            if days_held >= hold:
                # RSI过高或动量转负时卖出
                if rsi_series[i] > 70 or mom_series[i] < -5:
                    sell_price = closes[i]
                    pnl = (sell_price - entry_price) * position
                    capital += position * sell_price
                    trades.append({
                        'type': 'SELL', 'date': dates[i], 'price': sell_price,
                        'pnl': pnl, 'pnl_pct': (sell_price / entry_price - 1) * 100
                    })
                    position = 0
                    entry_price = 0
        
        # 检查是否应该买入
        if position == 0:
            selected = strategy['select'](current_mom, current_rsi)
            if 0 in selected:  # 单ETF key=0
                buy_price = closes[i]
                shares = int(capital * 0.95 / buy_price)
                if shares > 0:
                    position = shares
                    entry_price = buy_price
                    capital -= shares * buy_price
                    trades.append({
                        'type': 'BUY', 'date': dates[i], 'price': buy_price,
                        'shares': shares
                    })
        
        # 更新权益
        equity = capital + position * closes[i]
        equity_curve.append((dates[i], equity))
        i += 1
    
    # 强制平仓
    if position > 0:
        sell_price = closes[-1]
        pnl = (sell_price - entry_price) * position
        capital += position * sell_price
        trades.append({
            'type': 'SELL(平仓)', 'date': dates[-1], 'price': sell_price,
            'pnl': pnl, 'pnl_pct': (sell_price / entry_price - 1) * 100
        })
    
    # 计算指标
    final_equity = equity_curve[-1][1] if equity_curve else capital
    total_return = (final_equity / initial_capital - 1) * 100
    
    # 年化收益
    days = len(closes)
    annual_return = ((final_equity / initial_capital) ** (250 / max(days, 1)) - 1) * 100
    
    # 最大回撤
    peak = initial_capital
    max_dd = 0
    for _, eq in equity_curve:
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak
        if dd > max_dd:
            max_dd = dd
    
    # 夏普比率
    if len(equity_curve) > 1:
        returns = []
        for i in range(1, len(equity_curve)):
            prev_eq = equity_curve[i-1][1]
            if prev_eq > 0:
                returns.append(equity_curve[i][1] / prev_eq - 1)
        if returns:
            avg_ret = sum(returns) / len(returns)
            std_ret = math.sqrt(sum((r - avg_ret)**2 for r in returns) / len(returns))
            sharpe = (avg_ret * 250) / (std_ret * math.sqrt(250)) if std_ret > 0 else 0
        else:
            sharpe = 0
    else:
        sharpe = 0
    
    # 胜率
    sell_trades = [t for t in trades if 'pnl' in t]
    wins = len([t for t in sell_trades if t.get('pnl', 0) > 0])
    win_rate = wins / len(sell_trades) * 100 if sell_trades else 0
    
    return {
        'total_return': round(total_return, 2),
        'annual_return': round(annual_return, 2),
        'max_drawdown': round(max_dd * 100, 2),
        'sharpe_ratio': round(sharpe, 2),
        'win_rate': round(win_rate, 1),
        'trade_count': len(trades),
        'equity_curve': [(d, round(e, 2)) for d, e in equity_curve[-200:]],  # 最近200天
        'trades': trades[-20:],  # 最近20笔交易
    }


def run_backtest(sector_data, strategies=None):
    """
    对所有板块运行多策略回测
    
    sector_data: dict[板块名] -> {'closes': [...], 'dates': [...]}
    """
    if strategies is None:
        strategies = ALL_STRATEGIES
    
    results = {}
    for sector_name, data in sector_data.items():
        closes = data['closes']
        dates = data['dates']
        
        sector_results = []
        for strat_fn in strategies:
            strategy = strat_fn()
            bt = backtest_single_etf(closes, dates, strategy)
            if bt:
                bt['strategy_name'] = strategy['name']
                bt['strategy_params'] = strategy.get('params', {})
                sector_results.append(bt)
        
        results[sector_name] = sector_results
    
    return results


# ============================================================
# 最优策略推荐
# ============================================================

def recommend_strategy(backtest_results):
    """
    为每个板块推荐最优策略
    综合考虑：收益率、夏普比率、胜率、回撤
    """
    recommendations = {}
    
    for sector_name, results in backtest_results.items():
        if not results:
            continue
        
        # 综合评分 = 0.3*收益率排名 + 0.3*夏普排名 + 0.2*胜率排名 + 0.2*(1-回撤排名)
        scored = []
        for r in results:
            score = (
                0.30 * max(0, r['total_return']) / 100 +
                0.30 * max(0, r['sharpe_ratio']) / 3 +
                0.20 * r['win_rate'] / 100 +
                0.20 * max(0, 1 - r['max_drawdown'] / 50)
            )
            scored.append((score, r))
        
        scored.sort(key=lambda x: x[0], reverse=True)
        best = scored[0][1]
        
        recommendations[sector_name] = {
            'best_strategy': best['strategy_name'],
            'total_return': best['total_return'],
            'annual_return': best['annual_return'],
            'max_drawdown': best['max_drawdown'],
            'sharpe_ratio': best['sharpe_ratio'],
            'win_rate': best['win_rate'],
            'trade_count': best['trade_count'],
            'equity_curve': best['equity_curve'],
            'all_strategies': [{
                'name': r['strategy_name'],
                'return': r['total_return'],
                'sharpe': r['sharpe_ratio'],
                'win_rate': r['win_rate'],
                'max_dd': r['max_drawdown'],
            } for r in results]
        }
    
    return recommendations


if __name__ == '__main__':
    print("回测引擎就绪")
    print("可用策略:")
    for fn in ALL_STRATEGIES:
        s = fn()
        print(f"  - {s['name']}")
