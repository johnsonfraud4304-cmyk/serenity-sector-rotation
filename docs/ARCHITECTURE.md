# 架构说明

## 一句话

`data_engine.py` 负责把行情变成指标，`full_analysis.py` 把指标串成一轮完整分析，`server.py` 只做两件事——调度这轮分析、把结果喂给前端。所有模块之间不通过数据库耦合，只通过仓库根目录下的几个 JSON 文件交接。

## 数据流

```
腾讯 / 东方财富公开行情接口
        │  (并行抓取，fast_fetch.py)
        ▼
   etf_cache/*.json            本地缓存，交易时段 5 分钟过期
        │
        ▼
   data_engine.py              收益率、动量、RSI、MA20 偏离、阶段分类、季节效应、潜力分
        │
        ├──► analysis_data.json     主数据文件（前端唯一的数据源）
        │
        ▼
   full_analysis.py            一轮完整分析（按顺序）：
        ├─ 1. fast_fetch_all        并行拉 72 只 ETF
        ├─ 2. 技术分析              指标落盘
        ├─ 3. 相关性矩阵
        ├─ 4. 轮动历史
        ├─ 5. 信号生成              超买超卖 / 强买强卖
        ├─ 6. dashboard_engine      → dashboard.json（市场温度、阶段分布）
        ├─ 7. advanced_analysis     → MACD / 布林带 / 回撤 / 相对强度 / 组合建议
        ├─ 8. backtest_engine       → backtest_results.json（5 类策略 × 8 组参数）
        ├─ 9. cycle_engine          → cycle_analysis.json（Hilbert + FFT）
        └─ 10. DL 预测合并           把 dl_predictions.json 并进 analysis_data.json
        │
        ▼
   server.py                   标准库 http.server，无框架依赖
        ├─ 静态资源：index.html / sw.js / manifest.json / icon_*.png
        ├─ 数据：/analysis_data.json
        └─ /api/*：回测、推荐、持仓、专业建议、刷新触发、定时任务
```

## 刷新调度

`server.py` 里有三条互斥的刷新路径，都通过 `refresh_state` 这个全局字典向 `/api/refresh/status` 汇报进度：

| 路径 | 触发 | 做什么 | 耗时 |
|---|---|---|---|
| 快速刷新 | 启动时自动 / 「快速刷新」按钮 | `data_engine.py` → `full_analysis.py` → 合并 DL | ~10 s |
| AI 训练 | 「训练AI」按钮 / `/api/refresh/dl` | `train_and_predict.py` → 合并 DL | ~2 min |
| 定时刷新 | 后台线程 | 交易时段每 30 min，非交易时段每 2 h 跑一次快速刷新 | — |

子进程统一用 `sys.executable` 启动，`cwd` 固定在仓库根目录，所以不依赖调用者的工作目录。

## 模块职责

| 文件 | 职责 | 产出 |
|---|---|---|
| `etf_config.py` | ETF 池（72 只）、板块分类、配色 | — |
| `fast_fetch.py` | 多线程行情抓取，带重试 | `etf_cache/*.json` |
| `data_engine.py` | 指标计算、缓存 TTL、交易时段判断 | `analysis_data.json`（基础层） |
| `cycle_engine.py` | 周期长度识别：Hilbert 变换主路径 + 去趋势 FFT 交叉验证 | `cycle_analysis.json` |
| `dl_engine.py` | LSTM + Attention 模型、数据集、训练循环、推理 | `models/*.pt`、`models/*.pkl` |
| `train_and_predict.py` | 训练入口，产出未来 5 日动量与轮动阶段 | `dl_predictions.json` |
| `backtest_engine.py` | 5 类策略框架（动量轮动 / RSI 反转 / 均线交叉 / 多因子 / 低估反转） | 被 `run_backtest.py` 调用 |
| `stock_backtest.py` | 单标的回测 + 参数扫描 | 被 `run_backtest.py` 调用 |
| `advanced_analysis.py` | MACD、布林带、最大回撤、相对强度、组合建议 | 写回 `analysis_data.json` |
| `recommend_engine.py` | 推荐打分与排序 | `/api/recommend` |
| `dashboard_engine.py` | 市场温度、阶段分布、跨市场对照、行动摘要 | `dashboard.json` |
| `portfolio_tracker.py` | 交易记录、持仓成本、浮动盈亏 | `portfolio.json` |
| `professional_suggestions.py` | 持仓层面的加减仓建议 | `/api/professional` |
| `merge_all.py` | 把回测、周期、DL 的结果合并进主数据 | `analysis_data.json` |

## 前端

`index.html` 是一个不打包的单页应用：模板字符串渲染、`fetch` 拉 `/analysis_data.json` 与 `/api/*`、Chart.js 画图（本地 `chart.min.js`，不依赖 CDN）。`sw.js` 做静态资源缓存，`manifest.json` 让它可安装成 PWA。macOS 与 Android 端都只是给这个页面套壳，不额外写业务逻辑。

## 设计取舍

- **不用数据库**：数据量只有 72 只 ETF × 600 个交易日，JSON 足够；换来的是零部署成本，clone 下来就能跑。
- **不用 Web 框架**：`http.server` 够用，避免为了一个本地工具引入 Flask/FastAPI 依赖链。
- **JSON 交接而非函数调用**：每一步都能单独跑、单独看结果，调试时不用重跑整条链路。代价是步骤之间靠文件名约定，缺文件会静默降级。
- **模型随仓库分发**：`models/` 只有 1.2 MB，带上它可以让 DL 预测开箱可用；训练脚本仍在，想复现随时可以重跑。
