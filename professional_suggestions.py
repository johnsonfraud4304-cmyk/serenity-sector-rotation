#!/usr/bin/env python3
"""专业交易建议引擎 — 整合所有分析模块，给出精确到点位的操作建议"""
import json, os, math

DIR = os.path.dirname(os.path.abspath(__file__))


def generate_professional_suggestions(sectors, backtest_data, cycle_data, dl_data, portfolios):
    """生成专业级交易建议"""
    suggestions = []
    
    # ===== 市场背景分析 =====
    market_context = _analyze_market_context(sectors)
    
    for name, s in sectors.items():
        code = s.get('code', '')
        price = s.get('current_price', 0)
        rsi = s.get('rsi', 50)
        mom20 = s.get('mom_20', 0)
        mom60 = s.get('mom_60', 0)
        phase = s.get('phase', '')
        action = s.get('action', '')
        category = s.get('category', '')
        cs = s.get('composite_signal', {})
        score = cs.get('score', 0)
        macd = s.get('macd', {})
        bb = s.get('bollinger', {})
        dd = s.get('drawdown', {})
        rs = s.get('relative_strength', {})
        potential = s.get('potential_score', 50)
        dl = s.get('dl', {})
        
        # 回测数据
        bt = backtest_data.get('recommendations', {}).get(name, {})
        best_strategy = bt.get('best_strategy', '')
        bt_return = bt.get('total_return', 0)
        bt_sharpe = bt.get('sharpe_ratio', 0)
        bt_winrate = bt.get('win_rate', 0)
        bt_maxdd = bt.get('max_drawdown', 0)
        
        # 周期数据
        cycle = cycle_data.get(name, {})
        cycle_period = cycle.get('period', 0)
        cycle_phase = cycle.get('phase', '')
        cycle_confidence = cycle.get('confidence', 0)
        cycle_progress = cycle.get('progress', 0)
        
        # DL预测
        pred_mom = dl.get('pred_mom', 0)
        pred_phase = dl.get('pred_phase', '')
        rot_score = dl.get('rotation_score', 0)
        
        # ===== 计算精确点位 =====
        if price <= 0:
            continue
        
        # ATR计算 - 从缓存加载 closes
        closes = []
        cache_file = os.path.join(DIR, 'etf_cache', f'{code}.json')
        if os.path.exists(cache_file):
            try:
                with open(cache_file) as f:
                    klines = json.load(f)
                closes = [float(k[2]) for k in klines if len(k) >= 3 and float(k[2]) > 0]
            except:
                closes = [price] * 20
        if not closes:
            closes = [price] * 20
        atr = _atr(closes, 14)
        
        # 支撑/阻力位
        recent_high = max(closes[-20:]) if len(closes) >= 20 else price * 1.1
        recent_low = min(closes[-20:]) if len(closes) >= 20 else price * 0.9
        ma20 = s.get('bias_20', 0)
        ma60 = s.get('bias_60', 0)
        
        # 买入区间
        if rsi < 30:
            entry_low = round(price * 0.98, 3)
            entry_high = round(price * 1.02, 3)
            entry_urgency = '立即'
        elif rsi < 40:
            entry_low = round(price * 0.95, 3)
            entry_high = round(price, 3)
            entry_urgency = '近期'
        elif phase == '底部区':
            entry_low = round(price * 0.97, 3)
            entry_high = round(price * 1.01, 3)
            entry_urgency = '等待回调'
        else:
            entry_low = round(price * 0.97, 3)
            entry_high = round(price * 1.02, 3)
            entry_urgency = '择机'
        
        # 止损位（基于ATR和支撑位）
        stop_loss_atr = round(price - 2 * atr, 3)
        stop_loss_support = round(recent_low * 0.98, 3)
        stop_loss = max(stop_loss_atr, stop_loss_support)
        stop_loss = round(stop_loss, 3)
        stop_loss_pct = round((stop_loss / price - 1) * 100, 1)
        
        # 止盈位（多目标）
        if rsi < 30:
            tp1 = round(price * 1.08, 3)  # 第一目标 8%
            tp2 = round(price * 1.15, 3)  # 第二目标 15%
            tp3 = round(price * 1.25, 3)  # 第三目标 25%
        elif rsi < 50:
            tp1 = round(price * 1.05, 3)
            tp2 = round(price * 1.10, 3)
            tp3 = round(price * 1.18, 3)
        else:
            tp1 = round(price * 1.03, 3)
            tp2 = round(price * 1.06, 3)
            tp3 = round(price * 1.12, 3)
        
        # 移动止损
        trail_stop = round(max(stop_loss, price * 0.93), 3)
        
        # 盈亏比
        risk = price - stop_loss
        reward1 = tp1 - price
        reward2 = tp2 - price
        risk_reward1 = round(reward1 / risk, 2) if risk > 0 else 0
        risk_reward2 = round(reward2 / risk, 2) if risk > 0 else 0
        
        # ===== 综合建议 =====
        buy_score = 0
        reasons_for_buy = []
        reasons_for_sell = []
        
        # RSI
        if rsi < 25:
            buy_score += 25
            reasons_for_buy.append(f'RSI={rsi:.0f}极度超卖')
        elif rsi < 35:
            buy_score += 15
            reasons_for_buy.append(f'RSI={rsi:.0f}超卖区')
        elif rsi > 75:
            buy_score -= 25
            reasons_for_sell.append(f'RSI={rsi:.0f}极度超买')
        elif rsi > 65:
            buy_score -= 15
            reasons_for_sell.append(f'RSI={rsi:.0f}超买区')
        
        # 动量
        if mom20 > 0 and mom60 > 0:
            buy_score += 10
            reasons_for_buy.append(f'双周期上升({mom20:+.1f}%/{mom60:+.1f}%)')
        elif mom20 < -5 and mom60 < -5:
            buy_score -= 10
            reasons_for_sell.append(f'双周期下跌({mom20:+.1f}%/{mom60:+.1f}%)')
        
        # MACD
        if macd.get('golden_cross'):
            buy_score += 15
            reasons_for_buy.append('MACD金叉')
        elif macd.get('dead_cross'):
            buy_score -= 15
            reasons_for_sell.append('MACD死叉')
        
        # 布林带
        bb_pos = bb.get('position', 0.5)
        if bb_pos < 0.15:
            buy_score += 10
            reasons_for_buy.append(f'触及布林下轨({bb_pos:.0%})')
        elif bb_pos > 0.85:
            buy_score -= 10
            reasons_for_sell.append(f'触及布林上轨({bb_pos:.0%})')
        
        # 回撤
        cur_dd = dd.get('current_drawdown', 0)
        if cur_dd > 30:
            buy_score += 10
            reasons_for_buy.append(f'深度回撤{cur_dd:.0f}%')
        
        # 相对强度
        rs20 = rs.get('rs_20d', 0)
        if rs20 > 3:
            buy_score += 5
            reasons_for_buy.append(f'跑赢大盘{rs20:+.1f}%')
        elif rs20 < -3:
            buy_score -= 5
            reasons_for_sell.append(f'跑输大盘{rs20:+.1f}%')
        
        # DL预测
        if pred_mom > 3:
            buy_score += 8
            reasons_for_buy.append(f'AI预测动量+{pred_mom:.1f}%')
        elif pred_mom < -3:
            buy_score -= 8
            reasons_for_sell.append(f'AI预测动量{pred_mom:.1f}%')
        
        # 回测表现
        if bt_return > 30 and bt_sharpe > 1:
            buy_score += 5
            reasons_for_buy.append(f'回测优秀(收益{bt_return:.0f}%夏普{bt_sharpe:.1f})')
        
        # 周期
        if cycle_phase == '底部上升' and cycle_confidence > 0.5:
            buy_score += 5
            reasons_for_buy.append(f'周期底部上升(置信{cycle_confidence:.0%})')
        
        # ===== 确定建议 =====
        if buy_score >= 40:
            signal = '强烈买入'
            signal_color = '#22c55e'
            action_detail = f'分2-3批建仓，首批{entry_urgency}在¥{entry_low}-{entry_high}区间买入'
        elif buy_score >= 20:
            signal = '建议买入'
            signal_color = '#4ade80'
            action_detail = f'轻仓试探，在¥{entry_low}-{entry_high}区间分批买入'
        elif buy_score <= -40:
            signal = '强烈卖出'
            signal_color = '#ef4444'
            action_detail = '建议立即清仓，严格止损'
        elif buy_score <= -20:
            signal = '建议减仓'
            signal_color = '#f87171'
            action_detail = '建议减仓50%，设好止损'
        elif rsi > 60 and mom20 > 5:
            signal = '持有观望'
            signal_color = '#f59e0b'
            action_detail = f'趋势向好但RSI偏高，持有并设移动止损¥{trail_stop}'
        else:
            signal = '暂不操作'
            signal_color = '#9ca3af'
            action_detail = '信号不明确，等待更好时机'
        
        # 仓位建议
        risk_per_trade = 2  # 每笔风险2%
        capital = 100000
        max_loss = capital * risk_per_trade / 100
        stop_distance = price - stop_loss
        if stop_distance > 0:
            shares = int(max_loss / stop_distance)
            position_value = shares * price
            position_pct = round(position_value / capital * 100, 1)
        else:
            shares = 0
            position_value = 0
            position_pct = 0
        
        # 持有周期建议
        if cycle_period > 0:
            hold_days = int(cycle_period * 0.3)
        else:
            hold_days = 20
        hold_suggestion = f'{hold_days}个交易日'
        
        # 具体操作步骤
        strategy_steps = _generate_strategy_steps(signal, rsi, entry_low, entry_high, stop_loss, tp1, tp2, tp3, trail_stop, hold_days)
        
        # 风险提示
        risk_warnings = []
        if cur_dd > 25:
            risk_warnings.append(f'历史最大回撤{dd.get("max_drawdown",0):.0f}%，波动剧烈')
        if bt_maxdd > 40:
            risk_warnings.append(f'回测最大回撤{bt_maxdd:.0f}%，需做好风控')
        if abs(mom20) > 10:
            risk_warnings.append(f'短期动量{mom20:+.1f}%，波动较大')
        if not risk_warnings:
            risk_warnings.append('风险可控')
        
        suggestions.append({
            'name': name,
            'code': code,
            'category': category,
            'price': price,
            'signal': signal,
            'signal_color': signal_color,
            'action_detail': action_detail,
            'buy_score': buy_score,
            'reasons_for_buy': reasons_for_buy,
            'reasons_for_sell': reasons_for_sell,
            'entry': {'low': entry_low, 'high': entry_high, 'urgency': entry_urgency},
            'stop_loss': stop_loss,
            'stop_loss_pct': stop_loss_pct,
            'take_profit_1': tp1,
            'take_profit_2': tp2,
            'take_profit_3': tp3,
            'trail_stop': trail_stop,
            'risk_reward_1': risk_reward1,
            'risk_reward_2': risk_reward2,
            'position': {
                'shares': shares,
                'value': round(position_value, 0),
                'pct': position_pct,
                'max_loss': round(max_loss, 0),
            },
            'hold_days': hold_days,
            'hold_suggestion': hold_suggestion,
            'risk_warnings': risk_warnings,
            'strategy_steps': strategy_steps,
            'indicators': {
                'rsi': rsi,
                'mom20': mom20,
                'mom60': mom60,
                'macd_signal': '金叉' if macd.get('golden_cross') else '死叉' if macd.get('dead_cross') else '柱正' if macd.get('hist', 0) > 0 else '柱负',
                'bb_position': round(bb_pos * 100, 0),
                'cur_dd': cur_dd,
                'max_dd': dd.get('max_drawdown', 0),
                'rs_20d': rs20,
            },
            'backtest': {
                'strategy': best_strategy,
                'return': bt_return,
                'sharpe': bt_sharpe,
                'winrate': bt_winrate,
            },
            'cycle': {
                'period': cycle_period,
                'phase': cycle_phase,
                'confidence': cycle_confidence,
                'progress': cycle_progress,
            },
            'ai': {
                'pred_mom': pred_mom,
                'pred_phase': pred_phase,
                'rot_score': rot_score,
            },
            'potential': potential,
            'data_time': s.get('current_price', 0) > 0,
        })
    
    # 按综合评分排序
    suggestions.sort(key=lambda x: x['buy_score'], reverse=True)
    
    # 添加市场背景到每条建议
    for s in suggestions:
        s['market_context'] = market_context
        # 判断该板块在轮动中的位置
        name = s['name']
        if name in [n for n, _, _ in market_context['leaders']]:
            s['rotation_position'] = '领涨'
        elif name in [n for n, _, _ in market_context['laggards']]:
            s['rotation_position'] = '落后'
        else:
            s['rotation_position'] = '中性'
    
    return suggestions


