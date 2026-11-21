#!/usr/bin/env python3
"""快速数据获取 — 并行请求+实时行情，~5秒完成"""
import json, os, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from data_engine import ETF_LIST, fetch_kline_tencent, parse_klines, is_market_hours, fetch_realtime_tencent, fetch_realtime_eastmoney, merge_realtime_to_klines

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'etf_cache')
os.makedirs(CACHE_DIR, exist_ok=True)


def fetch_one(name, code, full_name, category, realtime_map=None):
    """获取单只ETF数据（带缓存+实时行情）"""
    cache_file = os.path.join(CACHE_DIR, f'{code}.json')
    
    # 检查缓存是否新鲜（交易时段10分钟，非交易时段2小时）
    market_open = is_market_hours()
    cache_ttl = 600 if market_open else 7200
    
    cached_data = None
    if os.path.exists(cache_file):
        age = time.time() - os.path.getmtime(cache_file)
        if age < cache_ttl:
            with open(cache_file) as f:
                cached_data = json.load(f)
            if cached_data and len(cached_data) > 50:
                # 交易时段合并实时行情
                if market_open and realtime_map and code in realtime_map:
                    cached_data = merge_realtime_to_klines(cached_data, realtime_map[code], code)
                return name, code, full_name, category, cached_data, 'cache'
    
    # 从网络获取
    klines = fetch_kline_tencent(code, count=500)
    if klines and len(klines) > 50:
        # 交易时段合并实时行情
        if market_open and realtime_map and code in klines:
            klines = merge_realtime_to_klines(klines, realtime_map[code], code)
        with open(cache_file, 'w') as f:
            json.dump(klines, f)
        return name, code, full_name, category, klines, 'network'
    
    # 回退到旧缓存
    if os.path.exists(cache_file):
        with open(cache_file) as f:
            data = json.load(f)
        if data and len(data) > 50:
            return name, code, full_name, category, data, 'old_cache'
    
    return name, code, full_name, category, None, 'failed'


def fast_fetch_all(max_workers=8):
    """并行获取所有ETF数据（含实时行情）"""
    t0 = time.time()
    results = {}
    stats = {'cache': 0, 'network': 0, 'old_cache': 0, 'failed': 0}
    
    market_open = is_market_hours()
    realtime_map = {}
    
    # 交易时段批量获取实时行情
    if market_open:
        all_codes = [code for name, (code, _, _) in ETF_LIST.items()]
        realtime_map = fetch_realtime_tencent(all_codes)
        if not realtime_map:
            realtime_map = fetch_realtime_eastmoney(all_codes)
        print(f"  实时行情: {len(realtime_map)}/{len(all_codes)} 只")
    
    tasks = [(name, code, full_name, cat) for name, (code, full_name, cat) in ETF_LIST.items()]
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(fetch_one, *t, realtime_map): t[0] for t in tasks}
        for future in as_completed(futures):
            name, code, full_name, category, klines, source = future.result()
            stats[source] += 1
            if klines:
                closes, dates = parse_klines(klines)
                if len(closes) > 100:
                    results[name] = {
                        'closes': closes, 'dates': dates,
                        'code': code, 'full_name': full_name,
                        'category': category,
                        'realtime': realtime_map.get(code),
                    }
    
    elapsed = time.time() - t0
    rt_tag = f" 实时:{len(realtime_map)}" if realtime_map else ""
    print(f"快速获取: {len(results)}/{len(ETF_LIST)} ETF, {elapsed:.1f}s "
          f"(缓存:{stats['cache']} 网络:{stats['network']} 旧缓存:{stats['old_cache']} 失败:{stats['failed']}){rt_tag}")
    return results


if __name__ == '__main__':
    fast_fetch_all()
