#!/usr/bin/env python3
"""
运行全板块回测并生成报告
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(__file__))

from backtest_engine import run_backtest, recommend_strategy, ALL_STRATEGIES

def load_etf_data():
    """加载ETF缓存数据"""
    etf_cache = os.path.join(os.path.dirname(__file__), 'etf_cache')
    sector_data = {}
    
    for f in os.listdir(etf_cache):
        if not f.endswith('.json') or f.startswith('proxy_'):
            continue
        code = f.replace('.json', '')
        path = os.path.join(etf_cache, f)
        try:
            with open(path) as fp:
                klines = json.load(fp)
            closes, dates = [], []
            for k in klines:
                if len(k) >= 3:
                    try:
                        c = float(k[2])
                        if c > 0:
                            closes.append(c)
                            dates.append(k[0])
                    except:
                        pass
            if len(closes) > 100:
                # 用ETF代码作为名称（后续可映射）
                sector_data[code] = {'closes': closes, 'dates': dates}
        except:
            pass
    
    # 加载板块名称映射
    analysis_path = os.path.join(os.path.dirname(__file__), 'analysis_data.json')
    name_map = {}
    if os.path.exists(analysis_path):
        with open(analysis_path) as f:
            analysis = json.load(f)
        for name, s in analysis.get('sectors', {}).items():
            name_map[s.get('code', '')] = name
    
    # 重命名
    renamed = {}
    for code, data in sector_data.items():
        name = name_map.get(code, code)
        renamed[name] = data
    
    return renamed

def main():
    print("=" * 60)
    print("板块/ETF 回测报告")
    print("=" * 60)
    
    # 加载数据
    sector_data = load_etf_data()
    print(f"加载 {len(sector_data)} 个板块/ETF")
    
    if not sector_data:
        print("无数据，退出")
        return
    
    # 运行回测
    print("运行 9 种策略回测...")
    backtest_results = run_backtest(sector_data)
    
    # 推荐最优策略
    recommendations = recommend_strategy(backtest_results)
    
    # 按综合表现排序
    ranked = sorted(recommendations.items(), 
                    key=lambda x: x[1]['total_return'], reverse=True)
    
    # 输出报告
    print(f"\n{'='*80}")
    print(f"{'板块':<10} {'最优策略':<30} {'总收益':>8} {'年化':>8} {'夏普':>6} {'胜率':>6} {'回撤':>8} {'交易':>4}")
    print(f"{'='*80}")
    
    for name, rec in ranked[:25]:
        print(f"{name:<10} {rec['best_strategy']:<30} "
              f"{rec['total_return']:>+7.1f}% {rec['annual_return']:>+7.1f}% "
              f"{rec['sharpe_ratio']:>5.2f} {rec['win_rate']:>5.1f}% "
              f"{rec['max_drawdown']:>7.1f}% {rec['trade_count']:>4}")
    
    # 保存结果
    output = {
        'generated_at': __import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M'),
        'strategies': [s()['name'] for s in ALL_STRATEGIES],
        'recommendations': {},
    }
    
    for name, rec in ranked:
        output['recommendations'][name] = {
            'best_strategy': rec['best_strategy'],
            'total_return': rec['total_return'],
            'annual_return': rec['annual_return'],
            'max_drawdown': rec['max_drawdown'],
            'sharpe_ratio': rec['sharpe_ratio'],
            'win_rate': rec['win_rate'],
            'trade_count': rec['trade_count'],
            'equity_curve': rec['equity_curve'][-100:],
            'all_strategies': rec['all_strategies'],
        }
    
    out_path = os.path.join(os.path.dirname(__file__), 'backtest_results.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print(f"\n回测结果已保存: {out_path}")
    
    # 最佳策略统计
    from collections import Counter
    strategy_counts = Counter(rec['best_strategy'] for rec in recommendations.values())
    print(f"\n最优策略分布:")
    for strat, count in strategy_counts.most_common():
        print(f"  {strat}: {count}个板块")

if __name__ == '__main__':
    main()
