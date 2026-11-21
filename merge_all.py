#!/usr/bin/env python3
"""合并所有数据源到analysis_data.json"""
import json, os

DIR = os.path.dirname(os.path.abspath(__file__))

def merge():
    # 加载analysis_data
    with open(os.path.join(DIR, 'analysis_data.json')) as f:
        analysis = json.load(f)
    
    # 合并DL预测
    dl_path = os.path.join(DIR, 'dl_predictions.json')
    if os.path.exists(dl_path):
        with open(dl_path) as f:
            dl = json.load(f)
        for name, pred in dl.get('predictions', {}).items():
            if name in analysis['sectors']:
                analysis['sectors'][name]['dl'] = {
                    'pred_mom': pred.get('pred_mom', 0),
                    'pred_phase': pred.get('pred_phase', ''),
                    'rotation_score': pred.get('rotation_score', 0),
                    'confidence': pred.get('confidence', 0),
                }
        analysis['dl_model'] = dl.get('model_info', {})
    
    # 合并周期分析
    cycle_path = os.path.join(DIR, 'cycle_analysis.json')
    if os.path.exists(cycle_path):
        with open(cycle_path) as f:
            cycles = json.load(f)
        for name, cycle in cycles.items():
            if name in analysis['sectors']:
                analysis['sectors'][name]['cycle'] = cycle
        analysis['cycle_summary'] = {
            name: {
                'period': cycle.get('consensus_period'),
                'phase': cycle.get('current_phase'),
                'progress': cycle.get('phase_progress'),
                'confidence': cycle.get('confidence'),
                'stability': cycle.get('cycle_stability'),
                'next_signal': cycle.get('next_buy_estimate', cycle.get('next_sell_estimate', '')),
                'methods': {
                    k: v for k, v in cycle.get('methods', {}).items()
                    if k in ['acf_primary', 'burg_primary', 'time_varying'] and isinstance(v, dict)
                },
            }
            for name, cycle in cycles.items()
        }
    
    # 合并仪表盘
    from dashboard_engine import generate_market_dashboard
    dashboard = generate_market_dashboard(analysis)
    if dashboard:
        analysis['dashboard'] = dashboard
    
    # 合并回测结果
    bt_path = os.path.join(DIR, 'backtest_results.json')
    if os.path.exists(bt_path):
        with open(bt_path) as f:
            bt = json.load(f)
        analysis['backtest'] = {
            'strategies': bt.get('strategies', []),
            'recommendations': bt.get('recommendations', {}),
        }
    
    # 保存
    with open(os.path.join(DIR, 'analysis_data.json'), 'w', encoding='utf-8') as f:
        json.dump(analysis, f, ensure_ascii=False, indent=2)
    
    print(f"合并完成: {len(analysis['sectors'])} 板块, DL={'有' if 'dl_model' in analysis else '无'}, 回测={'有' if 'backtest' in analysis else '无'}")

if __name__ == '__main__':
    merge()
