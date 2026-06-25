#!/usr/bin/env python3
"""
A股盘后报告 — GitHub Pages 自动部署脚本
=========================================
用法: python3 deploy_to_github.py

前提:
  1. 你已经注册了 GitHub 账号
  2. 创建了仓库（比如叫 a-stock-report）
  3. 本地装了 git

这个脚本做的事情:
  1. 把最新生成的 HTML 文件改名为 index.html
  2. 提交到 GitHub 仓库
  3. GitHub Pages 自动更新网站

【零基础操作步骤】看 deploy_steps.md
"""

import os
import subprocess
import shutil
from pathlib import Path
from datetime import datetime

# ============================================================
# 【你只需要改这一个地方】
# ============================================================
GITHUB_REPO_URL = "https://github.com/yanmingxin1688/a-stock-report.git"
# 改成你自己的 GitHub 仓库地址
# 比如：https://github.com/zhangsan/a-stock-report.git

# ============================================================
# 你可以不改的部分
# ============================================================
OUTPUTS_DIR = Path(__file__).parent
DEPLOY_DIR = OUTPUTS_DIR / "_deploy"


def find_latest_report():
    """找到最新生成的报告文件"""
    reports = sorted(OUTPUTS_DIR.glob("a_stock_daily_summary_*.html"))
    if not reports:
        print("❌ 没找到任何报告文件！请先运行 generate_report.py")
        return None
    latest = reports[-1]
    print(f"📄 最新报告: {latest.name}")
    return latest


def deploy(report_path):
    """把报告部署到 GitHub Pages"""
    # 1. 准备部署目录
    if DEPLOY_DIR.exists():
        shutil.rmtree(DEPLOY_DIR)

    print("📥 正在克隆 GitHub 仓库...")
    result = subprocess.run(
        ["git", "clone", GITHUB_REPO_URL, str(DEPLOY_DIR)],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"⚠️  克隆仓库失败（可能仓库还没创建）:\n{result.stderr}")
        print("\n💡 第一次使用的话，先创建本地仓库:")
        DEPLOY_DIR.mkdir(exist_ok=True)
        subprocess.run(["git", "init"], cwd=str(DEPLOY_DIR))
        subprocess.run(["git", "checkout", "-b", "main"], cwd=str(DEPLOY_DIR))
    else:
        print("✅ 仓库克隆成功")

    # 2. 复制报告为 index.html
    index_path = DEPLOY_DIR / "index.html"
    shutil.copy(report_path, index_path)
    print(f"📋 已复制报告 → {index_path}")

    # 3. Git 提交
    print("📤 正在提交并推送...")
    subprocess.run(["git", "add", "index.html"], cwd=str(DEPLOY_DIR))
    subprocess.run(
        ["git", "commit", "-m", f"更新报告: {datetime.now().strftime('%Y-%m-%d %H:%M')}"],
        cwd=str(DEPLOY_DIR)
    )
    result = subprocess.run(
        ["git", "push", "origin", "main"],
        cwd=str(DEPLOY_DIR),
        capture_output=True, text=True
    )

    if result.returncode == 0:
        print("✅ 推送成功！网站已更新。")
        print("🔗 你的网站地址: https://你的用户名.github.io/a-stock-report/")
    else:
        print(f"⚠️  推送可能需要你配置 GitHub 认证:\n{result.stderr}")


if __name__ == "__main__":
    report = find_latest_report()
    if report:
        deploy(report)
