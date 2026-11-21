#!/usr/bin/env python3
"""
个股回测API
接收股票代码，获取数据，运行9种策略回测，返回JSON结果
"""

import json, os, sys, subprocess, math
sys.path.insert(0, os.path.dirname(__file__))

from backtest_engine import (
    backtest_single_etf, ALL_STRATEGIES,
    compute_rsi_series, compute_momentum_series
)

ETF_CACHE = os.path.join(os.path.dirname(__file__), 'etf_cache')

# 策略详细说明
STRATEGY_GUIDE = {
    '动量轮动(回看20天/持有5天/选2个)': {
        'name': '短期动量轮动',
        'logic': '追踪过去20天涨幅最大的股票，买入后持有5天，然后重新选股。',
        'when_buy': '当该股票过去20天的累计收益率排名靠前（为正且较大）时买入。',
        'when_sell': '持有满5天后卖出，或RSI>70（严重超买）时提前卖出。',
        'how_to': [
            '每周末（或每5个交易日）计算手中股票的20日收益率',
            '如果20日收益率>0%且RSI<70，继续持有',
            '如果20日收益率<0%或RSI>70，卖出并换入20日收益率更高的股票',
            '如果没有更好的选择，保持现金等待',
        ],
        'suitable': '适合短线交易者，需要频繁操作，交易成本较高。',
        'risk': '追涨杀跌风险大，遇到急跌可能连续亏损。',
    },
    '动量轮动(回看40天/持有20天/选2个)': {
        'name': '中期动量轮动',
        'logic': '追踪过去40天涨幅较大的股票，买入后持有20天（约一个月），然后重新评估。',
        'when_buy': '当该股票过去40天的累计收益率为正，且RSI<65时买入。',
        'when_sell': '持有满20天后重新评估，如果40日动量转负或RSI>70则卖出。',
        'how_to': [
            '每月初（或每20个交易日）检查手中股票的40日收益率',
            '如果40日收益率>5%且RSI<65，继续持有',
            '如果40日收益率<0%，立即卖出',
            '如果RSI>70，考虑减仓一半',
            '空仓时，选择40日收益率最高的板块ETF买入',
        ],
        'suitable': '适合上班族，每月操作一次，交易成本低。',
        'risk': '趋势反转时可能回吐较多利润。',
    },
    'RSI反转(买<30/卖>70)': {
        'name': 'RSI超买超卖反转',
        'logic': '当RSI跌到30以下（严重超卖）时买入，当RSI涨到70以上（严重超买）时卖出。',
        'when_buy': 'RSI(14日)<30，说明近期跌得太多，短期反弹概率大。',
        'when_sell': 'RSI(14日)>70，说明近期涨得太多，短期回调概率大。',
        'how_to': [
            '每天收盘后计算股票的RSI(14日)',
            '当RSI<30时：分3批买入（RSI=30买1/3，RSI=25买1/3，RSI=20买1/3）',
            '当RSI>70时：分2批卖出（RSI=70卖1/2，RSI=75卖1/2）',
            'RSI在30-70之间时：持有不动',
            '止损：买入后如果继续下跌超过10%，无条件卖出',
        ],
        'suitable': '适合逆向投资者，需要耐心等待极端位置。',
        'risk': '超卖后可能继续下跌（"接飞刀"风险），需要严格止损。',
    },
    'RSI反转(买<25/卖>75)': {
        'name': '严格RSI反转',
        'logic': '比RSI(30/70)更严格，只在极端位置操作，减少交易频率。',
        'when_buy': 'RSI(14日)<25，极度超卖，历史低位。',
        'when_sell': 'RSI(14日)>75，极度超买，历史高位。',
        'how_to': [
            '每天收盘后计算RSI',
            'RSI<25：一次性买入50%仓位',
            'RSI<20：加仓到80%',
            'RSI>75：卖出50%',
            'RSI>80：清仓',
            '止损：买入后跌幅超过8%立即止损',
        ],
        'suitable': '适合保守型投资者，交易频率最低。',
        'risk': '信号很少，可能错过大段行情。',
    },
    '均线交叉(MA5/MA20)': {
        'name': '5日/20日均线金叉死叉',
        'logic': '当5日均线上穿20日均线（金叉）时买入，下穿（死叉）时卖出。',
        'when_buy': '5日均线从下方穿过20日均线，且两条均线都向上。',
        'when_sell': '5日均线从上方穿过20日均线，或价格跌破20日均线。',
        'how_to': [
            '每天收盘后计算5日均线和20日均线',
            '金叉信号（5日>20日且昨天5日<20日）：第二天开盘买入',
            '死叉信号（5日<20日且昨天5日>20日）：第二天开盘卖出',
            '如果没有信号，保持之前的仓位不动',
            '止损：买入后价格跌破20日均线的3%以下',
        ],
        'suitable': '适合趋势跟踪者，操作简单明确。',
        'risk': '震荡市中频繁假信号，来回打脸。',
    },
    '综合评分(动量40%+RSI30%+量30%)': {
        'name': '多因子综合评分（偏动量）',
        'logic': '综合动量、RSI、成交量三个因子打分，选分数最高的买入。',
        'when_buy': '综合评分>60分，且动量>0，RSI<60。',
        'when_sell': '综合评分<40分，或任一因子发出卖出信号（RSI>70或动量<-10%）。',
        'how_to': [
            '每天收盘后计算三个因子：',
            '  动量分 = 20日收益率标准化到0-100分（权重40%）',
            '  RSI分 = 100 - |RSI-35|×2（权重30%，RSI=35时满分）',
            '  量能分 = 当前成交量/20日平均成交量（权重30%）',
            '总分 = 动量分×0.4 + RSI分×0.3 + 量能分×0.3',
            '总分>60：买入或持有',
            '总分<40：卖出',
            '总分40-60：观望',
        ],
        'suitable': '适合有一定经验的投资者，需要同时看多个指标。',
        'risk': '因子权重是历史最优，未来可能失效。',
    },
    '综合评分(动量30%+RSI50%+量20%)': {
        'name': '多因子综合评分（偏RSI）',
        'logic': '以RSI为主导的综合评分，更偏向逆向投资。',
        'when_buy': '综合评分>60分，重点看RSI<35（超卖区）。',
        'when_sell': 'RSI>65或综合评分<40。',
        'how_to': [
            '每天收盘后计算：',
            '  动量分 = 20日收益率标准化（权重30%）',
            '  RSI分 = 100 - |RSI-35|×2（权重50%）',
            '  量能分 = 成交量比（权重20%）',
            'RSI<30且总分>60：大胆买入',
            'RSI在30-40且总分>60：小仓位试探',
            'RSI>65：减仓或止盈',
        ],
        'suitable': '适合喜欢抄底的投资者，RSI权重最高。',
        'risk': 'RSI超卖不等于见底，可能越跌越买。',
    },
    '价值逆向(RSI<25/持有20天)': {
        'name': '极端超卖抄底',
        'logic': '只在RSI跌到25以下（极端恐慌）时买入，无条件持有20天后卖出。',
        'when_buy': 'RSI(14日)<25，市场极端恐慌时。',
        'when_sell': '买入后固定持有20个交易日（约1个月），无论涨跌都卖出。',
        'how_to': [
            '耐心等待RSI<25的极端机会（可能几个月才出现一次）',
            'RSI<25当天收盘前买入',
            '买入后设置20个交易日的闹钟',
            '20天后无条件卖出，不看价格',
            '止损：如果买入后跌幅超过15%，立即止损不等20天',
        ],
        'suitable': '最适合散户！操作最少，只需等待极端机会。',
        'risk': '机会很少，需要极大的耐心。黑天鹅事件中可能亏损。',
    },
    '价值逆向(RSI<20/持有30天)': {
        'name': '极度恐慌抄底',
        'logic': '只在RSI<20（极度恐慌，历史罕见）时买入，持有30天后卖出。',
        'when_buy': 'RSI(14日)<20，极度罕见的恐慌信号。',
        'when_sell': '买入后固定持有30个交易日，或RSI>70提前止盈。',
        'how_to': [
            'RSI<20是非常罕见的信号，每年可能只出现1-3次',
            '出现时果断买入50%仓位',
            'RSI<15时加仓到80%',
            '持有30个交易日后卖出',
            '中途如果RSI>70，提前止盈',
            '止损：跌幅超过12%立即止损',
        ],
        'suitable': '最适合大资金稳健操作，胜率最高但机会最少。',
        'risk': '极端行情中RSI<20可能意味着更大的下跌（如系统性风险）。',
    },
}


