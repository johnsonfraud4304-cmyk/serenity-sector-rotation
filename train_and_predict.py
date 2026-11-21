#!/usr/bin/env python3
"""快速DL训练脚本 — 直接从缓存加载数据，不重复分析"""
import json, os, sys
sys.path.insert(0, os.path.dirname(__file__))

from dl_engine import (
    prepare_sector_features, run_training, predict_rotation,
    RotationTrainer, SectorRotationDataset, DEVICE
)
from run_backtest import load_etf_data
from data_engine import compute_potential_score

OUTPUT = os.path.join(os.path.dirname(__file__), 'dl_predictions.json')

def main():
    # 1. 直接从缓存加载数据（秒级）
    print("加载板块数据...")
    sector_data = load_etf_data()
    print(f"可用板块: {len(sector_data)}")

    if len(sector_data) < 3:
        print("数据不足，退出")
        return

    # 2. 训练（~45秒）
    trainer = run_training(sector_data, epochs=15)
    if trainer is None:
        print("训练失败")
        return

    # 3. 预测（~5秒）
    print("\n运行预测...")
    predictions = predict_rotation(trainer, sector_data)
    if predictions is None:
        print("预测失败")
        return

    # 4. 加载现有 analysis_data 重算评分
    analysis_path = os.path.join(os.path.dirname(__file__), 'analysis_data.json')
    if os.path.exists(analysis_path):
        with open(analysis_path) as f:
            analysis = json.load(f)
        for name in analysis['sectors']:
            dl = predictions.get(name)
            if dl:
                s = analysis['sectors'][name]
                s['potential_score'] = compute_potential_score(
                    s, s.get('seasonal', {}), dl=dl, spectrum=s.get('spectrum', [])
                )
        with open(analysis_path, 'w', encoding='utf-8') as f:
            json.dump(analysis, f, ensure_ascii=False, indent=2)

    # 5. 保存预测结果
    results = {
        'model_info': {
            'architecture': 'LSTM + TemporalAttention + MultiHeadRotation',
            'parameters': 98792,
            'device': str(DEVICE),
            'lookback': 30,
            'horizon': 5,
            'train_loss': trainer.train_history[-1]['loss'] if trainer.train_history else None,
        },
        'predictions': {},
        'top_picks': [],
        'avoid_list': [],
    }

    for name, pred in sorted(predictions.items(), key=lambda x: x[1]['rotation_score'], reverse=True):
        results['predictions'][name] = {
            **pred,
            'current_phase': '', 'current_rsi': 0, 'current_mom20': 0,
            'code': '', 'category': '',
        }
        if pred['rotation_score'] > 0.15 and pred['pred_mom'] > 0:
            results['top_picks'].append({
                'name': name,
                'reason': f"rot={pred['rotation_score']:.3f} mom={pred['pred_mom']:+.1f}%",
                'confidence': pred['confidence'],
            })
        elif pred['rotation_score'] < 0.05 and pred['pred_mom'] < -5:
            results['avoid_list'].append({
                'name': name,
                'reason': f"rot={pred['rotation_score']:.3f} mom={pred['pred_mom']:+.1f}%",
            })

    with open(OUTPUT, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    dl_count = sum(1 for p in predictions.values() if p.get('rotation_score', 0) > 0)
    print(f"\n完成! 预测: {len(predictions)} 板块, Loss: {results['model_info']['train_loss']:.4f}")

if __name__ == '__main__':
    main()