def _atr(closes, period=14):
    """计算ATR"""
    if len(closes) < period + 1:
        return abs(closes[-1] - closes[-2]) if len(closes) > 1 else 0
    trs = []
    for i in range(1, len(closes)):
        tr = max(abs(closes[i] - closes[i-1]),
                 abs(closes[i] - closes[max(0, i-1)]),
                 abs(closes[i-1] - closes[max(0, i-1)]))
        trs.append(tr)
    return sum(trs[-period:]) / period


def _generate_strategy_steps(signal, rsi, entry_low, entry_high, stop_loss, tp1, tp2, tp3, trail_stop, hold_days):
    """生成具体操作步骤"""
    steps = []
    if '买入' in signal:
        steps.append(f'1. 在¥{entry_low}-¥{entry_high}区间挂单买入')
        steps.append(f'2. 首批买入50%仓位，RSI<30时加仓至80%')
        steps.append(f'3. 严格止损：跌破¥{stop_loss}立即卖出')
        steps.append(f'4. 止盈T1：涨到¥{tp1}时卖出30%')
        steps.append(f'5. 止盈T2：涨到¥{tp2}时再卖30%，剩余设移动止损¥{trail_stop}')
        steps.append(f'6. 持有周期：{hold_days}个交易日后重新评估')
    elif '卖出' in signal:
        steps.append(f'1. 开盘后分2批卖出，第一批50%')
        steps.append(f'2. 如果继续上涨，第二批在¥{tp1}附近卖出')
        steps.append(f'3. 如果下跌，在¥{stop_loss}附近止损清仓')
        steps.append(f'4. 卖出后观望{hold_days}个交易日再考虑回补')
    elif '观望' in signal:
        steps.append(f'1. 不建议新建仓位')
        steps.append(f'2. 已持有仓位设移动止损¥{trail_stop}')
        steps.append(f'3. 等待RSI回到30以下或MACD金叉再介入')
        steps.append(f'4. 预计{hold_days}个交易日后出现更好买点')
    else:
        steps.append(f'1. 当前信号不明确，建议观望')
        steps.append(f'2. 关注RSI和MACD变化')
    return steps


