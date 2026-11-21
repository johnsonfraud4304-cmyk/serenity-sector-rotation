#!/usr/bin/env python3
"""
高级分析引擎 — 多因子信号、回撤、相对强度、市场宽度、组合构建
"""

import math, json
from datetime import datetime


# ============================================================
# 1. MACD指标
# ============================================================
def compute_ema(series, period):
    if not series:
        return []
    ema = [series[0]]
    k = 2 / (period + 1)
    for i in range(1, len(series)):
        ema.append(series[i] * k + ema[-1] * (1 - k))
    return ema


def compute_macd(closes, fast=12, slow=26, signal=9):
    ema_fast = compute_ema(closes, fast)
    ema_slow = compute_ema(closes, slow)
    dif = [f - s for f, s in zip(ema_fast, ema_slow)]
    dea = compute_ema(dif, signal)
    macd_hist = [2 * (d - e) for d, e in zip(dif, dea)]
    return {
        'dif': round(dif[-1], 4) if dif else 0,
        'dea': round(dea[-1], 4) if dea else 0,
        'hist': round(macd_hist[-1], 4) if macd_hist else 0,
        'golden_cross': dif[-1] > dea[-1] and dif[-2] <= dea[-2] if len(dif) > 1 else False,
        'dead_cross': dif[-1] < dea[-1] and dif[-2] >= dea[-2] if len(dif) > 1 else False,
    }


# ============================================================
# 2. 布林带
# ============================================================
def compute_bollinger(closes, period=20, num_std=2):
    if len(closes) < period:
        return {'upper': 0, 'middle': 0, 'lower': 0, 'width': 0, 'position': 0.5}
    window = closes[-period:]
    middle = sum(window) / period
    variance = sum((x - middle) ** 2 for x in window) / period
    std = math.sqrt(variance)
    upper = middle + num_std * std
    lower = middle - num_std * std
    width = (upper - lower) / middle * 100 if middle > 0 else 0
    position = (closes[-1] - lower) / (upper - lower) if (upper - lower) > 0 else 0.5
    return {
        'upper': round(upper, 4),
        'middle': round(middle, 4),
        'lower': round(lower, 4),
        'width': round(width, 2),
        'position': round(position, 3),
        'squeeze': width < 5,
    }


# ============================================================
# 3. 成交量分析
# ============================================================
def compute_volume_analysis(volumes, closes):
    if not volumes or len(volumes) < 20:
        return {'vol_ratio': 1, 'trend': 'neutral', 'price_vol_divergence': False}
    avg_vol = sum(volumes[-20:]) / 20
    current_vol = volumes[-1]
    vol_ratio = current_vol / avg_vol if avg_vol > 0 else 1
    vol_5d = sum(volumes[-5:]) / 5
    vol_20d = avg_vol
    trend = '放量' if vol_5d > vol_20d * 1.2 else '缩量' if vol_5d < vol_20d * 0.8 else '平量'
    price_up = closes[-1] > closes[-5] if len(closes) > 5 else True
    divergence = (price_up and trend == '缩量') or (not price_up and trend == '放量')
    return {
        'vol_ratio': round(vol_ratio, 2),
        'trend': trend,
        'price_vol_divergence': divergence,
    }


# ============================================================
# 4. 回撤分析
# ============================================================
def compute_drawdown_analysis(closes):
    if len(closes) < 2:
        return {'max_drawdown': 0, 'current_drawdown': 0, 'peak': 0, 'trough': 0, 'recovery_pct': 100}
    peak = closes[0]
    max_dd = 0
    peak_idx = 0
    trough_idx = 0
    for i, c in enumerate(closes):
        if c > peak:
            peak = c
            peak_idx = i
        dd = (peak - c) / peak * 100
        if dd > max_dd:
            max_dd = dd
            trough_idx = i

    current_peak = max(closes)
    current_dd = (current_peak - closes[-1]) / current_peak * 100

    # Recovery from max drawdown
    trough_price = closes[trough_idx]
    recovery_pct = 0
    if max_dd > 0:
        recovery_pct = (closes[-1] - trough_price) / (peak - trough_price) * 100 if peak > trough_price else 0

    return {
        'max_drawdown': round(max_dd, 2),
        'current_drawdown': round(current_dd, 2),
        'peak_price': round(current_peak, 4),
        'recovery_pct': round(min(100, max(0, recovery_pct)), 1),
    }


