#!/usr/bin/env python3
"""计算所有板块的精确轮动周期"""
import json, os, sys
sys.path.insert(0, os.path.dirname(__file__))

from cycle_engine import estimate_rotation_cycle
import numpy as np

DIR = os.path.dirname(os.path.abspath(__file__))

def load_etf_data():
    etf_cache = os.path.join(DIR, 'etf_cache')
    analysis_path = os.path.join(DIR, 'analysis_data.json')
    
    name_map = {}
    if os.path.exists(analysis_path):
        with open(analysis_path) as f:
            analysis = json.load(f)
        for name, s in analysis.get('sectors', {}).items():
            name_map[s.get('code', '')] = name
    
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
                name = name_map.get(code, code)
                sector_data[name] = {'closes': closes, 'dates': dates}
        except:
            pass
    return sector_data

def main():
    print("=" * 70)
    print("板块轮动周期精确计算（多方法融合）")
    print("=" * 70)
    
    sector_data = load_etf_data()
    print(f"加载 {len(sector_data)} 个板块\n")
    
    all_cycles = {}
    
    for name, data in sorted(sector_data.items()):
        closes = np.array(data['closes'], dtype=np.float64)
        cycle = estimate_rotation_cycle(closes, data['dates'])
        
        if cycle and cycle.get('consensus_period'):
            all_cycles[name] = cycle
            period = cycle['consensus_period']
            conf = cycle['confidence']
            stability = cycle['cycle_stability']
            phase = cycle['current_phase']
            progress = cycle['phase_progress']
            agreement = cycle.get('method_agreement', 0)
            
            # 方法详情
            methods = []
            if 'acf_primary' in cycle['methods']:
                methods.append(f"ACF={cycle['methods']['acf_primary']['period']}天")
            if 'burg_primary' in cycle['methods']:
                methods.append(f"Burg={cycle['methods']['burg_primary']['period']}天")
            if 'fft' in cycle['methods'] and cycle['methods']['fft']:
                methods.append(f"FFT={cycle['methods']['fft'][0]['period']}天")
            if 'time_varying' in cycle['methods']:
                tv = cycle['methods']['time_varying']
                methods.append(f"TV={tv['avg_period']}±{tv['std_period']}天")
            
            buy_sell = cycle.get('next_buy_estimate', cycle.get('next_sell_estimate', ''))
            
            print(f"  {name:<10} 周期={period:>6.1f}天 置信={conf:.2f} 稳定={stability:.2f} "
                  f"一致={agreement:.2f} 阶段={phase}({progress}%) "
                  f"[{', '.join(methods)}] {buy_sell}")
        else:
            print(f"  {name:<10} 无显著周期")
    
    # 保存结果
    output_path = os.path.join(DIR, 'cycle_analysis.json')
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(all_cycles, f, ensure_ascii=False, indent=2)
    
    print(f"\n结果已保存: {output_path}")
    print(f"有效板块: {len(all_cycles)}/{len(sector_data)}")
    
    # 统计
    periods = [c['consensus_period'] for c in all_cycles.values()]
    print(f"\n周期统计:")
    print(f"  平均周期: {np.mean(periods):.1f}天")
    print(f"  中位周期: {np.median(periods):.1f}天")
    print(f"  最短周期: {np.min(periods):.1f}天")
    print(f"  最长周期: {np.max(periods):.1f}天")

if __name__ == '__main__':
    main()
