#!/usr/bin/env python3
"""
板块轮动深度学习预测引擎
模型：多层LSTM + Attention + 分类头
功能：预测板块未来动量、轮动阶段、最优配置权重
"""

import json, os, math, time, pickle
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader
import numpy as np

DEVICE = torch.device('mps' if torch.backends.mps.is_available() else 'cpu')
MODEL_DIR = os.path.join(os.path.dirname(__file__), 'models')
os.makedirs(MODEL_DIR, exist_ok=True)

# ============================================================
# 1. 数据集
# ============================================================
class SectorRotationDataset(Dataset):
    """
    输入：过去 LOOKBACK 天的多板块特征序列
    输出：未来 HORIZON 天的板块动量预测 + 轮动阶段分类
    
    特征（每板块每天）：
    - 日收益率
    - 5日动量
    - 20日动量
    - RSI(14)
    - MA20偏离
    - 成交量变化率（如有）
    """
    
    def __init__(self, sector_data, lookback=30, horizon=5):
        """
        sector_data: dict[板块名] -> {
            'returns': list[float],
            'mom5': list[float],
            'mom20': list[float],
            'rsi': list[float],
            'bias20': list[float],
        }
        """
        self.lookback = lookback
        self.horizon = horizon
        self.sector_names = sorted(sector_data.keys())
        self.n_sectors = len(self.sector_names)
        
        # 构建特征矩阵 (T, n_sectors, n_features)
        min_len = min(len(v['returns']) for v in sector_data.values())
        n_features = 5  # ret, mom5, mom20, rsi, bias20
        
        self.features = np.zeros((min_len, self.n_sectors, n_features), dtype=np.float32)
        self.targets_mom = np.zeros((min_len, self.n_sectors), dtype=np.float32)
        self.targets_phase = np.zeros((min_len, self.n_sectors), dtype=np.int64)
        
        for i, name in enumerate(self.sector_names):
            d = sector_data[name]
            T = min_len
            self.features[:T, i, 0] = d['returns'][:T]
            self.features[:T, i, 1] = d['mom5'][:T]
            self.features[:T, i, 2] = d['mom20'][:T]
            self.features[:T, i, 3] = d['rsi'][:T]
            self.features[:T, i, 4] = d['bias20'][:T]
        
        # 标准化
        self.mean = self.features.mean(axis=(0, 1), keepdims=True)
        self.std = self.features.std(axis=(0, 1), keepdims=True) + 1e-8
        self.features = (self.features - self.mean) / self.std
        
        # 构建样本
        self.samples = []
        for t in range(lookback, min_len - horizon):
            x = self.features[t - lookback:t]  # (lookback, n_sectors, n_features)
            
            # 目标：未来horizon天的累计动量
            future_mom = np.zeros(self.n_sectors)
            for s in range(self.n_sectors):
                cum = 1.0
                for h in range(horizon):
                    if t + h < min_len:
                        cum *= (1 + sector_data[self.sector_names[s]]['returns'][t + h])
                future_mom[s] = (cum - 1) * 100
            
            # 轮动阶段分类（5类）
            # 0:底部 1:上升 2:顶部 3:下降 4:震荡
            phase = np.zeros(self.n_sectors, dtype=np.int64)
            for s in range(self.n_sectors):
                mom20 = sector_data[self.sector_names[s]]['mom20'][t]
                rsi = sector_data[self.sector_names[s]]['rsi'][t]
                if mom20 < -10 and rsi < 35:
                    phase[s] = 0  # 底部
                elif mom20 > 0 and rsi > 45:
                    phase[s] = 1  # 上升
                elif mom20 > 10 and rsi > 65:
                    phase[s] = 2  # 顶部
                elif mom20 < 0 and rsi < 45:
                    phase[s] = 3  # 下降
                else:
                    phase[s] = 4  # 震荡
            
            self.samples.append((x, future_mom, phase))
    
    def __len__(self):
        return len(self.samples)
    
    def __getitem__(self, idx):
        x, mom, phase = self.samples[idx]
        return (torch.from_numpy(x).float(), 
                torch.from_numpy(mom).float(), 
                torch.from_numpy(phase).long())


