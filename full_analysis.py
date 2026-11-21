"""快速分析脚本 — 并行获取+精简分析"""
import sys, os, json, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fast_fetch import fast_fetch_all
from data_engine import (
    compute_returns, rolling_momentum, simple_fft, compute_rsi, compute_ma,
    classify_phase, compute_seasonal, compute_potential_score, compute_corr_matrix,
    SECTOR_COLORS, get_etfs_by_category, is_market_hours
)
from dashboard_engine import generate_market_dashboard
from advanced_analysis import run_advanced_analysis
from datetime import datetime
import time

DIR = os.path.dirname(os.path.abspath(__file__))

# 1. 快速获取数据（并行，~3-5秒）
all_etf_data = fast_fetch_all(max_workers=10)
success = len(all_etf_data)

if success < 10:
    print("数据不足")
    sys.exit(1)

min_len = min(len(d['closes']) for d in all_etf_data.values())
min_len = min(min_len, 600)

market_open = is_market_hours()
rt_count = sum(1 for d in all_etf_data.values() if d.get('realtime'))

results = {
    'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M'),
    'data_range': '', 'total_etfs': len(all_etf_data), 'loaded_etfs': success,
    'categories': get_etfs_by_category(), 'sectors': {},
    'rotation_history': [], 'correlation_matrix': {}, 'signals': [],
    'realtime_mode': market_open, 'realtime_count': rt_count,
}
all_returns = {}

# 2. 技术分析（纯计算，很快）
for name, data in all_etf_data.items():
    closes = data['closes'][-min_len:]
    dates = data['dates'][-min_len:]
    rets = compute_returns(closes)
    if not results['data_range']:
        results['data_range'] = f"{dates[0]} ~ {dates[-1]}"
    mom_20 = rolling_momentum(rets, 20)
    mom_60 = rolling_momentum(rets, 60)
    rsi = compute_rsi(closes)
    ma20 = compute_ma(closes, 20)
    ma60 = compute_ma(closes, 60)
    bias_20 = (closes[-1] / ma20 - 1) * 100 if ma20 > 0 else 0
    bias_60 = (closes[-1] / ma60 - 1) * 100 if ma60 > 0 else 0
    spectrum = simple_fft(mom_20 if mom_20 else [0]*20)
    current_mom_20 = mom_20[-1] if mom_20 else 0
    current_mom_60 = mom_60[-1] if mom_60 else 0
    phase, phase_color, action = classify_phase(current_mom_20, current_mom_60, rsi)
    seasonal = compute_seasonal(rets, dates)
    cum_ret = (closes[-1] / closes[0] - 1) * 100
    mom_20_history = mom_20[-120:] if len(mom_20) >= 120 else mom_20
    temp_result = {'rsi': round(rsi, 1), 'mom_20': round(current_mom_20, 2), 'mom_60': round(current_mom_60, 2), 'bias_20': round(bias_20, 2), 'phase': phase}
    potential_score = compute_potential_score(temp_result, seasonal, dl=None, spectrum=spectrum)
    results['sectors'][name] = {
        'code': data['code'], 'full_name': data['full_name'],
        'category': data['category'],
        'color': SECTOR_COLORS.get(data['category'], '#6b7280'),
        'closes': closes, 'potential_score': potential_score,
        'cum_return': round(cum_ret, 1), 'current_price': round(closes[-1], 3),
        'rsi': round(rsi, 1), 'mom_20': round(current_mom_20, 2),
        'mom_60': round(current_mom_60, 2), 'bias_20': round(bias_20, 2),
        'bias_60': round(bias_60, 2), 'phase': phase,
        'phase_color': phase_color, 'action': action,
        'spectrum': spectrum, 'seasonal': seasonal,
        'mom_20_history': [round(x, 2) for x in mom_20_history],
        'dates': dates[-len(mom_20_history):] if mom_20_history else [],
        'realtime': data.get('realtime'),
    }
    all_returns[name] = rets

# 3. 相关性矩阵
top_sectors = list(all_returns.keys())[:15]
results['correlation_matrix'] = compute_corr_matrix({k: all_returns[k] for k in top_sectors})

