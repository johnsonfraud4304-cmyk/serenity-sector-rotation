#!/usr/bin/env python3
"""
A股板块轮动分析仪 — 数据引擎 v3
支持45+只ETF，实时行情+自动获取+缓存+回退
"""

import json, os, math, time, subprocess
from datetime import datetime, timedelta
from etf_config import ETF_LIST, SECTOR_COLORS, get_etfs_by_category

CACHE_DIR = os.path.join(os.path.dirname(__file__), 'etf_cache')
OUTPUT_FILE = os.path.join(os.path.dirname(__file__), 'analysis_data.json')

os.makedirs(CACHE_DIR, exist_ok=True)

# ============================================================
# 0. 交易时间判断
# ============================================================
def is_market_hours():
    """判断当前是否为A股交易时间（北京时间 9:15-15:05）"""
    try:
        import pytz
        tz = pytz.timezone('Asia/Shanghai')
        now = datetime.now(tz)
    except ImportError:
        # 无pytz时用UTC+8近似
        now = datetime.utcnow() + timedelta(hours=8)
    
    weekday = now.weekday()
    if weekday >= 5:  # 周末
        return False
    
    t = now.hour * 100 + now.minute
    return 915 <= t <= 1505


def get_cache_ttl():
    """根据交易时间返回缓存有效期（秒）"""
    if is_market_hours():
        return 300  # 交易时段5分钟
    return 86400  # 非交易时段24小时


# ============================================================
# 1. 实时行情获取
# ============================================================
def fetch_realtime_tencent(codes):
    """
    从腾讯实时行情API批量获取当前价格
    codes: ['sh510300', 'sz159915', ...]
    返回: {code: {'price': float, 'open': float, 'high': float, 'low': float, 'volume': int, 'time': str}}
    """
    if not codes:
        return {}
    
    results = {}
    # 腾讯API一次最多请求约50只
    batch_size = 50
    for i in range(0, len(codes), batch_size):
        batch = codes[i:i+batch_size]
        query = ','.join(batch)
        url = f'https://web.sqt.gtimg.cn/q={query}'
        try:
            r = subprocess.run(
                ['curl', '-s', '--max-time', '8',
                 '-H', 'User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)',
                 url],
                capture_output=True, timeout=12
            )
            text = r.stdout.decode('gbk', errors='ignore')
            for line in text.strip().split('\n'):
                if '=' not in line or '~' not in line:
                    continue
                var_part, val_part = line.split('=', 1)
                code = var_part.replace('v_', '').strip()
                fields = val_part.strip('";').split('~')
                if len(fields) < 45:
                    continue
                try:
                    price = float(fields[3])
                    if price <= 0:
                        continue
                    results[code] = {
                        'price': price,
                        'prev_close': float(fields[4]) if fields[4] else price,
                        'open': float(fields[5]) if fields[5] else price,
                        'high': float(fields[33]) if fields[33] else price,
                        'low': float(fields[34]) if fields[34] else price,
                        'volume': int(float(fields[6])) if fields[6] else 0,
                        'amount': float(fields[37]) if fields[37] else 0,
                        'time': fields[30] if len(fields) > 30 else '',
                    }
                except (ValueError, IndexError):
                    continue
        except Exception:
            continue
        time.sleep(0.02)
    
    return results


