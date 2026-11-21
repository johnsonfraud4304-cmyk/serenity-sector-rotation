#!/usr/bin/env python3
"""热门板块深度分析引擎 — 自动识别热门板块并给出深度解读"""
import json, os

DIR = os.path.dirname(os.path.abspath(__file__))


def analyze_hot_sectors(sectors, backtest_data, cycle_data):
    """分析热门板块，生成深度解读"""
    hot_sectors = []
    for name, s in sectors.items():
        mom20 = s.get('mom_20', 0)
        mom60 = s.get('mom_60', 0)
        rsi = s.get('rsi', 50)
        cs = s.get('composite_signal', {})
        score = cs.get('score', 0)
        bb = s.get('bollinger', {})
        macd = s.get('macd', {})
        dd = s.get('drawdown', {})
        rs = s.get('relative_strength', {})
        cycle = cycle_data.get(name, {})
        bt = backtest_data.get('recommendations', {}).get(name, {})
        heat_score = 0
        if mom20 > 3: heat_score += 20
        elif mom20 > 0: heat_score += 10
        if mom60 > 10: heat_score += 15
        elif mom60 > 0: heat_score += 5
        if 50 < rsi < 70: heat_score += 10
        if score > 0: heat_score += 10
        if bb.get('position', 0.5) > 0.5: heat_score += 5
        is_hot = heat_score >= 30 or mom20 > 5
        if not is_hot:
            continue
        reasons = []
        if macd.get('golden_cross'): reasons.append('MACD金叉')
        elif macd.get('hist', 0) > 0: reasons.append('MACD柱线扩大')
        if bb.get('position', 0.5) > 0.7: reasons.append('突破布林上轨')
        if rs.get('rs_20d', 0) > 3: reasons.append('跑赢大盘')
        if mom60 > 20: reasons.append('中期趋势强劲')
        if cycle.get('phase') == '底部上升': reasons.append('周期底部反弹')
        if bt.get('sharpe_ratio', 0) > 1: reasons.append('回测优秀')
        if not reasons: reasons.append('技术面共振')
        risks = []
        if rsi > 60: risks.append(f'RSI={rsi:.0f}偏高')
        if bb.get('position', 0.5) > 0.8: risks.append('接近布林上轨')
        if mom20 > 10: risks.append('短期涨幅过大')
        sustainability = '趋势健康' if mom20 > 0 and mom60 > 0 and rsi < 60 else '趋势延续但偏高' if rsi > 60 else '短期反弹' if mom20 > 0 else '趋势不明'
        sustain_color = '#22c55e' if '健康' in sustainability else '#f59e0b' if '延续' in sustainability or '反弹' in sustainability else '#ef4444'
        action = '追涨买入' if rsi < 40 and mom20 > 0 else '持有观望' if rsi > 60 else '分批止盈' if rsi > 70 else '等待信号'
        action_color = '#22c55e' if '买入' in action else '#f59e0b' if '观望' in action or '止盈' in action else '#9ca3af'
        price = s.get('current_price', 0)
        closes = []
        cache_file = os.path.join(DIR, 'etf_cache', f'{s.get("code","")}.json')
        if os.path.exists(cache_file):
            try:
                with open(cache_file) as f: klines = json.load(f)
                closes = [float(k[2]) for k in klines if len(k) >= 3 and float(k[2]) > 0]
            except: pass
        if not closes: closes = [price] * 20
        atr = _atr(closes, 14)
        entry_low = round(price * 0.97, 3) if rsi < 40 else round(price * 0.95, 3)
        entry_high = round(price * 1.02, 3)
        stop_loss = round(max(price - 2 * atr, min(closes[-20:]) * 0.98) if len(closes) >= 20 else price - 2 * atr, 3)
        stop_loss_pct = round((stop_loss / price - 1) * 100, 1)
        tp1, tp2, tp3 = round(price * 1.08, 3), round(price * 1.15, 3), round(price * 1.25, 3)
        trail_stop = round(max(stop_loss, price * 0.93), 3)
        risk = price - stop_loss
        rr = round((tp1 - price) / risk, 2) if risk > 0 else 0
        shares = int(2000 / (price - stop_loss)) if price > stop_loss else 0
        position_pct = round(shares * price / 100000 * 100, 1)
        steps = []
        if '买入' in action:
            steps = [f'在¥{entry_low}-¥{entry_high}区间挂单', f'首批50%仓位，RSI<30时加至80%', f'止损¥{stop_loss}(-{abs(stop_loss_pct)}%)', f'止盈T1=¥{tp1} T2=¥{tp2} T3=¥{tp3}', f'移动止损¥{trail_stop}']
        elif '观望' in action or '等待' in action:
            steps = [f'设移动止损¥{trail_stop}', f'等RSI回到30以下或MACD金叉再介入', f'关注¥{entry_low}支撑位']
        elif '止盈' in action:
            steps = [f'分批卖出：T1=¥{tp1}卖30% T2=¥{tp2}卖30%', f'剩余设移动止损¥{trail_stop}']
        else:
            steps = [f'当前价位¥{price}，关注¥{entry_low}支撑', f'止损¥{stop_loss}，止盈¥{tp1}/¥{tp2}']
        hot_sectors.append({
            'name': name, 'code': s.get('code', ''), 'category': s.get('category', ''),
            'price': price, 'mom20': mom20, 'mom60': mom60, 'rsi': rsi,
            'phase': s.get('phase', ''), 'heat_score': heat_score,
            'reasons': reasons, 'risks': risks,
            'sustainability': sustainability, 'sustain_color': sustain_color,
            'action': action, 'action_color': action_color,
            'macd_signal': '金叉' if macd.get('golden_cross') else '死叉' if macd.get('dead_cross') else '柱正' if macd.get('hist', 0) > 0 else '柱负',
            'bb_position': round(bb.get('position', 0.5) * 100, 0),
            'rs_20d': rs.get('rs_20d', 0), 'cur_dd': dd.get('current_drawdown', 0),
            'cycle_phase': cycle.get('phase', '-'),
            'bt_return': bt.get('total_return', 0), 'bt_sharpe': bt.get('sharpe_ratio', 0),
            'entry_low': entry_low, 'entry_high': entry_high,
            'stop_loss': stop_loss, 'stop_loss_pct': stop_loss_pct,
            'tp1': tp1, 'tp2': tp2, 'tp3': tp3,
            'trail_stop': trail_stop, 'risk_reward': rr,
            'position_pct': position_pct, 'position_shares': shares,
            'strategy_steps': steps,
        })
    hot_sectors.sort(key=lambda x: x['heat_score'], reverse=True)
    return hot_sectors[:15]


def _atr(closes, period=14):
    if len(closes) < period + 1:
        return abs(closes[-1] - closes[-2]) if len(closes) > 1 else 0
    trs = [max(abs(closes[i]-closes[i-1]), abs(closes[i]-closes[max(0,i-1)]), abs(closes[i-1]-closes[max(0,i-1)])) for i in range(1, len(closes))]
    return sum(trs[-period:]) / period