# ============================================================
# 5. 相对强度 (vs 沪深300)
# ============================================================
def compute_relative_strength(sector_closes, benchmark_closes):
    if len(sector_closes) < 20 or len(benchmark_closes) < 20:
        return {'rs_20d': 0, 'rs_60d': 0, 'rs_rank': '中性'}
    ml = min(len(sector_closes), len(benchmark_closes))
    sc = sector_closes[-ml:]
    bc = benchmark_closes[-ml:]

    # 20日相对强度
    sec_ret_20 = (sc[-1] / sc[-20] - 1) * 100 if sc[-20] > 0 else 0
    bench_ret_20 = (bc[-1] / bc[-20] - 1) * 100 if bc[-20] > 0 else 0
    rs_20d = sec_ret_20 - bench_ret_20

    # 60日相对强度
    if ml >= 60:
        sec_ret_60 = (sc[-1] / sc[-60] - 1) * 100 if sc[-60] > 0 else 0
        bench_ret_60 = (bc[-1] / bc[-60] - 1) * 100 if bc[-60] > 0 else 0
        rs_60d = sec_ret_60 - bench_ret_60
    else:
        rs_60d = rs_20d

    if rs_20d > 3 and rs_60d > 0:
        rank = '强势领涨'
    elif rs_20d > 0 and rs_60d > 0:
        rank = '温和偏强'
    elif rs_20d < -3 and rs_60d < 0:
        rank = '弱势落后'
    elif rs_20d < 0 and rs_60d < 0:
        rank = '温和偏弱'
    elif rs_20d > 0 and rs_60d < 0:
        rank = '短期反弹'
    else:
        rank = '短期回调'

    return {
        'rs_20d': round(rs_20d, 2),
        'rs_60d': round(rs_60d, 2),
        'rank': rank,
    }


# ============================================================
# 6. 市场宽度
# ============================================================
def compute_market_breadth(sectors):
    if not sectors:
        return {}
    total = len(sectors)
    above_ma20 = sum(1 for s in sectors.values() if s.get('bias_20', 0) > 0)
    above_ma60 = sum(1 for s in sectors.values() if s.get('bias_60', 0) > 0)
    rising = sum(1 for s in sectors.values() if s.get('mom_20', 0) > 0)
    oversold = sum(1 for s in sectors.values() if s.get('rsi', 50) < 30)
    overbought = sum(1 for s in sectors.values() if s.get('rsi', 50) > 70)
    avg_rsi = sum(s.get('rsi', 50) for s in sectors.values()) / total
    avg_mom = sum(s.get('mom_20', 0) for s in sectors.values()) / total

    # Phase distribution
    phases = {}
    for s in sectors.values():
        p = s.get('phase', '未知')
        phases[p] = phases.get(p, 0) + 1

    return {
        'total': total,
        'above_ma20': above_ma20,
        'above_ma20_pct': round(above_ma20 / total * 100, 1),
        'above_ma60': above_ma60,
        'above_ma60_pct': round(above_ma60 / total * 100, 1),
        'rising': rising,
        'rising_pct': round(rising / total * 100, 1),
        'oversold': oversold,
        'overbought': overbought,
        'avg_rsi': round(avg_rsi, 1),
        'avg_mom': round(avg_mom, 2),
        'phase_distribution': phases,
    }