# ============================================================
# 2. 模型架构
# ============================================================
class TemporalAttention(nn.Module):
    """时序注意力机制"""
    def __init__(self, hidden_dim):
        super().__init__()
        self.attn = nn.Sequential(
            nn.Linear(hidden_dim, hidden_dim // 2),
            nn.Tanh(),
            nn.Linear(hidden_dim // 2, 1)
        )
    
    def forward(self, lstm_out):
        # lstm_out: (batch, seq_len, hidden)
        scores = self.attn(lstm_out)  # (batch, seq_len, 1)
        weights = torch.softmax(scores, dim=1)
        context = (lstm_out * weights).sum(dim=1)  # (batch, hidden)
        return context, weights.squeeze(-1)


class SectorRotationLSTM(nn.Module):
    """
    板块轮动预测模型
    
    架构：
    1. 特征提取：Linear(n_features -> hidden_dim)
    2. 时序建模：多层LSTM
    3. 注意力：TemporalAttention
    4. 板块独立预测头：每个板块独立的动量回归 + 阶段分类
    5. 轮动信号：跨板块相对强弱 + 最优配置权重
    """
    
    def __init__(self, n_sectors, n_features=5, hidden_dim=64, 
                 n_layers=2, dropout=0.2, lookback=30):
        super().__init__()
        self.n_sectors = n_sectors
        self.hidden_dim = hidden_dim
        self.lookback = lookback
        
        # 特征提取（板块间共享）
        self.feature_proj = nn.Sequential(
            nn.Linear(n_features, hidden_dim),
            nn.LayerNorm(hidden_dim),
            nn.ReLU(),
            nn.Dropout(dropout)
        )
        
        # 板块嵌入（学习板块特有模式）
        self.sector_embed = nn.Embedding(n_sectors, hidden_dim // 4)
        
        # LSTM时序建模
        self.lstm = nn.LSTM(
            input_size=hidden_dim + hidden_dim // 4,
            hidden_size=hidden_dim,
            num_layers=n_layers,
            batch_first=True,
            dropout=dropout if n_layers > 1 else 0,
            bidirectional=False
        )
        
        # 时序注意力
        self.attention = TemporalAttention(hidden_dim)
        
        # 动量回归头（预测未来N天动量）
        self.momentum_head = nn.Sequential(
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, 1)
        )
        
        # 阶段分类头（5类）
        self.phase_head = nn.Sequential(
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, 5)
        )
        
        # 跨板块轮动信号（学习板块间相对强弱）
        self.rotation_attn = nn.MultiheadAttention(
            embed_dim=hidden_dim, num_heads=4, 
            dropout=dropout, batch_first=True
        )
        self.rotation_proj = nn.Linear(hidden_dim, 1)
        
    def forward(self, x):
        """
        x: (batch, lookback, n_sectors, n_features)
        向量化版本：所有板块并行处理，无Python循环
        """
        batch_size, seq_len, n_sec, n_feat = x.shape
        
        # 特征提取
        x_flat = x.reshape(-1, n_feat)
        feat = self.feature_proj(x_flat)
        feat = feat.reshape(batch_size, seq_len, n_sec, self.hidden_dim)
        
        # 板块嵌入
        sector_ids = torch.arange(n_sec, device=x.device)
        s_emb = self.sector_embed(sector_ids)
        s_emb = s_emb.unsqueeze(0).unsqueeze(0).expand(batch_size, seq_len, -1, -1)
        feat = torch.cat([feat, s_emb], dim=-1)
        
        # 向量化LSTM：将所有板块拼接到batch维度，一次处理
        # feat: (B, T, S, D) -> (B*S, T, D)
        feat_flat = feat.permute(0, 2, 1, 3).reshape(batch_size * n_sec, seq_len, -1)
        lstm_out, _ = self.lstm(feat_flat)  # (B*S, T, H)
        context, _ = self.attention(lstm_out)  # (B*S, H)
        context = context.reshape(batch_size, n_sec, self.hidden_dim)
        
        # 预测头（向量化）
        pred_mom = self.momentum_head(context).squeeze(-1)  # (B, S)
        pred_phase = self.phase_head(context)  # (B, S, 5)
        
        # 轮动信号
        attn_out, _ = self.rotation_attn(context, context, context)
        rotation_score = self.rotation_proj(attn_out).squeeze(-1)  # (B, S)
        
        return pred_mom, pred_phase, rotation_score


# ============================================================
# 3. 训练器
# ============================================================
class RotationTrainer:
    """模型训练与在线学习"""
    
    def __init__(self, n_sectors, n_features=5, lookback=30, horizon=5):
        self.n_sectors = n_sectors
        self.lookback = lookback
        self.horizon = horizon
        self.model = SectorRotationLSTM(
            n_sectors=n_sectors,
            n_features=n_features,
            hidden_dim=64,
            n_layers=2,
            dropout=0.2,
            lookback=lookback
        ).to(DEVICE)
        
        self.optimizer = optim.AdamW(self.model.parameters(), lr=1e-3, weight_decay=1e-4)
        self.scheduler = optim.lr_scheduler.CosineAnnealingLR(self.optimizer, T_max=50)
        self.mom_criterion = nn.HuberLoss(delta=5.0)
        self.phase_criterion = nn.CrossEntropyLoss()
        self.rotation_criterion = nn.MSELoss()
        
        self.train_history = []
        self.model_path = os.path.join(MODEL_DIR, 'rotation_lstm.pt')
        self.config_path = os.path.join(MODEL_DIR, 'rotation_config.pkl')
    
    def train(self, dataset, epochs=50, batch_size=32):
        """离线训练"""
        dataloader = DataLoader(dataset, batch_size=batch_size, shuffle=True, 
                               num_workers=0, pin_memory=False)
        
        self.model.train()
        history = []
        
        for epoch in range(epochs):
            total_loss = 0
            total_mom_loss = 0
            total_phase_loss = 0
            n_batches = 0
            
            for x, target_mom, target_phase in dataloader:
                x = x.to(DEVICE)
                target_mom = target_mom.to(DEVICE)
                target_phase = target_phase.to(DEVICE)
                
                self.optimizer.zero_grad()
                
                pred_mom, pred_phase, rotation_score = self.model(x)
                
                # 多任务损失
                loss_mom = self.mom_criterion(pred_mom, target_mom)
                loss_phase = self.phase_criterion(
                    pred_phase.reshape(-1, 5), target_phase.reshape(-1)
                )
                
                # 轮动信号损失：最优板块应该有最高得分
                # 用未来动量作为soft label
                with torch.no_grad():
                    soft_label = torch.softmax(target_mom / 5.0, dim=-1)
                loss_rot = self.rotation_criterion(
                    torch.softmax(rotation_score, dim=-1), soft_label
                )
                
                loss = loss_mom + 0.5 * loss_phase + 0.3 * loss_rot
                loss.backward()
                torch.nn.utils.clip_grad_norm_(self.model.parameters(), 1.0)
                self.optimizer.step()
                
                total_loss += loss.item()
                total_mom_loss += loss_mom.item()
                total_phase_loss += loss_phase.item()
                n_batches += 1
            
            self.scheduler.step()
            
            avg_loss = total_loss / max(n_batches, 1)
            avg_mom = total_mom_loss / max(n_batches, 1)
            avg_phase = total_phase_loss / max(n_batches, 1)
            history.append({
                'epoch': epoch + 1,
                'loss': avg_loss,
                'mom_loss': avg_mom,
                'phase_loss': avg_phase,
            })
            
            if (epoch + 1) % 10 == 0:
                print(f"  Epoch {epoch+1}/{epochs}: loss={avg_loss:.4f} "
                      f"mom={avg_mom:.4f} phase={avg_phase:.4f}")
        
        self.train_history = history
        return history
    
    def predict(self, x):
        """
        x: (lookback, n_sectors, n_features) numpy array
        返回: dict[板块名] -> {pred_mom, pred_phase, rotation_score}
        """
        self.model.eval()
        with torch.no_grad():
            x_tensor = torch.from_numpy(x).unsqueeze(0).to(DEVICE)
            pred_mom, pred_phase, rotation_score = self.model(x_tensor)
            
            pred_mom = pred_mom.cpu().numpy()[0]
            pred_phase = torch.softmax(pred_phase, dim=-1).cpu().numpy()[0]
            rotation_score = torch.softmax(rotation_score, dim=-1).cpu().numpy()[0]
        
        return {
            'pred_mom': pred_mom,
            'pred_phase_probs': pred_phase,
            'rotation_score': rotation_score,
        }
    
    def online_update(self, x, target_mom, target_phase, lr=1e-4):
        """
        在线学习：用最新数据微调模型
        单步梯度更新，保持模型对新数据的适应性
        """
        self.model.train()
        
        # 临时降低学习率
        for pg in self.optimizer.param_groups:
            pg['lr'] = lr
        
        x_tensor = torch.from_numpy(x).unsqueeze(0).to(DEVICE)
        mom_tensor = torch.from_numpy(target_mom).unsqueeze(0).to(DEVICE)
        phase_tensor = torch.from_numpy(target_phase).unsqueeze(0).to(DEVICE)
        
        self.optimizer.zero_grad()
        pred_mom, pred_phase, rotation_score = self.model(x_tensor)
        
        loss_mom = self.mom_criterion(pred_mom, mom_tensor)
        loss_phase = self.phase_criterion(pred_phase.reshape(-1, 5), phase_tensor.reshape(-1))
        loss = loss_mom + 0.5 * loss_phase
        
        loss.backward()
        torch.nn.utils.clip_grad_norm_(self.model.parameters(), 0.5)
        self.optimizer.step()
        
        # 恢复学习率
        for pg in self.optimizer.param_groups:
            pg['lr'] = 1e-3
        
        return loss.item()
    
    def save(self):
        """保存模型"""
        torch.save({
            'model_state': self.model.state_dict(),
            'optimizer_state': self.optimizer.state_dict(),
            'train_history': self.train_history,
            'n_sectors': self.n_sectors,
        }, self.model_path)
        
        with open(self.config_path, 'wb') as f:
            pickle.dump({
                'n_sectors': self.n_sectors,
                'lookback': self.lookback,
                'horizon': self.horizon,
            }, f)
        print(f"模型已保存: {self.model_path}")
    
    def load(self):
        """加载模型"""
        if os.path.exists(self.model_path):
            checkpoint = torch.load(self.model_path, map_location=DEVICE, weights_only=False)
            self.model.load_state_dict(checkpoint['model_state'])
            self.optimizer.load_state_dict(checkpoint['optimizer_state'])
            self.train_history = checkpoint.get('train_history', [])
            print(f"模型已加载: {self.model_path}")
            return True
        return False


# ============================================================
# 4. 顶层接口
# ============================================================
def prepare_sector_features(sector_data):
    """
    将板块原始数据转换为模型输入特征
    
    sector_data: dict[板块名] -> {'closes': [...], 'dates': [...]}
    返回: dict[板块名] -> {'returns', 'mom5', 'mom20', 'rsi', 'bias20'}
    """
    features = {}
    for name, data in sector_data.items():
        closes = data['closes']
        n = len(closes)
        
        # 日收益率
        returns = [(closes[i] - closes[i-1]) / closes[i-1] for i in range(1, n)]
        
        # 5日动量
        mom5 = []
        for i in range(5, len(returns)):
            cum = 1.0
            for j in range(i-5, i):
                cum *= (1 + returns[j])
            mom5.append((cum - 1) * 100)
        
        # 20日动量
        mom20 = []
        for i in range(20, len(returns)):
            cum = 1.0
            for j in range(i-20, i):
                cum *= (1 + returns[j])
            mom20.append((cum - 1) * 100)
        
        # RSI(14)
        rsi = []
        period = 14
        for i in range(period, len(returns)):
            gains = [max(0, returns[j]) for j in range(i-period, i)]
            losses = [max(0, -returns[j]) for j in range(i-period, i)]
            avg_g = sum(gains) / period
            avg_l = sum(losses) / period
            if avg_l == 0:
                rsi.append(100)
            else:
                rsi.append(100 - 100 / (1 + avg_g / avg_l))
        
        # MA20偏离
        bias20 = []
        for i in range(20, n):
            ma20 = sum(closes[i-20:i]) / 20
            bias20.append((closes[i] / ma20 - 1) * 100)
        
        # 对齐长度
        min_len = min(len(returns), len(mom5), len(mom20), len(rsi), len(bias20))
        features[name] = {
            'returns': returns[-min_len:],
            'mom5': mom5[-min_len:],
            'mom20': mom20[-min_len:],
            'rsi': rsi[-min_len:],
            'bias20': bias20[-min_len:],
        }
    
    return features


def run_training(sector_data, epochs=15):
    """
    完整训练流程（优化版：15 epoch + 大batch）
    """
    print("=" * 60)
    print("板块轮动深度学习训练（优化版）")
    print("=" * 60)
    
    features = prepare_sector_features(sector_data)
    sector_names = sorted(features.keys())
    n_sectors = len(sector_names)
    print(f"板块数: {n_sectors}")
    print(f"设备: {DEVICE}")
    
    dataset = SectorRotationDataset(features, lookback=30, horizon=5)
    print(f"训练样本数: {len(dataset)}")
    
    if len(dataset) < 50:
        print("数据不足，跳过训练")
        return None
    
    trainer = RotationTrainer(n_sectors, lookback=30, horizon=5)
    
    if trainer.load():
        print("在已有模型基础上继续训练")
    
    history = trainer.train(dataset, epochs=epochs, batch_size=128)
    trainer.save()
    
    norm_path = os.path.join(MODEL_DIR, 'norm_params.pkl')
    with open(norm_path, 'wb') as f:
        pickle.dump({'mean': dataset.mean, 'std': dataset.std, 'sector_names': sector_names}, f)
    
    print(f"\n训练完成! 最终loss: {history[-1]['loss']:.4f}")
    return trainer


def predict_rotation(trainer, sector_data):
    """
    用训练好的模型预测板块轮动
    返回: dict[板块名] -> {pred_mom, pred_phase, rotation_score, phase_name}
    """
    if trainer is None:
        return None
    
    features = prepare_sector_features(sector_data)
    sector_names = sorted(features.keys())
    
    # 加载标准化参数
    norm_path = os.path.join(MODEL_DIR, 'norm_params.pkl')
    if os.path.exists(norm_path):
        with open(norm_path, 'rb') as f:
            norm = pickle.load(f)
        mean = norm['mean']
        std = norm['std']
    else:
        return None
    
    # 构建输入
    n_feat = 5
    lookback = 30
    x = np.zeros((lookback, len(sector_names), n_feat), dtype=np.float32)
    
    for i, name in enumerate(sector_names):
        d = features[name]
        T = min(len(d['returns']), lookback)
        for t in range(T):
            idx = len(d['returns']) - T + t
            x[t, i, 0] = d['returns'][idx]
            x[t, i, 1] = d['mom5'][idx] if idx < len(d['mom5']) else 0
            x[t, i, 2] = d['mom20'][idx] if idx < len(d['mom20']) else 0
            x[t, i, 3] = d['rsi'][idx] if idx < len(d['rsi']) else 50
            x[t, i, 4] = d['bias20'][idx] if idx < len(d['bias20']) else 0
    
    # 标准化
    x = (x - mean) / std
    
    # 预测
    result = trainer.predict(x)
    
    phase_names = ['底部区', '上升期', '顶部区', '下降期', '震荡期']
    predictions = {}
    
    for i, name in enumerate(sector_names):
        phase_probs = result['pred_phase_probs'][i]
        pred_phase_idx = int(np.argmax(phase_probs))
        
        predictions[name] = {
            'pred_mom': float(result['pred_mom'][i]),
            'pred_phase': phase_names[pred_phase_idx],
            'pred_phase_probs': {phase_names[j]: float(phase_probs[j]) for j in range(5)},
            'rotation_score': float(result['rotation_score'][i]),
            'confidence': float(phase_probs[pred_phase_idx]),
        }
    
    return predictions


if __name__ == '__main__':
    # 测试
    print(f"设备: {DEVICE}")
    model = SectorRotationLSTM(n_sectors=6, n_features=5)
    x = torch.randn(2, 30, 6, 5)
    mom, phase, rot = model(x)
    print(f"动量输出: {mom.shape}")
    print(f"阶段输出: {phase.shape}")
    print(f"轮动得分: {rot.shape}")
    print(f"模型参数量: {sum(p.numel() for p in model.parameters()):,}")