def _analyze_market_context(sectors):
    """分析市场背景和板块轮动"""
    # 按动量排序
    sorted_sectors = sorted(sectors.items(), key=lambda x: x[1].get('mom_20', 0), reverse=True)
    
    # 领涨板块
    leaders = [(n, s) for n, s in sorted_sectors[:10] if s.get('mom_20', 0) > 3]
    # 落后板块
    laggards = [(n, s) for n, s in sorted_sectors[-10:] if s.get('mom_20', 0) < -3]
    
    # 市场宽度
    total = len(sectors)
    above_ma20 = sum(1 for s in sectors.values() if s.get('bias_20', 0) > 0)
    above_ma60 = sum(1 for s in sectors.values() if s.get('bias_60', 0) > 0)
    avg_rsi = sum(s.get('rsi', 50) for s in sectors.values()) / total
    avg_mom = sum(s.get('mom_20', 0) for s in sectors.values()) / total
    
    # 判断市场状态
    if avg_rsi < 30:
        market_state = '极度恐慌（逆向买入机会）'
    elif avg_rsi < 40:
        market_state = '恐慌（关注超卖反弹）'
    elif avg_rsi > 70:
        market_state = '极度贪婪（注意风险）'
    elif avg_rsi > 60:
        market_state = '贪婪（谨慎追高）'
    else:
        market_state = '中性'
    
    # 轮动判断
    if len(leaders) > len(laggards) * 2:
        rotation = '资金集中流入强势板块，选择性配置'
    elif len(laggards) > len(leaders) * 2:
        rotation = '资金流出明显，防御为主'
    else:
        rotation = '板块分化，轮动中'
    
    # 领涨板块分类
    leader_cats = set(s.get('category', '') for _, s in leaders)
    laggard_cats = set(s.get('category', '') for _, s in laggards)
    
    return {
        'market_state': market_state,
        'rotation': rotation,
        'leaders': [(n, s.get('mom_20', 0), s.get('category', '')) for n, s in leaders],
        'laggards': [(n, s.get('mom_20', 0), s.get('category', '')) for n, s in laggards],
        'leader_cats': list(leader_cats),
        'laggard_cats': list(laggard_cats),
        'avg_rsi': round(avg_rsi, 1),
        'avg_mom': round(avg_mom, 2),
        'above_ma20_pct': round(above_ma20 / total * 100, 1),
        'above_ma60_pct': round(above_ma60 / total * 100, 1),
    }


