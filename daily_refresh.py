#!/usr/bin/env python3
"""
定时任务管理器 — 每日收盘后自动更新数据+分析+模型
支持：手动触发 / cron定时 / App启动时自动调度
"""
import json, os, subprocess, sys
from datetime import datetime, timedelta

DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(DIR, 'schedule_log.json')


def get_last_run():
    """获取上次运行时间"""
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE) as f:
            data = json.load(f)
            return data.get('last_run', '')
    return ''


def set_last_run():
    """记录本次运行时间"""
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with open(LOG_FILE, 'w') as f:
        json.dump({'last_run': now, 'status': 'completed'}, f)
    return now


def should_run_now():
    """判断是否需要运行（每天收盘后只运行一次）"""
    last_run = get_last_run()
    if not last_run:
        return True
    try:
        last_dt = datetime.strptime(last_run, '%Y-%m-%d %H:%M:%S')
        now = datetime.now()
        # 如果上次运行是在今天15:00之后，且现在是第二天，才重新运行
        if now.date() > last_dt.date() and now.hour >= 15:
            return True
        # 如果上次运行超过24小时，重新运行
        if (now - last_dt).total_seconds() > 86400:
            return True
        return False
    except:
        return True


def run_scheduled_task():
    """运行定时任务：数据刷新 + 分析 + 模型训练"""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 开始定时任务...")
    
    steps = [
        ("获取最新行情数据", "data_engine.py"),
        ("运行高级分析", None),  # 用内联脚本
        ("深度学习训练", "train_and_predict.py"),
    ]
    
    for step_name, script in steps:
        print(f"  [{datetime.now().strftime('%H:%M:%S')}] {step_name}...")
        if script:
            try:
                r = subprocess.run(
                    [sys.executable, os.path.join(DIR, script)],
                    capture_output=True, text=True, timeout=600, cwd=DIR
                )
                if r.returncode == 0:
                    print(f"  ✓ {step_name} 完成")
                else:
                    print(f"  ⚠ {step_name} 有问题: {r.stderr[:100]}")
            except Exception as e:
                print(f"  ✗ {step_name} 失败: {e}")
        else:
            # 运行内联分析脚本
            try:
                r = subprocess.run(
                    [sys.executable, "-c", f"import sys; sys.path.insert(0,'{DIR}'); exec(open('{DIR}/full_analysis.py').read())"],
                    capture_output=True, text=True, timeout=300, cwd=DIR
                )
                print(f"  ✓ {step_name} 完成")
            except Exception as e:
                print(f"  ✗ {step_name} 失败: {e}")
    
    # 记录运行时间
    last_run = set_last_run()
    print(f"  [{datetime.now().strftime('%H:%M:%S')}] 定时任务完成，下次运行: 明天15:00后")
    return last_run


def get_schedule_status():
    """获取定时任务状态"""
    last_run = get_last_run()
    now = datetime.now()
    
    # 计算下次运行时间
    if last_run:
        try:
            last_dt = datetime.strptime(last_run, '%Y-%m-%d %H:%M:%S')
            if now.hour >= 15:
                next_run = (now + timedelta(days=1)).strftime('%Y-%m-%d 15:00')
            else:
                next_run = now.strftime('%Y-%m-%d 15:00')
        except:
            next_run = '未知'
    else:
        next_run = '首次运行待执行'
    
    return {
        'last_run': last_run or '从未运行',
        'next_run': next_run,
        'auto_refresh': should_run_now(),
        'schedule': '每个交易日 15:05 自动刷新',
    }


def install_cron():
    """安装 cron 定时任务（macOS）"""
    cron_cmd = f'5 15 * * 1-5 cd {DIR} && /opt/miniconda3/bin/python3 {DIR}/daily_refresh.py >> {DIR}/cron.log 2>&1'
    
    # 检查是否已安装
    result = subprocess.run(['crontab', '-l'], capture_output=True, text=True)
    current = result.stdout
    
    if 'daily_refresh.py' in current:
        print("定时任务已安装")
        return
    
    # 添加到 crontab
    new_cron = current.rstrip() + '\n' + cron_cmd + '\n'
    subprocess.run(['crontab', '-'], input=new_cron, text=True)
    print(f"✓ 定时任务已安装: 每个交易日 15:05 自动刷新")
    print(f"  日志: {DIR}/cron.log")


def remove_cron():
    """移除 cron 定时任务"""
    result = subprocess.run(['crontab', '-l'], capture_output=True, text=True)
    current = result.stdout
    lines = [l for l in current.split('\n') if 'daily_refresh.py' not in l]
    subprocess.run(['crontab', '-'], input='\n'.join(lines), text=True)
    print("✓ 定时任务已移除")


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='定时任务管理')
    parser.add_argument('action', choices=['run', 'status', 'install', 'remove', 'test'])
    args = parser.parse_args()
    
    if args.action == 'run':
        run_scheduled_task()
    elif args.action == 'status':
        status = get_schedule_status()
        print(f"上次运行: {status['last_run']}")
        print(f"下次运行: {status['next_run']}")
        print(f"自动刷新: {'是' if status['auto_refresh'] else '否'}")
        print(f"计划: {status['schedule']}")
    elif args.action == 'install':
        install_cron()
    elif args.action == 'remove':
        remove_cron()
    elif args.action == 'test':
        print("测试运行...")
        run_scheduled_task()
