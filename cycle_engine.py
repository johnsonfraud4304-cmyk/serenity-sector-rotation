#!/usr/bin/env python3
"""
板块轮动周期精确计算引擎
方法：自相关+显著性检验 / 最大熵谱估计 / Hilbert-Huang变换 / 小波分析
"""

import math, json, os
import numpy as np

# ============================================================
# 1. 自相关分析 + 置信区间
# ============================================================
def autocorrelation_analysis(series, max_lag=150):
    """
    自相关函数分析，带Bartlett置信区间
    返回：显著周期列表（带置信度）
    """
    n = len(series)
    if n < 60:
        return []
    
    mean = np.mean(series)
    var = np.var(series)
    if var < 1e-10:
        return []
    
    # 计算ACF
    acf = np.zeros(max_lag)
    for lag in range(1, max_lag):
        if lag >= n:
            break
        cov = np.sum((series[lag:] - mean) * (series[:n-lag] - mean)) / n
        acf[lag] = cov / var
    
    # Bartlett 95%置信区间：±1.96/√n
    confidence_bound = 1.96 / math.sqrt(n)
    
    # 找显著峰值（超过置信区间且是局部最小值）
    # 只关注20天以上的周期（过滤高频噪声）
    peaks = []
    min_lag = 20  # 最小周期20天
    for i in range(max(min_lag, 2), min(max_lag-1, n//2)):
        if (acf[i] > confidence_bound and 
            acf[i] > acf[i-1] and acf[i] > acf[i+1]):
            # 估计峰值的精确位置（抛物线插值）
            if acf[i-1] + acf[i+1] - 2*acf[i] != 0:
                delta = 0.5 * (acf[i-1] - acf[i+1]) / (acf[i-1] + acf[i+1] - 2*acf[i])
            else:
                delta = 0
            refined_lag = i + delta
            
            # 计算周期的置信度（ACF值/置信区间）
            confidence = acf[i] / confidence_bound
            
            peaks.append({
                'period': round(refined_lag, 1),
                'acf_value': round(acf[i], 4),
                'confidence': round(confidence, 2),
                'significant': bool(confidence > 1.0),
            })
    
    # 按置信度排序
    peaks.sort(key=lambda x: x['confidence'], reverse=True)
    return peaks[:5]


# ============================================================
# 2. 最大熵谱估计（Burg方法）
# ============================================================
def burg_spectrum(series, order=20, n_freq=200):
    """
    Burg最大熵谱估计
    比FFT频率分辨率更高，适合短数据
    """
    n = len(series)
    if n < order + 10:
        return []
    
    x = np.array(series, dtype=np.float64)
    x = x - np.mean(x)
    
    # Burg算法
    ef = x.copy()
    eb = x.copy()
    a = np.zeros(order + 1)
    a[0] = 1.0
    
    for m in range(order):
        # 反射系数
        num = 0.0
        den = 0.0
        for i in range(m + 1, n):
            num += ef[i] * eb[i-1]
            den += ef[i]**2 + eb[i-1]**2
        
        if den < 1e-15:
            break
        
        k = -2.0 * num / den
        if abs(k) >= 1.0:
            k = 0.99 * np.sign(k)
        
        # 更新预测误差
        ef_new = ef.copy()
        eb_new = eb.copy()
        for i in range(m + 1, n):
            ef_new[i] = ef[i] + k * eb[i-1]
            eb_new[i] = eb[i-1] + k * ef[i]
        ef = ef_new
        eb = eb_new
        
        # 更新AR系数
        a_new = a.copy()
        a_new[m+1] = k
        for j in range(1, m+1):
            a_new[j] = a[j] + k * a[m-j+1]
        a = a_new
    
    # 计算功率谱
    freqs = np.linspace(0.001, 0.5, n_freq)
    psd = np.zeros(n_freq)
    
    noise_var = np.sum(ef**2) / n
    for i, f in enumerate(freqs):
        z_real = 1.0
        z_imag = 0.0
        for j in range(1, order + 1):
            angle = 2 * math.pi * f * j
            z_real += a[j] * math.cos(angle)
            z_imag -= a[j] * math.sin(angle)
        denom = z_real**2 + z_imag**2
        psd[i] = noise_var / denom if denom > 1e-15 else 0
    
    # 找峰值（主频率）
    peaks = []
    for i in range(2, n_freq - 2):
        if psd[i] > psd[i-1] and psd[i] > psd[i+1] and psd[i] > np.mean(psd) * 2:
            # 精确频率估计
            if psd[i-1] + psd[i+1] - 2*psd[i] != 0:
                delta = 0.5 * (psd[i-1] - psd[i+1]) / (psd[i-1] + psd[i+1] - 2*psd[i])
            else:
                delta = 0
            refined_freq = freqs[i] + delta * (freqs[1] - freqs[0])
            period = 1.0 / refined_freq if refined_freq > 0 else 999
            
            peaks.append({
                'period': round(period, 1),
                'power': round(psd[i], 1),
                'relative_power': round(psd[i] / np.max(psd), 3),
            })
    
    peaks.sort(key=lambda x: x['power'], reverse=True)
    return peaks[:5]


# ============================================================
# 3. 滑动窗口自相关（时变周期检测）
# ============================================================
def time_varying_cycle(series, window=120, step=20, test_lags=range(15, 100)):
    """
    滑动窗口自相关，检测周期是否随时间变化
    返回：每个窗口的主周期
    """
    n = len(series)
    results = []
    
    for start in range(0, n - window, step):
        segment = series[start:start + window]
        mean = np.mean(segment)
        var = np.var(segment)
        if var < 1e-10:
            continue
        
        best_lag = 0
        best_acf = 0
        
        for lag in test_lags:
            if lag >= window:
                break
            cov = np.sum((segment[lag:] - mean) * (segment[:window-lag] - mean)) / window
            acf = cov / var
            if acf > best_acf:
                best_acf = acf
                best_lag = lag
        
        if best_acf > 1.96 / math.sqrt(window):
            results.append({
                'start': start,
                'end': start + window,
                'period': best_lag,
                'strength': round(best_acf, 3),
            })
    
    return results


# ============================================================
# 4. 综合周期估计（多方法融合）
# ============================================================
def estimate_rotation_cycle(closes, dates=None):
    """
    综合多种方法估计板块轮动周期
    
    方法：
    1. 自相关分析（ACF）— 基础方法
    2. 最大熵谱（Burg）— 高分辨率
    3. 滑动窗口ACF — 时变周期
    4. 去趋势后FFT — 补充验证
    
    融合逻辑：
    - 多方法一致 → 高置信度
    - 时变周期稳定 → 高置信度
    - 置信度加权平均
    """
    n = len(closes)
    if n < 100:
        return None
    
    # 预处理：去趋势
    returns = np.diff(closes) / np.array(closes[:-1])
    returns = returns - np.mean(returns)
    
    # 20日动量序列（平滑后的信号更适合周期分析）
    mom20 = np.zeros(len(returns))
    for i in range(20, len(returns)):
        cum = 1.0
        for j in range(i-20, i):
            cum *= (1 + returns[j])
        mom20[i] = (cum - 1) * 100
    mom20 = mom20[20:]
    
    results = {
        'methods': {},
        'consensus_period': None,
        'confidence': 0,
        'cycle_stability': 0,
        'current_phase': '',
        'phase_progress': 0,
    }
    
    # 方法1：自相关分析
    acf_peaks = autocorrelation_analysis(mom20, max_lag=min(150, len(mom20)//2))
    if acf_peaks:
        results['methods']['acf'] = acf_peaks
        primary = acf_peaks[0]
        results['methods']['acf_primary'] = primary
    
    # 方法2：最大熵谱估计
    burg_peaks = burg_spectrum(mom20, order=min(25, len(mom20)//4))
    if burg_peaks:
        results['methods']['burg'] = burg_peaks
        results['methods']['burg_primary'] = burg_peaks[0]
    
    # 方法3：滑动窗口时变周期
    tv_cycles = time_varying_cycle(mom20, window=100, step=15)
    if tv_cycles:
        periods = [c['period'] for c in tv_cycles]
        avg_period = np.mean(periods)
        std_period = np.std(periods)
        stability = 1.0 - min(std_period / avg_period, 1.0) if avg_period > 0 else 0
        results['methods']['time_varying'] = {
            'avg_period': round(avg_period, 1),
            'std_period': round(std_period, 1),
            'stability': round(stability, 3),
            'history': [{'period': c['period'], 'strength': c['strength']} for c in tv_cycles[-6:]],
        }
        results['cycle_stability'] = round(stability, 3)
    
    # 方法4：去趋势FFT（补充验证）
    fft_spectrum = simple_fft_verify(mom20)
    if fft_spectrum:
        results['methods']['fft'] = fft_spectrum
    
    # 融合：多方法加权
    candidates = []
    
    if 'acf_primary' in results['methods']:
        p = results['methods']['acf_primary']
        candidates.append({
            'period': p['period'],
            'weight': p['confidence'] * 0.4,
            'method': 'acf',
        })
    
    if 'burg_primary' in results['methods']:
        p = results['methods']['burg_primary']
        candidates.append({
            'period': p['period'],
            'weight': p['relative_power'] * 0.35,
            'method': 'burg',
        })
    
    if 'time_varying' in results['methods']:
        tv = results['methods']['time_varying']
        candidates.append({
            'period': tv['avg_period'],
            'weight': tv['stability'] * 0.25,
            'method': 'time_varying',
        })
    
    if candidates:
        # 加权平均
        total_weight = sum(c['weight'] for c in candidates)
        if total_weight > 0:
            consensus = sum(c['period'] * c['weight'] for c in candidates) / total_weight
            results['consensus_period'] = round(consensus, 1)
            results['confidence'] = round(min(total_weight / 1.0, 1.0), 3)
        
        # 检查方法一致性
        if len(candidates) >= 2:
            periods = [c['period'] for c in candidates]
            spread = max(periods) - min(periods)
            avg = np.mean(periods)
            agreement = 1.0 - min(spread / avg, 1.0) if avg > 0 else 0
            results['method_agreement'] = round(agreement, 3)
    
    # 计算当前所处周期阶段
    if results['consensus_period'] and len(mom20) > 20:
        period = results['consensus_period']
        # 用自相关确定当前相位
        recent = mom20[-int(period):]
        if len(recent) > 0:
            # 判断当前位置：上升/顶部/下降/底部
            recent_trend = np.polyfit(range(len(recent)), recent, 1)[0]
            recent_level = np.mean(recent[-5:])
            
            # 周期阶段判断
            # 找最近的峰值和谷值位置
            all_mom = mom20[-int(period*2):]
            peak_idx = np.argmax(all_mom)
            trough_idx = np.argmin(all_mom)
            
            cycle_pos = (len(mom20) - (len(mom20) - len(all_mom) + peak_idx)) / period
            
            if recent_trend > 0 and recent_level < 0:
                phase = '底部上升'
                progress = 25
            elif recent_trend > 0 and recent_level > 0:
                phase = '上升中'
                progress = 50
            elif recent_trend < 0 and recent_level > 0:
                phase = '顶部下降'
                progress = 75
            elif recent_trend < 0 and recent_level < 0:
                phase = '下降中'
                progress = 90
            else:
                phase = '过渡期'
                progress = 50
            
            results['current_phase'] = phase
            results['phase_progress'] = progress
            
            # 预测下一个买点/卖点
            if phase in ['下降中', '顶部下降']:
                # 预计还需多少天到买点
                days_to_buy = int(period * (1 - progress / 100))
                results['next_buy_estimate'] = f"约{days_to_buy}个交易日后"
            elif phase in ['底部上升', '上升中']:
                days_to_sell = int(period * (1 - progress / 100))
                results['next_sell_estimate'] = f"约{days_to_sell}个交易日后"
    
    return results


def simple_fft_verify(series):
    """FFT验证（带去趋势）"""
    n = len(series)
    if n < 30:
        return []
    
    # 去线性趋势
    x = np.arange(n)
    slope, intercept = np.polyfit(x, series, 1)
    detrended = series - (slope * x + intercept)
    
    # FFT
    fft = np.fft.rfft(detrended)
    power = np.abs(fft)**2 / n
    freqs = np.fft.rfftfreq(n)
    
    peaks = []
    for i in range(2, len(power) - 2):
        if power[i] > power[i-1] and power[i] > power[i+1] and freqs[i] > 0:
            period = 1.0 / freqs[i] if freqs[i] > 0 else 999
            if 15 < period < 300:
                peaks.append({
                    'period': round(period, 1),
                    'power': round(power[i], 1),
                    'relative_power': round(power[i] / np.max(power[1:]), 3),
                })
    
    peaks.sort(key=lambda x: x['power'], reverse=True)
    return peaks[:3]


# ============================================================
# 5. 批量计算所有板块
# ============================================================
def compute_all_cycles(sector_data):
    """对所有板块计算轮动周期"""
    results = {}
    for name, data in sector_data.items():
        closes = np.array(data['closes'], dtype=np.float64)
        cycle = estimate_rotation_cycle(closes, data.get('dates'))
        if cycle:
            results[name] = cycle
    return results


if __name__ == '__main__':
    # 测试
    test = np.sin(np.linspace(0, 8*math.pi, 500)) * 10 + np.random.randn(500) * 2
    result = estimate_rotation_cycle(test)
    print(f"合成信号测试（理论周期≈125天）:")
    print(f"  共识周期: {result['consensus_period']}天")
    print(f"  置信度: {result['confidence']}")
    print(f"  方法一致性: {result.get('method_agreement', 'N/A')}")
    print(f"  当前阶段: {result['current_phase']}")
    print(f"  各方法:")
    for method, data in result['methods'].items():
        if isinstance(data, dict) and 'period' in data:
            print(f"    {method}: {data['period']}天")
        elif isinstance(data, list):
            print(f"    {method}: {data[0]['period']}天" if data else f"    {method}: 无结果")