def fetch_realtime_eastmoney(codes):
    """
    从东方财富实时行情API批量获取（备用）
    codes: ['sh510300', 'sz159915', ...]
    返回: {code: {'price': float, ...}}
    """
    if not codes:
        return {}
    
    results = {}
    # 构造secid列表: sh510300 -> 1.510300, sz159915 -> 0.159915
    secids = []
    code_map = {}
    for code in codes:
        if code.startswith('sh'):
            secid = f"1.{code[2:]}"
        else:
            secid = f"0.{code[2:]}"
        secids.append(secid)
        code_map[secid] = code
    
    batch_size = 50
    for i in range(0, len(secids), batch_size):
        batch = secids[i:i+batch_size]
        fields = 'f2,f3,f4,f12,f14,f15,f16,f17,f18'
        url = f'https://push2.eastmoney.com/api/qt/ulist/get?secids={",".join(batch)}&fields={fields}'
        try:
            r = subprocess.run(
                ['curl', '-s', '--max-time', '8',
                 '-H', 'User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)',
                 url],
                capture_output=True, timeout=12
            )
            data = json.loads(r.stdout)
            for item in data.get('data', {}).get('diff', []):
                secid = f"{item.get('f13','')}.{item.get('f12','')}"
                code = code_map.get(secid)
                if not code:
                    continue
                price = item.get('f2', 0)
                if price and price > 0:
                    results[code] = {
                        'price': price / 100 if price > 1000 else price,
                        'open': item.get('f17', 0) / 100,
                        'high': item.get('f15', 0) / 100,
                        'low': item.get('f16', 0) / 100,
                        'prev_close': item.get('f18', 0) / 100,
                        'volume': 0,
                        'amount': 0,
                        'time': '',
                    }
        except Exception:
            continue
        time.sleep(0.02)
    
    return results


# ============================================================
# 2. 日K线获取
# ============================================================
def fetch_kline_tencent(code, count=500):
    """从腾讯财经API获取日K线（GBK编码处理）"""
    url = f'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?_var=kline_dayfq&param={code},day,,,{count},qfq'
    try:
        r = subprocess.run(
            ['curl', '-s', '--max-time', '10',
             '-H', 'User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)',
             url],
            capture_output=True, timeout=15
        )
        data = r.stdout.decode('gbk', errors='ignore')
        if len(data) < 50:
            return None
        idx = data.index('{')
        d = json.loads(data[idx:])
        stock_key = list(d.get('data', {}).keys())[0]
        stock_data = d['data'][stock_key]
        klines = stock_data.get('day', stock_data.get('qfqday', []))
        return klines
    except Exception as e:
        return None


def load_or_fetch(code, name):
    """加载缓存或从网络获取，支持实时行情更新"""
    cache_file = os.path.join(CACHE_DIR, f'{code}.json')
    cache_ttl = get_cache_ttl()
    
    # 读取现有缓存
    cached_data = None
    if os.path.exists(cache_file):
        try:
            with open(cache_file) as f:
                cached_data = json.load(f)
        except:
            cached_data = None
    
    # 检查缓存是否新鲜
    cache_fresh = False
    if cached_data and len(cached_data) > 50:
        age = time.time() - os.path.getmtime(cache_file)
        if age < cache_ttl:
            cache_fresh = True
    
    if cache_fresh:
        return cached_data
    
    # 缓存过期，从网络获取日K线
    klines = fetch_kline_tencent(code)
    if klines and len(klines) > 50:
        with open(cache_file, 'w') as f:
            json.dump(klines, f)
        return klines
    
    # 回退到旧缓存
    if cached_data and len(cached_data) > 50:
        return cached_data
    
    # 回退到代理数据
    proxy_file = os.path.join(CACHE_DIR, f'proxy_{name}.json')
    if os.path.exists(proxy_file):
        try:
            with open(proxy_file) as f:
                data = json.load(f)
            if data and len(data) > 50:
                return data
        except:
            pass
    
    return None


def merge_realtime_to_klines(klines, realtime_info, code):
    """将实时行情合并到K线数据末尾，用于当日盘中分析"""
    if not klines or not realtime_info:
        return klines
    
    today = datetime.now().strftime('%Y-%m-%d')
    last_date = klines[-1][0] if klines else ''
    
    price = realtime_info.get('price', 0)
    if price <= 0:
        return klines
    
    # 如果最后一条已经是今天，更新它；否则追加新条目
    if last_date == today:
        # 更新今日数据为实时价格
        klines[-1][2] = str(price)  # 收盘价 = 当前价
        klines[-1][3] = str(realtime_info.get('high', price))  # 最高价
        klines[-1][4] = str(realtime_info.get('low', price))   # 最低价
    else:
        # 追加今日实时数据作为新K线
        open_price = realtime_info.get('open', price)
        high_price = realtime_info.get('high', price)
        low_price = realtime_info.get('low', price)
        klines.append([today, str(open_price), str(price), str(high_price), str(low_price)])
    
    return klines


