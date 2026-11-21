#!/usr/bin/env python3
"""持仓管理引擎 — 交易记录/实时盈亏/收益统计/操作建议"""
import json, os
from datetime import datetime

PORTFOLIO_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'portfolio.json')


def load_portfolio():
    """加载持仓数据"""
    if os.path.exists(PORTFOLIO_FILE):
        with open(PORTFOLIO_FILE) as f:
            return json.load(f)
    return {"trades": [], "positions": {}, "total_invested": 0, "total_pnl": 0}


def save_portfolio(portfolio):
    """保存持仓数据"""
    with open(PORTFOLIO_FILE, 'w', encoding='utf-8') as f:
        json.dump(portfolio, f, ensure_ascii=False, indent=2)


def add_trade(code, name, action, price, quantity, category=''):
    """添加交易记录
    action: 'BUY' 或 'SELL'
    """
    portfolio = load_portfolio()
    
    trade = {
        'id': len(portfolio['trades']) + 1,
        'date': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'code': code,
        'name': name,
        'action': action,
        'price': float(price),
        'quantity': int(quantity),
        'amount': round(float(price) * int(quantity), 2),
        'category': category,
    }
    portfolio['trades'].append(trade)
    
    # 更新持仓
    key = f"{code}_{name}"
    if action == 'BUY':
        if key in portfolio['positions']:
            pos = portfolio['positions'][key]
            # 加权平均成本
            total_cost = pos['avg_cost'] * pos['quantity'] + float(price) * int(quantity)
            pos['quantity'] += int(quantity)
            pos['avg_cost'] = round(total_cost / pos['quantity'], 4)
        else:
            portfolio['positions'][key] = {
                'code': code,
                'name': name,
                'category': category,
                'quantity': int(quantity),
                'avg_cost': float(price),
                'buy_date': trade['date'],
            }
    elif action == 'SELL':
        if key in portfolio['positions']:
            pos = portfolio['positions'][key]
            pos['quantity'] -= int(quantity)
            if pos['quantity'] <= 0:
                del portfolio['positions'][key]
    
    # 计算总投入
    portfolio['total_invested'] = sum(
        t['amount'] if t['action'] == 'BUY' else -t['amount']
        for t in portfolio['trades']
    )
    
    save_portfolio(portfolio)
    return trade


def get_positions_with_pnl(current_prices):
    """获取带实时盈亏的持仓"""
    portfolio = load_portfolio()
    positions = portfolio.get('positions', {})
    
    result = []
    total_cost = 0
    total_value = 0
    total_pnl = 0
    
    for key, pos in positions.items():
        code = pos['code']
        name = pos['name']
        qty = pos['quantity']
        avg_cost = pos['avg_cost']
        
        # 获取当前价格
        current_price = current_prices.get(code, avg_cost)
        
        # 计算盈亏
        cost = avg_cost * qty
        value = current_price * qty
        pnl = value - cost
        pnl_pct = (current_price / avg_cost - 1) * 100 if avg_cost > 0 else 0
        
        total_cost += cost
        total_value += value
        total_pnl += pnl
        
        # 持仓天数
        buy_date = pos.get('buy_date', '')
        hold_days = 0
        if buy_date:
            try:
                buy_dt = datetime.strptime(buy_date, '%Y-%m-%d %H:%M')
                hold_days = (datetime.now() - buy_dt).days
            except:
                pass
        
        result.append({
            'code': code,
            'name': name,
            'category': pos.get('category', ''),
            'quantity': qty,
            'avg_cost': round(avg_cost, 4),
            'current_price': round(current_price, 4),
            'cost': round(cost, 2),
            'value': round(value, 2),
            'pnl': round(pnl, 2),
            'pnl_pct': round(pnl_pct, 2),
            'hold_days': hold_days,
            'buy_date': buy_date,
        })
    
    # 按盈亏排序
    result.sort(key=lambda x: x['pnl'], reverse=True)
    
    return {
        'positions': result,
        'summary': {
            'total_cost': round(total_cost, 2),
            'total_value': round(total_value, 2),
            'total_pnl': round(total_pnl, 2),
            'total_pnl_pct': round((total_value / total_cost - 1) * 100, 2) if total_cost > 0 else 0,
            'position_count': len(result),
            'winning': sum(1 for p in result if p['pnl'] > 0),
            'losing': sum(1 for p in result if p['pnl'] < 0),
        }
    }


def get_trade_history(limit=50):
    """获取交易历史"""
    portfolio = load_portfolio()
    trades = portfolio.get('trades', [])
    return trades[-limit:][::-1]  # 最新在前