# 4. 轮动历史
sector_names = list(all_returns.keys())
for start in range(0, min_len - 60, 60):
    end = start + 60
    period_perf = {}
    for nm in sector_names:
        c = all_etf_data[nm]['closes'][-min_len:]
        period_perf[nm] = round((c[end] / c[start] - 1) * 100, 1) if c[start] > 0 else 0
    ranked = sorted(period_perf.items(), key=lambda x: x[1], reverse=True)
    results['rotation_history'].append({
        'date': all_etf_data[sector_names[0]]['dates'][-min_len + start] if start < min_len else '',
        'rankings': [{'sector': s, 'return': r} for s, r in ranked[:10]],
    })

# 5. 信号
for nm in sector_names:
    s = results['sectors'][nm]
    if s['rsi'] < 30:
        results['signals'].append({'type': 'BUY', 'sector': nm, 'reason': f"RSI={s['rsi']:.0f}", 'strength': '强'})
    elif s['rsi'] > 70:
        results['signals'].append({'type': 'SELL', 'sector': nm, 'reason': f"RSI={s['rsi']:.0f}", 'strength': '强'})
    elif s['mom_20'] > 10:
        results['signals'].append({'type': 'HOLD', 'sector': nm, 'reason': f"动量={s['mom_20']:+.1f}%", 'strength': '中'})
    elif s['mom_20'] < -10:
        results['signals'].append({'type': 'WATCH', 'sector': nm, 'reason': f"动量={s['mom_20']:+.1f}%", 'strength': '中'})

# 6. Dashboard
db = generate_market_dashboard(results)
if db:
    results['dashboard'] = db

# 7. 高级分析（MACD/布林带/回撤/相对强度/组合）
enhanced, breadth, portfolios = run_advanced_analysis(results['sectors'])
for name in results['sectors']:
    if name in enhanced:
        results['sectors'][name] = enhanced[name]
results['market_breadth'] = breadth
results['portfolios'] = portfolios

# 8. 回测（复用缓存的结果，不重新计算）
bt_path = os.path.join(DIR, 'backtest_results.json')
if os.path.exists(bt_path):
    with open(bt_path) as f:
        bt = json.load(f)
    results['backtest'] = {
        'strategies': bt.get('strategies', []),
        'recommendations': bt.get('recommendations', {}),
    }

# 9. 周期分析（复用缓存的结果）
cycle_path = os.path.join(DIR, 'cycle_analysis.json')
if os.path.exists(cycle_path):
    with open(cycle_path) as f:
        cycles = json.load(f)
    results['cycle_summary'] = {
        name: {
            'period': c.get('consensus_period'),
            'phase': c.get('current_phase'),
            'progress': c.get('phase_progress'),
            'confidence': c.get('confidence'),
            'stability': c.get('cycle_stability'),
            'next_signal': c.get('next_buy_estimate', c.get('next_sell_estimate', '')),
            'methods': {k: v for k, v in c.get('methods', {}).items()
                       if k in ['acf_primary', 'burg_primary', 'time_varying'] and isinstance(v, dict)},
        }
        for name, c in cycles.items()
    }

# 10. DL预测（合并已有结果）
dl_path = os.path.join(DIR, 'dl_predictions.json')
if os.path.exists(dl_path):
    with open(dl_path) as f:
        dl = json.load(f)
    for nm, pred in dl.get('predictions', {}).items():
        if nm in results['sectors']:
            results['sectors'][nm]['dl'] = {
                'pred_mom': pred.get('pred_mom', 0), 'pred_phase': pred.get('pred_phase', ''),
                'rotation_score': pred.get('rotation_score', 0), 'confidence': pred.get('confidence', 0),
                'pred_phase_probs': pred.get('pred_phase_probs', {}),
            }
            s = results['sectors'][nm]
            s['potential_score'] = compute_potential_score(s, s.get('seasonal', {}), dl=s['dl'], spectrum=s.get('spectrum', []))
    results['dl_model'] = dl.get('model_info', {})

# 清理 closes
for name in results['sectors']:
    results['sectors'][name].pop('closes', None)

# 保存
with open(os.path.join(DIR, 'analysis_data.json'), 'w', encoding='utf-8') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

print('DONE')