# ============================================================
# 7. 综合信号评分 (多因子融合)
# ============================================================
def compute_composite_signal(s, macd=None, bollinger=None, volume=None, drawdown=None, rs=None, dl=None):
    """
    多因子综合信号评分 (-100 ~ +100)
    正值=看多, 负值=看空, 绝对值越大信号越强
    """
    score = 0
    factors = []

    # 1. RSI (权重25分)
    rsi = s.get('rsi', 50)
    if rsi < 25:
        rsi_score = 25
        factors.append(('RSI超卖', 25, '#22c55e'))
    elif rsi < 35:
        rsi_score = 15
        factors.append(('RSI偏低', 15, '#22c55e'))
    elif rsi > 75:
        rsi_score = -25
        factors.append(('RSI超买', -25, '#ef4444'))
    elif rsi > 65:
        rsi_score = -15
        factors.append(('RSI偏高', -15, '#ef4444'))
    else:
        rsi_score = 0
        factors.append(('RSI中性', 0, '#6b7280'))
    score += rsi_score

    # 2. 动量 (权重25分)
    mom20 = s.get('mom_20', 0)
    mom60 = s.get('mom_60', 0)
    if mom20 > 5 and mom60 > 5:
        mom_score = 20
        factors.append(('双周期强势', 20, '#22c55e'))
    elif mom20 > 0 and mom60 > 0:
        mom_score = 10
        factors.append(('趋势向上', 10, '#22c55e'))
    elif mom20 > 0 and mom60 < 0:
        mom_score = 5
        factors.append(('短期反弹', 5, '#f59e0b'))
    elif mom20 < -5 and mom60 < -5:
        mom_score = -20
        factors.append(('双周期弱势', -20, '#ef4444'))
    elif mom20 < 0 and mom60 < 0:
        mom_score = -10
        factors.append(('趋势向下', -10, '#ef4444'))
    else:
        mom_score = 0
        factors.append(('动量中性', 0, '#6b7280'))
    score += mom_score

    # 3. MACD (权重20分)
    if macd:
        if macd.get('golden_cross'):
            macd_score = 20
            factors.append(('MACD金叉', 20, '#22c55e'))
        elif macd.get('dead_cross'):
            macd_score = -20
            factors.append(('MACD死叉', -20, '#ef4444'))
        elif macd.get('hist', 0) > 0:
            macd_score = 8
            factors.append(('MACD柱正', 8, '#22c55e'))
        else:
            macd_score = -8
            factors.append(('MACD柱负', -8, '#ef4444'))
        score += macd_score

    # 4. 布林带位置 (权重15分)
    if bollinger:
        pos = bollinger.get('position', 0.5)
        if pos < 0.1:
            bb_score = 15
            factors.append(('布林带底部', 15, '#22c55e'))
        elif pos < 0.3:
            bb_score = 8
            factors.append(('布林带偏低', 8, '#22c55e'))
        elif pos > 0.9:
            bb_score = -15
            factors.append(('布林带顶部', -15, '#ef4444'))
        elif pos > 0.7:
            bb_score = -8
            factors.append(('布林带偏高', -8, '#ef4444'))
        else:
            bb_score = 0
            factors.append(('布林带中性', 0, '#6b7280'))
        score += bb_score

    # 5. 量价配合 (权重10分)
    if volume:
        if volume.get('price_vol_divergence'):
            vol_score = -8
            factors.append(('量价背离', -8, '#f59e0b'))
        elif volume.get('trend') == '放量' and mom20 > 0:
            vol_score = 10
            factors.append(('放量上涨', 10, '#22c55e'))
        elif volume.get('trend') == '缩量' and mom20 < 0:
            vol_score = 5
            factors.append(('缩量下跌', 5, '#f59e0b'))
        else:
            vol_score = 0
            factors.append(('量能正常', 0, '#6b7280'))
        score += vol_score

    # 6. 相对强度 (权重5分)
    if rs:
        rs_20 = rs.get('rs_20d', 0)
        if rs_20 > 3:
            rs_score = 5
            factors.append(('跑赢大盘', 5, '#22c55e'))
        elif rs_20 < -3:
            rs_score = -5
            factors.append(('跑输大盘', -5, '#ef4444'))
        else:
            rs_score = 0
            factors.append(('同步大盘', 0, '#6b7280'))
        score += rs_score

    # Normalize to -100 ~ +100
    score = max(-100, min(100, score))

    # Signal interpretation
    if score >= 50:
        signal = '强烈看多'
        color = '#22c55e'
        action = '重仓买入'
    elif score >= 25:
        signal = '看多'
        color = '#4ade80'
        action = '分批建仓'
    elif score >= 10:
        signal = '偏多'
        color = '#86efac'
        action = '轻仓试探'
    elif score <= -50:
        signal = '强烈看空'
        color = '#ef4444'
        action = '清仓回避'
    elif score <= -25:
        signal = '看空'
        color = '#f87171'
        action = '减仓止盈'
    elif score <= -10:
        signal = '偏空'
        color = '#fca5a5'
        action = '观望等待'
    else:
        signal = '中性'
        color = '#9ca3af'
        action = '持有不动'

    return {
        'score': score,
        'signal': signal,
        'color': color,
        'action': action,
        'factors': factors,
    }