def parse_klines(klines):
    """解析K线数据为收盘价和日期"""
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
    return closes, dates


# ============================================================
# 2. 数学分析函数
# ============================================================
def compute_returns(closes):
    return [(closes[i] - closes[i-1]) / closes[i-1] for i in range(1, len(closes))]


def rolling_momentum(rets, window=20):
    mom = []
    for i in range(window, len(rets)):
        cum = 1.0
        for j in range(i - window, i):
            cum *= (1 + rets[j])
        mom.append((cum - 1) * 100)
    return mom


def simple_fft(series, max_freq=50):
    n = len(series)
    if n < 10:
        return []
    mean = sum(series) / n
    centered = [x - mean for x in series]
    power = []
    for k in range(1, min(max_freq, n // 2)):
        cos_sum = sum(centered[t] * math.cos(2 * math.pi * k * t / n) for t in range(n))
        sin_sum = sum(centered[t] * math.sin(2 * math.pi * k * t / n) for t in range(n))
        p = (cos_sum**2 + sin_sum**2) / n
        period = n / k
        power.append({'period': round(period, 1), 'power': round(p, 1)})
    return sorted(power, key=lambda x: x['power'], reverse=True)[:5]


def compute_rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50
    gains, losses = [], []
    for i in range(1, len(closes)):
        change = closes[i] - closes[i-1]
        gains.append(max(0, change))
        losses.append(max(0, -change))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def compute_ma(closes, period):
    if len(closes) < period:
        return closes[-1] if closes else 0
    return sum(closes[-period:]) / period


def classify_phase(mom_20, mom_60, rsi):
    if mom_20 > 5 and mom_60 > 10 and rsi > 65:
        return '顶部区', '#FF4444', '减仓/止盈'
    elif mom_20 > 0 and mom_60 > 0:
        return '上升期', '#44AA44', '持有/加仓'
    elif mom_20 < -5 and mom_60 < -10 and rsi < 35:
        return '底部区', '#4444FF', '建仓/抄底'
    elif mom_20 < 0 and mom_60 < 0:
        return '下降期', '#AAAA00', '观望/减仓'
    elif mom_20 > 0 and mom_60 < 0:
        return '反弹期', '#FF8800', '短线/试探'
    else:
        return '震荡期', '#888888', '观望'


def compute_seasonal(rets, dates):
    monthly = {m: [] for m in range(1, 13)}
    for i, r in enumerate(rets):
        if i + 1 < len(dates):
            try:
                month = int(dates[i + 1][5:7])
                monthly[month].append(r)
            except:
                pass
    return {m: round(sum(d)/len(d)*100, 3) if d else 0 for m, d in monthly.items()}


def compute_potential_score(s, seasonal, dl=None, spectrum=None):
    """
    计算板块上涨潜力评分（百分制）
    
    维度及权重：
    1. 技术面超卖程度 (30分) — RSI越低、偏离越负 → 分越高
    2. 动量反转信号 (25分) — 底部+动量触底回升 → 分高
    3. 深度学习预测 (25分) — AI预测动量、轮动得分
    4. 季节性加分 (10分) — 当前月份历史表现
    5. 周期位置 (10分) — FFT主周期阶段
    """
    score = 0
    
    # ── 维度1: 技术面超卖 (30分) ──
    # RSI: 30以下满分，30-50线性，50以上递减
    rsi = s.get('rsi', 50)
    if rsi < 20:
        rsi_score = 30
    elif rsi < 30:
        rsi_score = 25 + (30 - rsi) * 0.5
    elif rsi < 40:
        rsi_score = 15 + (40 - rsi) * 1.0
    elif rsi < 50:
        rsi_score = 5 + (50 - rsi) * 1.0
    elif rsi < 70:
        rsi_score = max(0, 5 - (rsi - 50) * 0.25)
    else:
        rsi_score = 0
    score += rsi_score
    
    # MA20偏离: 越负越有反弹空间（满分附加到RSI里）
    bias = s.get('bias_20', 0)
    if bias < -10:
        bias_score = 5
    elif bias < -5:
        bias_score = 3 + (-5 - bias) * 0.4
    elif bias < 0:
        bias_score = (0 - bias) * 0.6
    else:
        bias_score = 0
    score += min(bias_score, 5)
    
    # ── 维度2: 动量反转 (25分) ──
    mom20 = s.get('mom_20', 0)
    mom60 = s.get('mom_60', 0)
    phase = s.get('phase', '')
    
    # 底部区 + 动量触底 = 高分
    if phase == '底部区':
        phase_score = 15
    elif phase == '下降期' and mom20 > -15:
        phase_score = 10  # 下降末期
    elif phase == '上升期':
        phase_score = 8   # 已在上升但还有空间
    elif phase == '反弹期':
        phase_score = 6
    elif phase == '震荡期':
        phase_score = 4
    elif phase == '顶部区':
        phase_score = 0
    else:
        phase_score = 3
    score += phase_score
    
    # 动量加速度：20日比60日好转 → 触底回升信号
    if mom20 > mom60 and mom20 < 0:
        accel_score = 5  # 动量好转但还没涨
    elif mom20 > 0 and mom60 < 0:
        accel_score = 3  # 反弹初期
    elif mom20 > 0 and mom60 > 0:
        accel_score = 2  # 已在上升
    else:
        accel_score = 0
    score += min(accel_score, 5)
    
    # ── 维度3: 深度学习预测 (25分) ──
    if dl:
        # 预测动量 (15分)
        pred_mom = dl.get('pred_mom', 0)
        if pred_mom > 5:
            mom_dl_score = 15
        elif pred_mom > 2:
            mom_dl_score = 10 + (pred_mom - 2) * 1.67
        elif pred_mom > 0:
            mom_dl_score = 5 + pred_mom * 2.5
        elif pred_mom > -3:
            mom_dl_score = max(0, 5 + pred_mom * 1.5)
        else:
            mom_dl_score = 0
        score += mom_dl_score
        
        # 轮动得分 (5分)
        rot_score = dl.get('rotation_score', 0)
        score += min(rot_score * 200, 5)  # 0.025 → 5分
        
        # 预测置信度 (5分)
        conf = dl.get('confidence', 0)
        pred_phase = dl.get('pred_phase', '')
        if pred_phase in ['底部区', '上升期']:
            score += conf * 5
    else:
        score += 10  # 无DL数据时给中间分
    
    # ── 维度4: 季节性 (10分) ──
    from datetime import datetime
    current_month = datetime.now().month
    if seasonal and current_month in seasonal:
        month_perf = seasonal[current_month]
        if month_perf > 0.5:
            seasonal_score = 10
        elif month_perf > 0.2:
            seasonal_score = 7
        elif month_perf > 0:
            seasonal_score = 4
        elif month_perf > -0.2:
            seasonal_score = 2
        else:
            seasonal_score = 0
        score += seasonal_score
    else:
        score += 5
    
    # ── 维度5: 周期位置 (10分) ──
    if spectrum and len(spectrum) > 0:
        # 主周期越短 → 轮动越频繁 → 越快到买点
        main_period = spectrum[0].get('period', 100)
        if main_period < 50:
            cycle_score = 8   # 短周期，频繁轮动
        elif main_period < 80:
            cycle_score = 6
        elif main_period < 120:
            cycle_score = 4
        else:
            cycle_score = 2
        score += cycle_score
    else:
        score += 5
    
    return min(100, max(0, round(score)))


def compute_corr_matrix(all_returns):
    names = list(all_returns.keys())
    n = len(names)
    matrix = []
    for i in range(n):
        row = []
        for j in range(n):
            s1 = all_returns[names[i]]
            s2 = all_returns[names[j]]
            ml = min(len(s1), len(s2))
            if ml < 20:
                row.append(0)
                continue
            s1, s2 = s1[:ml], s2[:ml]
            m1 = sum(s1) / ml
            m2 = sum(s2) / ml
            cov = sum((s1[k]-m1)*(s2[k]-m2) for k in range(ml)) / ml
            v1 = sum((x-m1)**2 for x in s1) / ml
            v2 = sum((x-m2)**2 for x in s2) / ml
            corr = cov / math.sqrt(v1 * v2) if v1 > 0 and v2 > 0 else 0
            row.append(round(corr, 3))
        matrix.append(row)
    return {'sectors': names, 'matrix': matrix}


# ============================================================
# 3. 主分析流程
# ============================================================
def run_analysis():
    print("=" * 60)
    print("A股板块轮动分析引擎 v3 (实时行情)")
    print("=" * 60)
    
    market_open = is_market_hours()
    print(f"当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"交易时段: {'是' if market_open else '否'}")
    
    # 批量获取实时行情（交易时段）
    realtime_data = {}
    if market_open:
        all_codes = [code for name, (code, _, _) in ETF_LIST.items()]
        print(f"\n获取 {len(all_codes)} 只ETF实时行情...")
        realtime_data = fetch_realtime_tencent(all_codes)
        if not realtime_data:
            realtime_data = fetch_realtime_eastmoney(all_codes)
        print(f"  实时行情: {len(realtime_data)}/{len(all_codes)} 只成功")
    
    # 获取所有ETF日K线数据
    all_etf_data = {}
    success_count = 0
    
    for name, (code, full_name, category) in ETF_LIST.items():
        klines = load_or_fetch(code, name)
        
        # 交易时段：将实时行情合并到K线
        if market_open and code in realtime_data and klines:
            klines = merge_realtime_to_klines(klines, realtime_data[code], code)
        
        if klines and len(klines) > 100:
            closes, dates = parse_klines(klines)
            if len(closes) > 100:
                all_etf_data[name] = {
                    'closes': closes,
                    'dates': dates,
                    'code': code,
                    'full_name': full_name,
                    'category': category,
                    'color': SECTOR_COLORS.get(category, '#6b7280'),
                    'realtime': realtime_data.get(code),
                }
                success_count += 1
                rt_tag = " [实时]" if code in realtime_data else ""
                print(f"  ✓ {name:<10} {code:<12} {len(closes)}条K线{rt_tag}")
            else:
                print(f"  ✗ {name:<10} {code:<12} 数据不足")
        else:
            print(f"  ✗ {name:<10} {code:<12} 获取失败")
        time.sleep(0.05)
    
    print(f"\n成功获取 {success_count}/{len(ETF_LIST)} 只ETF数据")
    
    if success_count < 5:
        print("数据不足，尝试使用本地缓存...")
        # 尝试从旧缓存加载
        for name, (code, full_name, category) in ETF_LIST.items():
            if name in all_etf_data:
                continue
            cache_file = os.path.join(CACHE_DIR, f'{code}.json')
            if os.path.exists(cache_file):
                with open(cache_file) as f:
                    klines = json.load(f)
                if klines and len(klines) > 100:
                    closes, dates = parse_klines(klines)
                    if len(closes) > 100:
                        all_etf_data[name] = {
                            'closes': closes, 'dates': dates,
                            'code': code, 'full_name': full_name,
                            'category': category,
                            'color': SECTOR_COLORS.get(category, '#6b7280'),
                        }
                        success_count += 1
    
    # 确定共同长度
    min_len = min(len(d['closes']) for d in all_etf_data.values())
    min_len = min(min_len, 600)
    
    results = {
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'data_range': '',
        'total_etfs': len(ETF_LIST),
        'loaded_etfs': success_count,
        'categories': get_etfs_by_category(),
        'sectors': {},
        'rotation_history': [],
        'correlation_matrix': {},
        'signals': [],
        'realtime_mode': market_open,
        'realtime_count': len(realtime_data),
    }
    
    all_returns = {}
    
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
        
        # 计算上涨潜力评分（DL数据后续合并时补充）
        temp_result = {
            'rsi': round(rsi, 1),
            'mom_20': round(current_mom_20, 2),
            'mom_60': round(current_mom_60, 2),
            'bias_20': round(bias_20, 2),
            'phase': phase,
        }
        potential_score = compute_potential_score(temp_result, seasonal, dl=None, spectrum=spectrum)
        
        results['sectors'][name] = {
            'code': data['code'],
            'full_name': data['full_name'],
            'category': data['category'],
            'color': data['color'],
            'potential_score': potential_score,
            'cum_return': round(cum_ret, 1),
            'current_price': round(closes[-1], 3),
            'rsi': round(rsi, 1),
            'mom_20': round(current_mom_20, 2),
            'mom_60': round(current_mom_60, 2),
            'bias_20': round(bias_20, 2),
            'bias_60': round(bias_60, 2),
            'phase': phase,
            'phase_color': phase_color,
            'action': action,
            'spectrum': spectrum,
            'seasonal': seasonal,
            'mom_20_history': [round(x, 2) for x in mom_20_history],
            'dates': dates[-len(mom_20_history):] if mom_20_history else [],
            'realtime': data.get('realtime'),
        }
        
        all_returns[name] = rets
    
    # 相关性矩阵（取前15个以保持可读）
    top_sectors = list(all_returns.keys())[:15]
    subset_returns = {k: all_returns[k] for k in top_sectors}
    results['correlation_matrix'] = compute_corr_matrix(subset_returns)
    
    # 轮动排名历史
    sector_names = list(all_returns.keys())
    for start in range(0, min_len - 60, 60):
        end = start + 60
        period_perf = {}
        for name in sector_names:
            closes = all_etf_data[name]['closes'][-min_len:]
            cum = closes[end] / closes[start] - 1 if closes[start] > 0 else 0
            period_perf[name] = round(cum * 100, 1)
        ranked = sorted(period_perf.items(), key=lambda x: x[1], reverse=True)
        results['rotation_history'].append({
            'date': all_etf_data[sector_names[0]]['dates'][-min_len + start] if start < min_len else '',
            'rankings': [{'sector': s, 'return': r} for s, r in ranked[:10]],
        })
    
    # 交易信号
    for name in sector_names:
        s = results['sectors'][name]
        if s['rsi'] < 30:
            results['signals'].append({'type': 'BUY', 'sector': name, 'reason': f"RSI={s['rsi']:.0f} 超卖", 'strength': '强'})
        elif s['rsi'] > 70:
            results['signals'].append({'type': 'SELL', 'sector': name, 'reason': f"RSI={s['rsi']:.0f} 超买", 'strength': '强'})
        elif s['mom_20'] > 10:
            results['signals'].append({'type': 'HOLD', 'sector': name, 'reason': f"20日动量={s['mom_20']:+.1f}% 强势", 'strength': '中'})
        elif s['mom_20'] < -10:
            results['signals'].append({'type': 'WATCH', 'sector': name, 'reason': f"20日动量={s['mom_20']:+.1f}% 弱势", 'strength': '中'})
    
    # 写入JSON
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    print(f"\n分析完成 → {OUTPUT_FILE}")
    print(f"板块数: {len(results['sectors'])}")
    print(f"数据范围: {results['data_range']}")
    
    return results


if __name__ == '__main__':
    results = run_analysis()
    print("\n当前板块状态:")
    for name, s in sorted(results['sectors'].items(), key=lambda x: x[1]['mom_20'], reverse=True):
        print(f"  {name:<10} {s['phase']:<6} RSI={s['rsi']:>5.1f} 20日={s['mom_20']:>+6.1f}% [{s['category']}]")