if __name__ == '__main__':
    with open(os.path.join(DIR, 'analysis_data.json')) as f:
        d = json.load(f)
    
    suggestions = generate_professional_suggestions(
        d['sectors'], d.get('backtest', {}),
        d.get('cycle_summary', {}), {}, {}
    )
    
    print(f"\n{'='*70}")
    print(f"  Serenity — 专业交易建议报告")
    print(f"{'='*70}")
    
    for s in suggestions[:10]:
        print(f"\n{'─'*60}")
        print(f"  {s['name']} ({s['code']}) ¥{s['price']}")
        print(f"  建议: {s['signal']} (评分={s['buy_score']})")
        print(f"  操作: {s['action_detail']}")
        print(f"  买入区间: ¥{s['entry']['low']}-{s['entry']['high']}")
        print(f"  止损: ¥{s['stop_loss']} ({s['stop_loss_pct']}%)")
        print(f"  止盈T1/T2/T3: ¥{s['take_profit_1']}/¥{s['take_profit_2']}/¥{s['take_profit_3']}")
        print(f"  盈亏比: {s['risk_reward_1']}/{s['risk_reward_2']}")
        print(f"  仓位: {s['position']['pct']}% ({s['position']['shares']}份, ¥{s['position']['value']})")
        print(f"  持有周期: {s['hold_suggestion']}")
        print(f"  风险: {' | '.join(s['risk_warnings'])}")
        if s['reasons_for_buy']:
            print(f"  看多因素: {' | '.join(s['reasons_for_buy'])}")
        if s['reasons_for_sell']:
            print(f"  看空因素: {' | '.join(s['reasons_for_sell'])}")