# ============================================================
# 8. 组合构建建议
# ============================================================
def build_portfolio(sectors, method='risk_parity'):
    """
    根据板块数据构建投资组合
    method: 'equal_weight' | 'momentum' | 'risk_parity' | 'composite'
    """
    candidates = []
    for name, s in sectors.items():
        cs = s.get('composite_signal', {})
        score = cs.get('score', 0)
        if score > 0:
            candidates.append({
                'name': name,
                'score': score,
                'rsi': s.get('rsi', 50),
                'mom_20': s.get('mom_20', 0),
                'category': s.get('category', ''),
                'color': s.get('color', '#666'),
                'drawdown': s.get('drawdown', {}).get('current_drawdown', 0),
            })

    if not candidates:
        return {'method': method, 'allocations': [], 'total_score': 0}

    # Sort by score
    candidates.sort(key=lambda x: x['score'], reverse=True)

    if method == 'equal_weight':
        w = round(100 / len(candidates), 1)
        for c in candidates:
            c['weight'] = w

    elif method == 'momentum':
        total_score = sum(max(0, c['score']) for c in candidates)
        for c in candidates:
            c['weight'] = round(max(0, c['score']) / total_score * 100, 1) if total_score > 0 else 0

    elif method == 'risk_parity':
        # Inverse volatility weighting
        inv_vols = []
        for c in candidates:
            rsi = c['rsi']
            vol_proxy = abs(c['mom_20']) + 10
            inv_vols.append(1 / vol_proxy)
        total_inv = sum(inv_vols)
        for c, iv in zip(candidates, inv_vols):
            c['weight'] = round(iv / total_inv * 100, 1) if total_inv > 0 else 0

    elif method == 'composite':
        total = 0
        for c in candidates:
            # Score-based with drawdown adjustment
            adj_score = max(0, c['score']) * (1 - c['drawdown'] / 100 * 0.3)
            c['adj_score'] = adj_score
            total += adj_score
        for c in candidates:
            c['weight'] = round(c.get('adj_score', 0) / total * 100, 1) if total > 0 else 0

    # Limit to top 10
    top = candidates[:10]
    total_weight = sum(c['weight'] for c in top)
    if total_weight > 0:
        for c in top:
            c['weight'] = round(c['weight'] / total_weight * 100, 1)

    return {
        'method': method,
        'allocations': top,
        'total_score': round(sum(c['score'] * c['weight'] / 100 for c in top), 1),
    }


# ============================================================
# 9. 运行全部高级分析
# ============================================================
def run_advanced_analysis(sectors, benchmark_closes=None):
    """
    对所有板块运行高级分析，增强sectors数据
    """
    # Find benchmark (沪深300)
    if benchmark_closes is None:
        for name, s in sectors.items():
            if '沪深300' in name:
                benchmark_closes = s.get('closes', [])
                break

    # Market breadth
    breadth = compute_market_breadth(sectors)

    enhanced = {}
    for name, s in sectors.items():
        closes = s.get('closes', [])
        if len(closes) < 30:
            enhanced[name] = s
            continue

        # MACD
        macd = compute_macd(closes)

        # Bollinger
        bollinger = compute_bollinger(closes)

        # Drawdown
        drawdown = compute_drawdown_analysis(closes)

        # Relative strength
        rs = compute_relative_strength(closes, benchmark_closes) if benchmark_closes else None

        # Composite signal
        composite = compute_composite_signal(s, macd, bollinger, None, drawdown, rs, s.get('dl'))

        enhanced[name] = {
            **s,
            'macd': macd,
            'bollinger': bollinger,
            'drawdown': drawdown,
            'relative_strength': rs,
            'composite_signal': composite,
        }

    # Portfolio construction
    portfolios = {
        'equal_weight': build_portfolio(enhanced, 'equal_weight'),
        'momentum': build_portfolio(enhanced, 'momentum'),
        'risk_parity': build_portfolio(enhanced, 'risk_parity'),
        'composite': build_portfolio(enhanced, 'composite'),
    }

    return enhanced, breadth, portfolios