def _search_stock_tencent(keyword):
    """通过腾讯搜索API查找股票代码"""
    import urllib.parse
    try:
        url = f'https://smartbox.gtimg.cn/s3/?v=2&q={urllib.parse.quote(keyword)}&t=gp'
        r = subprocess.run(['curl', '-s', '--max-time', '5', url],
                          capture_output=True, timeout=8)
        data = r.stdout.decode('gbk', errors='ignore')
        if 'v_hint="' in data:
            hint = data.split('v_hint="')[1].split('"')[0]
            parts = hint.split('~')
            if len(parts) >= 3:
                market = parts[0]  # sh or sz
                code = parts[1]    # 股票代码
                name = parts[2]    # 股票名称
                return f'{market}{code}'
    except:
        pass
    return None


# 个股名称→代码映射
STOCK_NAME_MAP = {
    '贵州茅台': '600519', '五粮液': '000858', '泸州老窖': '000568',
    '伊利股份': '600887', '海尔智家': '600690', '美的集团': '000333',
    '比亚迪': '002594', '宁德时代': '300750', '隆基绿能': '601012',
    '阳光电源': '300274', '中国中免': '601888', '海天味业': '603288',
    '恒瑞医药': '600276', '药明康德': '603259', '迈瑞医疗': '300760',
    '招商银行': '600036', '中国平安': '601318', '贵州银行': '601997',
    '中信证券': '600030', '海通证券': '600837', '万科A': '000002',
    '保利发展': '600048', '海螺水泥': '600585', '中国建筑': '601668',
    '三一重工': '600031', '中联重科': '000157', '恒立液压': '601100',
    '中航沈飞': '600760', '航发动力': '600893', '紫光国微': '002049',
    '北方华创': '002371', '中芯国际': '688981', '韦尔股份': '603501',
    '海光信息': '688041', '寒武纪': '688256', '科大讯飞': '002230',
    '中际旭创': '300308', '新易盛': '300502', '光迅科技': '002281',
    '赛力斯': '601127', '长安汽车': '000625', '长城汽车': '601633',
    '中国神华': '601088', '紫金矿业': '601899', '洛阳钼业': '603993',
    '贵州茅台': '600519', '山西汾酒': '600809', '洋河股份': '002304',
    '隆基绿能': '601012', '通威股份': '600438', '福斯特': '603806',
    '生益科技': '600183', '沪电股份': '002463', '深南电路': '002916',
    '立讯精密': '002475', '歌尔股份': '002241', '京东方A': '000725',
    '工业富联': '601138', '海康威视': '002415', '大华股份': '002236',
    '恒生电子': '600570', '用友网络': '600588', '金蝶国际': '00268',
    '福斯特': '603806', '旭升集团': '603305', '三花智控': '002050',
    '上汽集团': '600104', '广汽集团': '601238', '吉利汽车': '00175',
    '中国铁建': '601186', '中国交建': '601800', '中国中铁': '601390',
    '工商银行': '601398', '建设银行': '601939', '农业银行': '601288',
    '中国银行': '601988', '交通银行': '601328', '兴业银行': '601166',
    '浦发银行': '600000', '民生银行': '600016', '平安银行': '000001',
    '格力电器': '000651', 'TCL科技': '000100', '中兴通讯': '000063',
    '中国联通': '600050', '中国移动': '600941', '中国电信': '601728',
    '宝钢股份': '600019', '鞍钢股份': '000898', '太钢不锈': '000825',
    '中国石化': '600028', '中国石油': '601857', '中国海油': '600938',
    '长江电力': '600900', '华能国际': '600011', '国电南瑞': '600406',
    '隆基绿能': '601012', '通威股份': '600438', '阳光电源': '300274',
    '亿纬锂能': '300014', '天齐锂业': '002466', '赣锋锂业': '002460',
}