def get_performance_stats():
    """获取绩效统计"""
    portfolio = load_portfolio()
    trades = portfolio.get('trades', [])
    
    if not trades:
        return {'total_trades': 0, 'win_rate': 0, 'total_pnl': 0}
    
    # 统计已完成的交易（有买有卖）
    buys = {}
    completed = []
    for t in trades:
        key = f"{t['code']}_{t['name']}"
        if t['action'] == 'BUY':
            buys[key] = t
        elif t['action'] == 'SELL' and key in buys:
            buy = buys[key]
            pnl = (t['price'] - buy['price']) / buy['price'] * 100
            completed.append({
                'name': t['name'],
                'buy_price': buy['price'],
                'sell_price': t['price'],
                'pnl_pct': round(pnl, 2),
                'hold_days': (datetime.strptime(t['date'], '%Y-%m-%d %H:%M') - 
                             datetime.strptime(buy['date'], '%Y-%m-%d %H:%M')).days,
            })
    
    total_trades = len(completed)
    wins = sum(1 for t in completed if t['pnl_pct'] > 0)
    win_rate = round(wins / total_trades * 100, 1) if total_trades > 0 else 0
    avg_pnl = sum(t['pnl_pct'] for t in completed) / total_trades if total_trades > 0 else 0
    avg_hold = sum(t['hold_days'] for t in completed) / total_trades if total_trades > 0 else 0
    
    return {
        'total_trades': total_trades,
        'wins': wins,
        'losses': total_trades - wins,
        'win_rate': win_rate,
        'avg_pnl': round(avg_pnl, 2),
        'avg_hold_days': round(avg_hold, 1),
        'completed': completed[-10:],  # 最近10笔
    }


def generate_trading_suggestions(current_prices, analysis_data):
    """基于持仓和市场状态生成操作建议"""
    portfolio = load_portfolio()
    positions = portfolio.get('positions', {})
    sectors = analysis_data.get('sectors', {})
    
    suggestions = []
    
    for key, pos in positions.items():
        code = pos['code']
        name = pos['name']
        avg_cost = pos['avg_cost']
        qty = pos['quantity']
        current_price = current_prices.get(code, avg_cost)
        
        # 查找对应的板块分析数据
        sector_data = None
        for sname, s in sectors.items():
            if s.get('code') == code or sname == name:
                sector_data = s
                break
        
        if not sector_data:
            continue
        
        rsi = sector_data.get('rsi', 50)
        mom_20 = sector_data.get('mom_20', 0)
        phase = sector_data.get('phase', '')
        action = sector_data.get('action', '')
        cs = sector_data.get('composite_signal', {})
        score = cs.get('score', 0)
        sl = sector_data.get('stop_loss', {})
        pnl_pct = (current_price / avg_cost - 1) * 100 if avg_cost > 0 else 0
        
        # 止损检查
        if sl and current_price <= sl.get('stop_loss', 0):
            suggestions.append({
                'type': 'STOP_LOSS',
                'name': name,
                'code': code,
                'urgency': '紧急',
                'reason': f'触及止损位 ¥{sl["stop_loss"]}，当前 ¥{current_price}，建议立即卖出',
                'action': '卖出全部',
                'color': '#ef4444',
            })
        
        # 止盈检查
        elif sl and current_price >= sl.get('take_profit', float('inf')):
            suggestions.append({
                'type': 'TAKE_PROFIT',
                'name': name,
                'code': code,
                'urgency': '建议',
                'reason': f'达到止盈位 ¥{sl["take_profit"]}，当前 ¥{current_price}，建议分批止盈',
                'action': '卖出50%',
                'color': '#22c55e',
            })
        
        # 亏损持仓检查
        elif pnl_pct < -10:
            suggestions.append({
                'type': 'LOSS_WARNING',
                'name': name,
                'code': code,
                'urgency': '关注',
                'reason': f'浮亏 {pnl_pct:.1f}%，RSI={rsi:.0f}，建议{("补仓摊低成本" if rsi < 30 else "观望等待")}',
                'action': '补仓或观望',
                'color': '#f59e0b',
            })
        
        # RSI超卖提醒（可加仓）
        elif rsi < 25 and pnl_pct > -5:
            suggestions.append({
                'type': 'ADD_POSITION',
                'name': name,
                'code': code,
                'urgency': '机会',
                'reason': f'RSI={rsi:.0f}极度超卖，当前浮盈{pnl_pct:.1f}%，可考虑加仓',
                'action': '加仓',
                'color': '#22c55e',
            })
        
        # RSI超买提醒（可减仓）
        elif rsi > 70 and pnl_pct > 10:
            suggestions.append({
                'type': 'REDUCE',
                'name': name,
                'code': code,
                'urgency': '建议',
                'reason': f'RSI={rsi:.0f}超买+浮盈{pnl_pct:.1f}%，建议减仓锁利',
                'action': '减仓30%',
                'color': '#f59e0b',
            })
        
        # 趋势转弱提醒
        elif phase == '下降期' and pnl_pct > 0:
            suggestions.append({
                'type': 'TREND_WEAK',
                'name': name,
                'code': code,
                'urgency': '关注',
                'reason': f'进入下降期，当前浮盈{pnl_pct:.1f}%，建议设置移动止损',
                'action': '设移动止损',
                'color': '#f97316',
            })
    
    # 按紧急程度排序
    urgency_order = {'紧急': 0, '建议': 1, '机会': 2, '关注': 3}
    suggestions.sort(key=lambda x: urgency_order.get(x['urgency'], 99))
    
    return suggestions


if __name__ == '__main__':
    # 测试
    trade = add_trade('sh512400', '有色', 'BUY', 1.93, 1000, '周期')
    print(f"添加交易: {trade}")
    
    positions = get_positions_with_pnl({'sh512400': 1.95})
    print(f"持仓: {positions['summary']}")
    
    history = get_trade_history()
    print(f"交易历史: {len(history)} 笔")
    
    stats = get_performance_stats()
    print(f"绩效: 胜率={stats['win_rate']}%")
