#!/usr/bin/env python3
"""
市场综合仪表盘
提供：实时信号预警、市场温度计、跨市场联动、估值分位
"""

import json, os, math
from datetime import datetime

DIR = os.path.dirname(os.path.abspath(__file__))

def load_analysis():
    path = os.path.join(DIR, 'analysis_data.json')
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}


def generate_market_dashboard(analysis):
    """
    生成市场综合仪表盘数据
    """
    sectors = analysis.get('sectors', {})
    if not sectors:
        return {}
    
    dashboard = {}
    
    # ── 1. 实时信号预警系统 ──
    alerts = []
    for name, s in sectors.items():
        rsi = s.get('rsi', 50)
        mom20 = s.get('mom_20', 0)
        mom60 = s.get('mom_60', 0)
        phase = s.get('phase', '')
        score = s.get('potential_score', 50)
        dl = s.get('dl', {})
        cycle = s.get('cycle', {})
        
        # RSI极端信号
        if rsi < 20:
            alerts.append({
                'level': '🔴 强买', 'sector': name,
                'reason': f'RSI={rsi:.0f} 极度超卖（历史最低5%区间）',
                'action': '立即建仓20%',
                'priority': 1,
            })
        elif rsi < 30:
            alerts.append({
                'level': '🟡 买', 'sector': name,
                'reason': f'RSI={rsi:.0f} 超卖区',
                'action': '分批建仓10%',
                'priority': 2,
            })
        elif rsi > 80:
            alerts.append({
                'level': '🔴 强卖', 'sector': name,
                'reason': f'RSI={rsi:.0f} 极度超买',
                'action': '立即减仓50%',
                'priority': 1,
            })
        elif rsi > 70:
            alerts.append({
                'level': '🟡 卖', 'sector': name,
                'reason': f'RSI={rsi:.0f} 超买区',
                'action': '止盈减仓20%',
                'priority': 2,
            })
        
        # 周期拐点信号
        if cycle and cycle.get('current_phase') == '底部上升' and cycle.get('phase_progress', 50) < 30:
            alerts.append({
                'level': '🟢 周期', 'sector': name,
                'reason': f'轮动周期底部上升（周期{cycle.get("consensus_period","?")}天，进度{cycle.get("phase_progress",0)}%）',
                'action': '周期买点，建仓',
                'priority': 3,
            })
        
        # 动量反转信号
        if mom20 > 0 and mom60 < -5:
            alerts.append({
                'level': '🔵 反转', 'sector': name,
                'reason': f'20日动量转正({mom20:+.1f}%)但60日仍负({mom60:+.1f}%)=触底反弹',
                'action': '试探性买入5%',
                'priority': 3,
            })
        
        # AI预测+传统信号共振
        if dl and dl.get('pred_mom', 0) > 3 and rsi < 40:
            alerts.append({
                'level': '🤖 AI', 'sector': name,
                'reason': f'AI预测+{dl["pred_mom"]:.1f}% + RSI={rsi:.0f}偏低 = 共振买点',
                'action': 'AI信号买入10%',
                'priority': 2,
            })
    
    alerts.sort(key=lambda x: x['priority'])
    dashboard['alerts'] = alerts[:15]
    
    # ── 2. 市场温度计 ──
    all_rsi = [s.get('rsi', 50) for s in sectors.values()]
    all_mom = [s.get('mom_20', 0) for s in sectors.values()]
    all_scores = [s.get('potential_score', 50) for s in sectors.values()]
    
    # 计算今日涨跌（从缓存获取最新K线）
    daily_changes = {}
    for name, s in sectors.items():
        code = s.get('code', '')
        cache_file = os.path.join(DIR, 'etf_cache', f'{code}.json')
        try:
            with open(cache_file) as f:
                klines = json.load(f)
            if len(klines) >= 2:
                today = float(klines[-1][2])
                yesterday = float(klines[-2][2])
                daily_changes[name] = round((today / yesterday - 1) * 100, 2)
        except:
            pass
    
    today_rising = sum(1 for v in daily_changes.values() if v > 0)
    today_falling = sum(1 for v in daily_changes.values() if v < 0)
    today_avg = sum(daily_changes.values()) / len(daily_changes) if daily_changes else 0
    today_up_pct = round(today_rising / len(daily_changes) * 100, 1) if daily_changes else 0
    
    # 恐慌/贪婪指数（0-100，50为中性）
    # 融合中期指标(RSI/动量)和短期指标(今日涨跌)
    avg_rsi = sum(all_rsi) / len(all_rsi)
    oversold_count = sum(1 for r in all_rsi if r < 30)
    overbought_count = sum(1 for r in all_rsi if r > 70)
    positive_mom = sum(1 for m in all_mom if m > 0)
    
    # 基础分（基于RSI）
    fear_greed = 50
    if avg_rsi < 35:
        fear_greed = 20
    elif avg_rsi < 45:
        fear_greed = 35
    elif avg_rsi > 65:
        fear_greed = 80
    elif avg_rsi > 55:
        fear_greed = 65
    
    # 中期调整（动量）
    fear_greed += (positive_mom / len(all_mom) - 0.5) * 15
    fear_greed += (overbought_count - oversold_count) / len(all_rsi) * 10
    
    # 短期调整（今日表现）— 这是关键！
    if today_avg > 3:
        fear_greed += 20  # 大涨，恐慌转贪婪
    elif today_avg > 1:
        fear_greed += 10  # 温和上涨
    elif today_avg < -3:
        fear_greed -= 20  # 大跌
    elif today_avg < -1:
        fear_greed -= 10  # 温和下跌
    
    # 上涨比例调整
    if today_up_pct > 70:
        fear_greed += 10
    elif today_up_pct < 30:
        fear_greed -= 10
    
    fear_greed = max(0, min(100, fear_greed))
    
    if fear_greed < 20:
        mood = '极度恐慌 🟦'
        advice = '历史表明极度恐慌时买入，中长期收益可观'
    elif fear_greed < 40:
        mood = '恐慌 🟦'
        advice = '市场偏冷，适合分批建仓'
    elif fear_greed < 60:
        mood = '中性 ⬜'
        advice = '市场平衡，持有观望'
    elif fear_greed < 80:
        mood = '贪婪 🟧'
        advice = '市场偏热，注意止盈'
    else:
        mood = '极度贪婪 🟥'
        advice = '历史上极度贪婪时往往见顶，减仓为宜'
    
    dashboard['market_temp'] = {
        'fear_greed_index': round(fear_greed),
        'mood': mood,
        'advice': advice,
        'avg_rsi': round(avg_rsi, 1),
        'oversold_count': oversold_count,
        'overbought_count': overbought_count,
        'positive_mom_pct': round(positive_mom / len(all_mom) * 100),
        'avg_score': round(sum(all_scores) / len(all_scores)),
        'today_avg_change': round(today_avg, 2),
        'today_rising': today_rising,
        'today_falling': today_falling,
        'today_up_pct': today_up_pct,
    }
    
    # ── 3. 板块强弱分布 ──
    phase_dist = {}
    for s in sectors.values():
        p = s.get('phase', '未知')
        phase_dist[p] = phase_dist.get(p, 0) + 1
    
    dashboard['phase_distribution'] = phase_dist
    
    # ── 4. 跨市场联动（基于相关性） ──
    cross_market = []
    # A股科技 vs 美股纳指
    semi = sectors.get('半导体', {})
    nq = sectors.get('纳斯达克100', sectors.get('纳斯达克', {}))
    if semi and nq:
        cross_market.append({
            'pair': '半导体 vs 纳斯达克',
            'a_mom': semi.get('mom_20', 0),
            'b_mom': nq.get('mom_20', 0),
            'signal': '同向强化' if semi.get('mom_20',0) * nq.get('mom_20',0) > 0 else '背离（注意风险）',
        })
    # 消费 vs 白酒
    consume = sectors.get('消费', {})
    baijiu = sectors.get('白酒', {})
    if consume and baijiu:
        cross_market.append({
            'pair': '消费 vs 白酒',
            'a_mom': consume.get('mom_20', 0),
            'b_mom': baijiu.get('mom_20', 0),
            'signal': '同向强化' if consume.get('mom_20',0) * baijiu.get('mom_20',0) > 0 else '背离',
        })
    # 新能源 vs 光伏
    ne = sectors.get('新能源', {})
    pv = sectors.get('光伏', {})
    if ne and pv:
        cross_market.append({
            'pair': '新能源 vs 光伏',
            'a_mom': ne.get('mom_20', 0),
            'b_mom': pv.get('mom_20', 0),
            'signal': '同向强化' if ne.get('mom_20',0) * pv.get('mom_20',0) > 0 else '背离',
        })
    
    dashboard['cross_market'] = cross_market
    
    # ── 5. 今日操作建议汇总 ──
    buy_list = []
    sell_list = []
    hold_list = []
    
    for name, s in sectors.items():
        score = s.get('potential_score', 50)
        rsi = s.get('rsi', 50)
        phase = s.get('phase', '')
        
        if score >= 70 and rsi < 35:
            buy_list.append({'name': name, 'score': score, 'rsi': rsi, 'reason': f'评分{score} RSI={rsi:.0f}'})
        elif rsi > 70 or phase == '顶部区':
            sell_list.append({'name': name, 'score': score, 'rsi': rsi, 'reason': f'RSI={rsi:.0f} {phase}'})
        else:
            hold_list.append({'name': name, 'score': score})
    
    buy_list.sort(key=lambda x: x['score'], reverse=True)
    sell_list.sort(key=lambda x: x['rsi'], reverse=True)
    
    dashboard['action_summary'] = {
        'buy': buy_list[:5],
        'sell': sell_list[:5],
        'hold_count': len(hold_list),
    }
    
    return dashboard