def fetch_stock_kline(code_or_name, count=500):
    """
    获取个股K线数据
    支持：股票代码(如600519、sh600519) 或 名称(如贵州茅台)
    """
    # 标准化代码
    code = code_or_name.strip()
    
    # 1. 先查名称映射表
    if code in STOCK_NAME_MAP:
        code = STOCK_NAME_MAP[code]
    # 2. 如果是名称且不在映射表中，先尝试腾讯搜索API
    elif not code.replace('sh','').replace('sz','').replace('.','').isdigit():
        # 尝试从analysis_data匹配
        analysis_path = os.path.join(os.path.dirname(__file__), 'analysis_data.json')
        found = False
        if os.path.exists(analysis_path):
            with open(analysis_path) as f:
                analysis = json.load(f)
            for name, s in analysis.get('sectors', {}).items():
                if code in name or name in code:
                    code = s.get('code', code)
                    found = True
                    break
        # 如果analysis_data没找到，用腾讯搜索API
        if not found:
            searched = _search_stock_tencent(code)
            if searched:
                code = searched
    
    # 去掉前缀
    pure_code = code.replace('sh', '').replace('sz', '').replace('.', '')
    
    # 确定市场前缀
    if pure_code.startswith('6') or pure_code.startswith('5'):
        prefix = 'sh'
    elif pure_code.startswith('0') or pure_code.startswith('3'):
        prefix = 'sz'
    elif pure_code.startswith('1'):
        prefix = 'sz'
    else:
        prefix = 'sh'
    
    full_code = f'{prefix}{pure_code}'
    
    # 检查缓存
    cache_file = os.path.join(ETF_CACHE, f'{full_code}.json')
    if os.path.exists(cache_file):
        with open(cache_file) as f:
            klines = json.load(f)
        if len(klines) > 50:
            return parse_klines(klines), full_code
    
    # 从腾讯API获取
    url = f'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?_var=kline_dayfq&param={full_code},day,,,{count},qfq'
    try:
        r = subprocess.run(
            ['curl', '-s', '--max-time', '15', '-H', 'User-Agent: Mozilla/5.0', url],
            capture_output=True, timeout=20
        )
        data = r.stdout.decode('gbk', errors='ignore')
        if len(data) < 50:
            return None, full_code
        idx = data.index('{')
        d = json.loads(data[idx:])
        stock_key = list(d.get('data', {}).keys())[0]
        stock_data = d['data'][stock_key]
        klines = stock_data.get('day', stock_data.get('qfqday', []))
        
        # 缓存
        with open(cache_file, 'w') as f:
            json.dump(klines, f)
        
        return parse_klines(klines), full_code
    except Exception as e:
        return None, full_code


def parse_klines(klines):
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
    return {'closes': closes, 'dates': dates} if len(closes) > 50 else None


def run_stock_backtest(code_or_name):
    """运行个股回测"""
    data, full_code = fetch_stock_kline(code_or_name)
    if not data:
        return {'error': f'无法获取 {code_or_name} 的数据，请检查代码是否正确'}
    
    closes = data['closes']
    dates = data['dates']
    
    # 获取股票名称
    stock_name = full_code
    # 从名称映射表反查
    reverse_map = {v: k for k, v in STOCK_NAME_MAP.items()}
    pure = full_code.replace('sh', '').replace('sz', '')
    if pure in reverse_map:
        stock_name = reverse_map[pure]
    # 从analysis_data查找
    elif os.path.exists(os.path.join(os.path.dirname(__file__), 'analysis_data.json')):
        with open(os.path.join(os.path.dirname(__file__), 'analysis_data.json')) as f:
            analysis = json.load(f)
        for name, s in analysis.get('sectors', {}).items():
            if s.get('code') == full_code:
                stock_name = name
                break
    
    # 计算基本指标
    rsi_series = compute_rsi_series(closes)
    current_rsi = rsi_series[-1] if rsi_series else 50
    current_price = closes[-1]
    
    # 运行所有策略
    results = []
    for strat_fn in ALL_STRATEGIES:
        strategy = strat_fn()
        bt = backtest_single_etf(closes, dates, strategy)
        if bt:
            strat_name = strategy['name']
            guide = STRATEGY_GUIDE.get(strat_name, {})
            results.append({
                'strategy': strat_name,
                'guide': guide,
                'total_return': bt['total_return'],
                'annual_return': bt['annual_return'],
                'max_drawdown': bt['max_drawdown'],
                'sharpe_ratio': bt['sharpe_ratio'],
                'win_rate': bt['win_rate'],
                'trade_count': bt['trade_count'],
                'equity_curve': bt['equity_curve'][-150:],
            })
    
    # 按综合得分排序
    for r in results:
        score = (
            0.30 * max(0, r['total_return']) / 100 +
            0.30 * max(0, r['sharpe_ratio']) / 3 +
            0.20 * r['win_rate'] / 100 +
            0.20 * max(0, 1 - r['max_drawdown'] / 50)
        )
        r['score'] = round(score, 3)
    
    results.sort(key=lambda x: x['score'], reverse=True)
    
    # 推荐最优策略
    best = results[0] if results else None
    
    return {
        'stock_code': full_code,
        'stock_name': stock_name,
        'current_price': round(current_price, 2),
        'current_rsi': round(current_rsi, 1),
        'data_range': f'{dates[0]} ~ {dates[-1]}',
        'data_points': len(closes),
        'best_strategy': best['strategy'] if best else None,
        'results': results,
        'strategy_guide': STRATEGY_GUIDE,
    }


if __name__ == '__main__':
    # 测试
    import sys
    code = sys.argv[1] if len(sys.argv) > 1 else '600519'
    result = run_stock_backtest(code)
    if 'error' in result:
        print(f"错误: {result['error']}")
    else:
        print(f"\n{result['stock_name']} ({result['stock_code']})")
        print(f"当前价: {result['current_price']}  RSI: {result['current_rsi']}")
        print(f"数据: {result['data_range']} ({result['data_points']}条)")
        print(f"\n{'策略':<25} {'收益':>8} {'年化':>8} {'胜率':>6} {'回撤':>8} {'夏普':>6}")
        print('-' * 70)
        for r in result['results']:
            print(f"{r['strategy']:<25} {r['total_return']:>+7.1f}% {r['annual_return']:>+7.1f}% "
                  f"{r['win_rate']:>5.1f}% {r['max_drawdown']:>7.1f}% {r['sharpe_ratio']:>5.2f}")