if __name__ == '__main__':
    analysis = load_analysis()
    dashboard = generate_market_dashboard(analysis)
    
    print("=" * 60)
    print("市场综合仪表盘")
    print("=" * 60)
    
    temp = dashboard.get('market_temp', {})
    print(f"\n🌡️ 市场温度: {temp.get('fear_greed_index', 50)}/100 {temp.get('mood', '')}")
    print(f"   平均RSI: {temp.get('avg_rsi', 50)} | 超卖: {temp.get('oversold_count',0)}个 | 超买: {temp.get('overbought_count',0)}个")
    print(f"   建议: {temp.get('advice', '')}")
    
    print(f"\n🚨 信号预警:")
    for alert in dashboard.get('alerts', [])[:8]:
        print(f"  {alert['level']} {alert['sector']}: {alert['reason']} → {alert['action']}")
    
    print(f"\n📊 今日操作:")
    action = dashboard.get('action_summary', {})
    for b in action.get('buy', []):
        print(f"  🟢 买入: {b['name']} ({b['reason']})")
    for s in action.get('sell', []):
        print(f"  🔴 卖出: {s['name']} ({s['reason']})")
    
    # 保存
    out_path = os.path.join(DIR, 'dashboard.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(dashboard, f, ensure_ascii=False, indent=2)
    print(f"\n仪表盘数据已保存: {out_path}")
