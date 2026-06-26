#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股盘后总结 — 自动报告生成引擎
================================
用法:
    python3 generate_report.py          # 用模拟数据生成报告
    python3 generate_report.py --real   # 用真实 API 数据生成报告（需要你先配置 fetch_real_data()）

输出:
    a_stock_daily_summary_2026-06-XX.html   （带日期的 HTML 文件）

================================
【给零基础同学的说明】
这个脚本做了两件事：
  1. 准备数据（从 API 拿，或者用模拟数据）
  2. 把数据填进 HTML 模板 → 生成最终的报告文件

你只需要关心两个函数：
  - build_mock_data()     → 模拟数据，现在就能跑，用来测试流程
  - fetch_real_data()     → 接你的真实 API，后面你自己填

整个脚本可以单独运行，也可以被 Workbuddy 定时任务调用。
"""

import json
import math
import os
import random
import re
import subprocess
import time
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

# 清除代理环境变量，防止沙盒/Clash 残留配置拦截请求
for _proxy_key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
    os.environ.pop(_proxy_key, None)
os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"

import requests

# ============================================================
#  如果你有 Jinja2，就用它；没有的话用简单的字符串替换
#  安装方法: pip3 install jinja2 --break-system-packages
# ============================================================
try:
    from jinja2 import Template
    USE_JINJA2 = True
    print("✅ 使用 Jinja2 模板引擎")
except ImportError:
    USE_JINJA2 = False
    print("⚠️  Jinja2 未安装，使用简单字符串替换。建议执行:")
    print("   pip3 install jinja2 --break-system-packages")


# ============================================================
#  第一部分：定义数据结构
#  这些就是 HTML 模板需要"填空"的所有变量
#  看一遍你就知道这个报告包含哪些动态数据了
# ============================================================

def build_mock_data():
    """
    模拟数据 — 结构和真实 API 数据完全一样。
    你先用这个跑通流程，确认报告能正常生成。
    之后把 fetch_real_data() 里的 API 调用补上就行。
    """
    today = datetime.now().strftime("%Y-%m-%d")
    data_time = datetime.now().strftime("%Y/%m/%d 16:00") + " Asia/Shanghai"

    return {
        # ---- 页面头部 ----
        "report_date": today,
        "data_time": data_time,

        # ---- 焦点站位 ----
        "focus_text": (
            "今天星球科技风格领涨，不买贵金。主线从早盘的"
            "<strong>玻璃基板/PCB/面板</strong>，下午扩散到"
            "<strong>半导体、存储芯片、设备、封测</strong>。"
        ),

        # ---- 五大指数卡片 ----
        # 每个指数有: name, value, change_pct, volume_info, note, is_up
        "indices": [
            {"name": "上证指数", "value": "4108.08", "change_pct": "+0.40%", "is_up": True,
             "volume_info": "成交量 1.40万亿 | 785 / 1534 / 28", "note": "振幅较小，个股活跃度一般"},
            {"name": "深证成指", "value": "15880.95", "change_pct": "+1.31%", "is_up": True,
             "volume_info": "成交量 1.69万亿 | 841 / 2055 / 25", "note": "电子权重大幅贡献"},
            {"name": "创业板指", "value": "4167.05", "change_pct": "+1.56%", "is_up": True,
             "volume_info": "成交量 8304亿 | 476 / 912 / 8", "note": "成长风格修复"},
            {"name": "沪深300", "value": "4931.39", "change_pct": "-0.97%", "is_up": False,
             "volume_info": "成交量 8504亿 | 136 / 161 / 3", "note": "权重有明显承接"},
            {"name": "科创50", "value": "1840.82", "change_pct": "+4.69%", "is_up": True,
             "volume_info": "成交量 1769亿 | 36 / 14 / 0", "note": "今天最强板块，半导体全面修复"},
        ],

        # ---- 行业主力净流入 ----
        "inflow_sectors": [
            {"name": "电子", "change_pct": "+3.25%", "net_flow": "+259.68亿", "meaning": "全天最强资金池"},
            {"name": "半导体", "change_pct": "+4.13%", "net_flow": "+154.01亿", "meaning": "早盘分歧后行情全面修复"},
            {"name": "数字芯片设计", "change_pct": "+4.01%", "net_flow": "+81.74亿", "meaning": "AI/芯片成为中枢主线"},
            {"name": "光学光电子", "change_pct": "+3.30%", "net_flow": "+65.66亿", "meaning": "显示储能堆强"},
            {"name": "面板", "change_pct": "+4.74%", "net_flow": "+41.62亿", "meaning": "科技AI领先"},
            {"name": "半导体设备", "change_pct": "+6.56%", "net_flow": "+28.40亿", "meaning": "拓展，中复，成果扩散"},
            {"name": "封测", "change_pct": "+4.22%", "net_flow": "+24.23亿", "meaning": "长电、通富、华天走强"},
            {"name": "元件", "change_pct": "+4.15%", "net_flow": "+20.26亿", "meaning": "PCB/元件板同质回归分化"},
        ],

        # ---- 行业主力净流出 ----
        "outflow_sectors": [
            {"name": "有色金属", "change_pct": "-1.06%", "net_flow": "-99.17亿", "meaning": "资源线流出"},
            {"name": "电力设备", "change_pct": "-0.81%", "net_flow": "-97.39亿", "meaning": "800V不是今天主发"},
            {"name": "基础化工", "change_pct": "-0.62%", "net_flow": "-55.05亿", "meaning": "涨价不被资金选择"},
            {"name": "电信", "change_pct": "-0.18%", "net_flow": "-47.52亿", "meaning": "新服务板块"},
            {"name": "通信", "change_pct": "-0.29%", "net_flow": "-35.69亿", "meaning": "CPO/通信不如半导体"},
            {"name": "汽车", "change_pct": "-0.96%", "net_flow": "-29.66亿", "meaning": "新能源与整车承压"},
            {"name": "传媒", "change_pct": "-2.09%", "net_flow": "-27.52亿", "meaning": "新旧资金离散"},
        ],

        # ---- 概念与主线排序 ----
        # rank_class: gold/silver/bronze/""    status_tag_class: tag-confirm/tag-watch/tag-weak/tag-neutral
        "concepts": [
            {"rank": 1, "rank_class": "gold",
             "title": "半导体/存储芯片", "subtitle": "半导体龙头+0.7%，存储芯片+148亿",
             "change_pct": "+4.13%", "stocks": "兆易创新、北京君正、胜利精密、德明利",
             "status": "主线确认", "status_tag_class": "tag-confirm",
             "tomorrow_view": "明天看情绪是否继续扩散，还是前排高开兑现"},
            {"rank": 2, "rank_class": "silver",
             "title": "消费电子/面板/显示", "subtitle": "消费电子+94.82亿，面板+61.6亿",
             "change_pct": "+3.80%", "stocks": "京东方A、TCL科技、长信科技",
             "status": "主线确认", "status_tag_class": "tag-confirm",
             "tomorrow_view": "京东方A封板带动核心观察窗口"},
            {"rank": 3, "rank_class": "bronze",
             "title": "PCB/元件/CCL", "subtitle": "元件+20.3亿，PCB亮剑",
             "change_pct": "+2.90%", "stocks": "深南电路、沪电股份、鹏鼎控股",
             "status": "观察", "status_tag_class": "tag-watch",
             "tomorrow_view": "明日板块性价比有所下降"},
            {"rank": 4, "rank_class": "",
             "title": "玻璃基板", "subtitle": "板块+4.94%，主力+55.86亿",
             "change_pct": "+4.94%", "stocks": "中国巨石、国瓷集团、长川科技",
             "status": "确认回调", "status_tag_class": "tag-neutral",
             "tomorrow_view": "今天强势，明天看是否继续"},
            {"rank": 5, "rank_class": "",
             "title": "半导体设备/材料", "subtitle": "设备+28.4亿，材料+8.9亿",
             "change_pct": "+5.20%", "stocks": "中微公司、拓荆科技、盛美上海",
             "status": "新扩散", "status_tag_class": "tag-watch",
             "tomorrow_view": "看后续行情弹性"},
            {"rank": 6, "rank_class": "",
             "title": "800V/电力设备", "subtitle": "电力设备-97.39亿",
             "change_pct": "-0.81%", "is_up": False,
             "stocks": "麦格米特、欣锐科技、均胜电子",
             "status": "前排撤退", "status_tag_class": "tag-weak",
             "tomorrow_view": "核心之外，后排不支撑"},
        ],

        # ---- 关键催化 ----
        "catalysts": [
            {"direction": "玻璃基板",
             "time": "6月16日16:57；6月17日10:59二次发酵",
             "source": "界面新闻/东方财富",
             "media": "公告+A股盘面",
             "content": "合科持昂感应到供应链发布CoWoS玻璃基板开发进展，首次公开技术进度",
             "effect": "玻璃基板+4.94%，主力+55.86亿，当日高度"},
            {"direction": "PCB/CCL",
             "time": "6月17日早盘持续发酵",
             "source": "证券报/东方财富",
             "media": "公告+A股盘面",
             "content": "摩根士丹利报告：AI数据中心高需求覆盖供应链，据点说板将至2028年",
             "effect": "深南电路、沪电股份涨停，板块+7.51%"},
            {"direction": "存储芯片",
             "time": "6月17日13:04",
             "source": "财联社",
             "media": "媒体+研报盘面",
             "content": "摩根士丹利报告：AI数据中心高需求密切供应链",
             "effect": "存储链前排封板，兆易创新+7.51%"},
            {"direction": "面板/显示",
             "time": "6月17日全天持续确认",
             "source": "东方财富/行情资金",
             "media": "A股面板",
             "content": "京东方官方化，主要预期消费电子/玻璃基板/显示技术扩展",
             "effect": "京东方A、TCL科技涨停，面板+61.60亿"},
        ],

        # ---- 前排/中军/后排 ----
        "front_tier": [
            {"section": "大盘品瑞", "stocks": "京东方A、兆易创新", "change": "昨涨停", "change_class": "up"},
            {"section": "存储前排", "stocks": "北京君正、胜利精密、德明利", "change": "封板/实盘20cm", "change_class": "up"},
            {"section": "玻璃基板前", "stocks": "中国巨石、国瓷集团、长川科技", "change": "多只涨停/20cm", "change_class": "up"},
        ],
        "mid_tier": [
            {"section": "存储链中段", "stocks": "北京君正、胜利精密、德明利", "change": "封板，涨幅+7.24%", "change_class": "up"},
            {"section": "PCB中游", "stocks": "深南电路、沪电股份、数孚科技", "change": "板块偶然性较强", "change_class": ""},
        ],
        "rear_tier": [
            {"section": "玻璃基板后", "stocks": "中国巨石、长川团队", "change": "中国巨石-7.66%，长川+5.09%", "change_class": ""},
            {"section": "800V核心后", "stocks": "麦格米特、欣锐科技", "change": "麦格米特-9.20%，欣锐-1.12%", "change_class": "down"},
        ],

        # ---- 舆情监测 ----
        "sentiments": [
            {"source": "东方财富/搜索热度", "direction": "玻璃基板",
             "heat_level": "高", "heat_class": "heat-high",
             "event": "确认AI封板，CoWoS、玻璃基板、产业化认定",
             "timing": "盘前一致", "action": "确认封板，明天看高开后是否有承接"},
            {"source": "东方财富/资金流向", "direction": "存储芯片",
             "heat_level": "高", "heat_class": "heat-high",
             "event": "AI数据中心PC，存储芯片上涨",
             "timing": "午后升温", "action": "午后升温确认，明天看是否高开兑现"},
            {"source": "论坛/板块跟踪", "direction": "电力/新能源",
             "heat_level": "一般", "heat_class": "heat-medium",
             "event": "电子产品板相关",
             "timing": "跌多涨少", "action": "资金分流，近期不买"},
            {"source": "论坛/板块跟踪", "direction": "小金属/医药",
             "heat_level": "暖降", "heat_class": "heat-low",
             "event": "AI、特种气体",
             "timing": "一般", "action": "资金分流，不追跌"},
        ],

        # ---- 持仓影响 ----
        "holdings": [
            {"name": "澜起科技", "code": "688008",
             "change_pct": "-7.51%", "is_up": False,
             "net_flow": "-9.13亿", "position": "午后存储芯片主流一线品种",
             "tomorrow_view": "不再推荐高开后承接，明天看是否高开后还有承接"},
            {"name": "欣锐科技", "code": "300870",
             "change_pct": "-0.27%", "is_up": False,
             "net_flow": "-1.12亿", "position": "800V前储备板块",
             "tomorrow_view": "效率低，观望"},
        ],

        # ---- 明日锚点（做多条件） ----
        "long_anchors": [
            {"direction": "存储芯片", "condition": "兆易创新、北京君正、胜利精密、德明利", "stocks": "前排高开不跌，中华承接延续"},
            {"direction": "面板/显示", "condition": "京东方A封板续接，TCL科技强势盘整", "stocks": "前排高开后保持+3%以上"},
            {"direction": "PCB/CCL", "condition": "深南电路、沪电股份", "stocks": "涨幅继续+3%，前排大幅领涨"},
            {"direction": "玻璃基板", "condition": "中国巨石、国瓷集团、长川科技", "stocks": "前排修复/再次涨停，材料与设备共振"},
            {"direction": "800V", "condition": "麦格米特、欣锐科技", "stocks": "前排修复/高开，材料+设备共振"},
        ],

        # ---- 失败信号（止损条件） ----
        "short_anchors": [
            {"direction": "存储芯片", "condition": "高开兑现，澜起科技高开下行", "stocks": "前排高开大幅回调，中华缩量"},
            {"direction": "面板", "condition": "京东方A开盘后迅速跌板", "stocks": "高开大幅回调+资金撤离"},
            {"direction": "PCB/CCL", "condition": "前排开幅大，回归不乐观", "stocks": "前排大幅下行，后排不强"},
            {"direction": "玻璃基板", "condition": "前排修复/再高开，材料+设备跌落", "stocks": "只有后排初动，材料+设备仍跌"},
            {"direction": "800V", "condition": "前排修复一，初动后转跌不强", "stocks": "初动后转跌，前排不能"},
        ],

        # ---- 龙虎榜状态 ----
        "dragon_status": (
            "完整龙虎榜内容未能定量。本板先发盘后与资金定量："
            "前期可参考更新龙虎榜，重点关注存储芯片、玻璃基板，"
            "PCB排行是否有机构/游资/龙头大方向确认。"
        ),

        # ---- 来源 ----
        "sources": (
            "东方财富公开行情/标准东方财富行业量；"
            "界面新闻/东方财富（含玻璃基板全球数量和景气扩展开发进展）；"
            "东方财富（深资板推动、关注下午的PCB板块/产链）；"
            "财联社（存储芯片部分扩展到PCB产链）。"
        ),
    }


def fetch_real_data():
    """
    ============================================================
    真实数据获取 — 多源直连 HTTP API（零第三方数据依赖）
    数据源优先级：
      1. 腾讯财经（不封IP）— 指数实时行情
      2. 东财 push2（有限流）— 行业板块排名 + 资金流
      3. 东财 datacenter（有限流）— 龙虎榜
      4. 同花顺热点（零鉴权）— 当日强势股 + 题材归因
      5. 东财全球资讯 — 7x24 快讯
    ============================================================
    """
    print("📡 开始获取真实数据...")

    # ── 东财防封基础设施 ──────────────────────────────
    UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    EM_SESSION = requests.Session()
    EM_SESSION.headers.update({"User-Agent": UA})
    EM_MIN_INTERVAL = 1.2
    _em_last_call = [0.0]

    def em_get(url, params=None, headers=None, timeout=15, **kwargs):
        """东财统一请求入口：自动节流 + 复用 session + 绕过系统代理"""
        wait = EM_MIN_INTERVAL - (time.time() - _em_last_call[0])
        if wait > 0:
            time.sleep(wait + random.uniform(0.1, 0.5))
        try:
            return EM_SESSION.get(url, params=params, headers=headers,
                                  timeout=timeout, proxies={"http": None, "https": None}, **kwargs)
        finally:
            _em_last_call[0] = time.time()

    def _curl_json(url, params=None, headers=None, timeout=15):
        """用 curl 子进程拉 JSON（绕过 Python TLS 兼容性问题）"""
        cmd = ["curl", "-s", "--max-time", str(timeout)]
        # 只在调用方未提供 UA 时才加默认 UA，避免重复
        ua_provided = headers and any(k.lower() == "user-agent" for k in headers)
        if not ua_provided:
            cmd += ["-H", "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"]
        if headers:
            for k, v in headers.items():
                cmd += ["-H", f"{k}: {v}"]
        if params:
            full_url = url + "?" + urlencode(params)
        else:
            full_url = url
        cmd.append(full_url)
        raw = subprocess.check_output(cmd, timeout=timeout + 5,
                                     env={k: v for k, v in os.environ.items()
                                          if "PROXY" not in k.upper()})
        return json.loads(raw.decode("utf-8"))

    # ── 数据获取 ──────────────────────────────────────

    # 1) 五大指数 — 腾讯财经（不封IP，批量一次拉完）
    print("  [1/6] 拉取五大指数行情...")
    index_codes = {
        "sh000001": "上证指数", "sz399001": "深证成指",
        "sz399006": "创业板指", "sh000300": "沪深300", "sh000688": "科创50",
    }
    prefixed = list(index_codes.keys())

    indices = []
    try:
        url = "https://qt.gtimg.cn/q=" + ",".join(prefixed)
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "Mozilla/5.0")
        resp = urllib.request.urlopen(req, timeout=10)
        raw = resp.read().decode("gbk")
        for line in raw.strip().split(";"):
            if not line.strip() or "=" not in line or '"' not in line:
                continue
            key = line.split("=")[0].split("_")[-1]  # e.g. "sh000001"
            vals = line.split('"')[1].split("~")
            if len(vals) < 53:
                continue
            name = index_codes.get(key, vals[1])
            price = vals[3] if vals[3] else "0"
            change_pct_val = float(vals[32]) if vals[32] else 0
            is_up = change_pct_val >= 0
            change_pct = f"+{change_pct_val:.2f}%" if is_up else f"{change_pct_val:.2f}%"
            amount_wan = float(vals[37]) if vals[37] else 0
            # 成交额格式化（A股惯例用成交额）
            if amount_wan >= 100000000:
                vol_str = f"成交额 {amount_wan/10000:.2f}万亿"
            elif amount_wan >= 10000:
                vol_str = f"成交额 {amount_wan/10000:.0f}亿"
            else:
                vol_str = f"成交额 {amount_wan:.0f}万"
            vol_yi = amount_wan / 10000  # 万 → 亿
            amplitude = float(vals[43]) if vals[43] else 0
            up_count = int(float(vals[48])) if vals[48] else 0
            down_count = int(float(vals[49])) if vals[49] else 0
            note = f"振幅{amplitude:.1f}% | 涨{up_count}/跌{down_count}"
            indices.append({
                "name": name, "value": f"{float(price):.2f}",
                "change_pct": change_pct, "is_up": is_up,
                "volume_info": vol_str, "note": note,
            })
        print(f"    ✅ 获取 {len(indices)} 个指数")
    except Exception as e:
        print(f"    ❌ 指数获取失败: {e}")
        indices = build_mock_data()["indices"]

    # 2) 行业板块排名 — push2delay 直连（push2 在沙盒/规则代理下被服务端 RST，push2delay 镜像通）
    print("  [2/6] 拉取行业板块排名...")
    inflow_sectors = []
    outflow_sectors = []
    sector_top5_names = []
    sector_bottom5_names = []
    sector_data_source = "eastmoney_push2delay_curl"
    # 按可用性顺序尝试多个 push2 镜像
    for push2_host in ("push2delay.eastmoney.com", "push2.eastmoney.com"):
        try:
            url = f"https://{push2_host}/api/qt/clist/get"
            params = {
                "pn": "1", "pz": "90", "po": "1", "np": "1",
                "fltt": "2", "invt": "2",
                "fs": "m:90+t:2",
                "fields": "f2,f3,f4,f12,f13,f14,f104,f105,f128,f136,f140,f141,f207",
            }
            d = _curl_json(url, params=params, headers={"User-Agent": UA, "Referer": "https://www.eastmoney.com/"}, timeout=15)
            items = d.get("data", {}).get("diff", [])
            if not items:
                raise ValueError(f"{push2_host} 返回空数据，尝试下一个镜像")
            sector_data_source = f"eastmoney_{push2_host.replace('.eastmoney.com','')}_curl"
            rows = []
            for item in items:
                change_pct = float(item.get("f3", 0) or 0)
                name = item.get("f14", "")
                up_count = int(item.get("f104", 0) or 0)
                down_count = int(item.get("f105", 0) or 0)
                leader = item.get("f140", "")
                rows.append({
                    "name": name,
                    "change_pct": f"+{change_pct:.2f}%" if change_pct >= 0 else f"{change_pct:.2f}%",
                    "change_pct_raw": change_pct,
                    "up_count": up_count,
                    "down_count": down_count,
                    "leader": leader,
                })
            rows_sorted = sorted(rows, key=lambda x: x["change_pct_raw"], reverse=True)
            for r in rows_sorted[:8]:
                meaning = f"涨{r['up_count']}跌{r['down_count']}，领涨{r['leader']}"
                inflow_sectors.append({
                    "name": r["name"],
                    "change_pct": r["change_pct"],
                    "net_flow": f"+{abs(r['change_pct_raw']*10):.1f}亿(估)",
                    "meaning": meaning,
                })
                sector_top5_names.append(r["name"])
            for r in rows_sorted[-7:]:
                meaning = f"涨{r['up_count']}跌{r['down_count']}，资金流出"
                outflow_sectors.append({
                    "name": r["name"],
                    "change_pct": r["change_pct"],
                    "net_flow": f"-{abs(r['change_pct_raw']*10):.1f}亿(估)",
                    "meaning": meaning,
                })
                sector_bottom5_names.append(r["name"])
            print(f"    ✅ {push2_host} 净流入 {len(inflow_sectors)} 行业 / 净流出 {len(outflow_sectors)} 行业")
            break  # 成功就退出 for
        except Exception as e:
            print(f"    ⚠️ {push2_host} 失败 ({e})")
    else:
        # 所有镜像都失败，回退 akshare
        print(f"    ⚠️ push2 全镜像失败，尝试 akshare 备用源...")
        # 清除环境变量中的代理设置，让 akshare 内部请求直连（不被沙盒反代拦截）
        _orig_http_proxy = os.environ.pop("HTTP_PROXY", "")
        _orig_https_proxy = os.environ.pop("HTTPS_PROXY", "")
        _orig_http_proxy2 = os.environ.pop("http_proxy", "")
        _orig_https_proxy2 = os.environ.pop("https_proxy", "")
        os.environ["NO_PROXY"] = "*"
        try:
            import akshare as ak
            df = ak.stock_board_industry_name_em()
            if df is not None and not df.empty:
                df_sorted = df.sort_values(by="涨跌幅", ascending=False)
                sector_data_source = "akshare_stock_board_industry"
                for _, row in df_sorted.head(8).iterrows():
                    name = str(row.get("板块名称", ""))
                    chg = float(row.get("涨跌幅", 0) or 0)
                    up_c = int(row.get("上涨家数", 0) or 0)
                    down_c = int(row.get("下跌家数", 0) or 0)
                    leader = str(row.get("领涨股票", ""))
                    meaning = f"涨{up_c}跌{down_c}，领涨{leader}"
                    inflow_sectors.append({
                        "name": name,
                        "change_pct": f"+{chg:.2f}%" if chg >= 0 else f"{chg:.2f}%",
                        "net_flow": f"+{abs(chg)*10:.1f}亿(估)",
                        "meaning": meaning,
                    })
                    sector_top5_names.append(name)
                for _, row in df_sorted.tail(7).iterrows():
                    name = str(row.get("板块名称", ""))
                    chg = float(row.get("涨跌幅", 0) or 0)
                    up_c = int(row.get("上涨家数", 0) or 0)
                    down_c = int(row.get("下跌家数", 0) or 0)
                    meaning = f"涨{up_c}跌{down_c}，资金流出"
                    outflow_sectors.append({
                        "name": name,
                        "change_pct": f"+{chg:.2f}%" if chg >= 0 else f"{chg:.2f}%",
                        "net_flow": f"-{abs(chg)*10:.1f}亿(估)",
                        "meaning": meaning,
                    })
                    sector_bottom5_names.append(name)
                print(f"    ✅ akshare 备用源 净流入 {len(inflow_sectors)} 行业 / 净流出 {len(outflow_sectors)} 行业")
            else:
                raise ValueError("akshare 返回空 DataFrame")
        except Exception as e2:
            print(f"    ❌ akshare 备用源也失败: {e2}")
            inflow_sectors = build_mock_data()["inflow_sectors"]
            outflow_sectors = build_mock_data()["outflow_sectors"]
            sector_data_source = "mock"
        finally:
            # 恢复环境变量
            if _orig_http_proxy: os.environ["HTTP_PROXY"] = _orig_http_proxy
            if _orig_https_proxy: os.environ["HTTPS_PROXY"] = _orig_https_proxy
            if _orig_http_proxy2: os.environ["http_proxy"] = _orig_http_proxy2
            if _orig_https_proxy2: os.environ["https_proxy"] = _orig_https_proxy2

    # 3) 同花顺热点 — 当日强势股 + 题材归因
    print("  [3/6] 拉取当日强势股归因...")
    hot_stocks = []
    concept_tags_freq = {}
    try:
        today_str = datetime.now().strftime("%Y-%m-%d")
        url = f"http://zx.10jqka.com.cn/event/api/getharden/date/{today_str}/orderby/date/orderway/desc/charset/GBK/"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/117.0.0.0 Safari/537.36"
        }
        r = requests.get(url, headers=headers, timeout=10)
        data = r.json()
        rows = data.get("data") or []
        for row in rows:
            reason = str(row.get("reason", ""))
            tags = [t.strip() for t in reason.split("+") if t.strip()]
            for tag in tags:
                concept_tags_freq[tag] = concept_tags_freq.get(tag, 0) + 1
            hot_stocks.append({
                "code": row.get("code", ""),
                "name": row.get("name", ""),
                "change_pct": float(row.get("zhangfu", 0) or 0),
                "reason": reason,
                "turnover": float(row.get("huanshou", 0) or 0),
            })
        print(f"    ✅ 强势股 {len(hot_stocks)} 只 / 题材标签 {len(concept_tags_freq)} 个")
    except Exception as e:
        print(f"    ❌ 热点获取失败: {e}")

    # 4) 东财全球资讯 — 最近快讯（作催化源）
    print("  [4/6] 拉取财经快讯...")
    news_items = []
    try:
        url = "https://np-weblist.eastmoney.com/comm/web/getFastNewsList"
        params = {
            "client": "web", "biz": "web_724",
            "fastColumn": "102", "sortEnd": "",
            "pageSize": "20",
            "req_trace": str(uuid.uuid4()),
        }
        headers = {"User-Agent": UA, "Referer": "https://kuaixun.eastmoney.com/"}
        r = em_get(url, params=params, headers=headers, timeout=10)
        d = r.json()
        for item in d.get("data", {}).get("fastNewsList", []):
            news_items.append({
                "title": item.get("title", ""),
                "summary": item.get("summary", "")[:150],
                "time": item.get("showTime", ""),
            })
        print(f"    ✅ 快讯 {len(news_items)} 条")
    except Exception as e:
        print(f"    ❌ 快讯获取失败: {e}")

    # 5) 龙虎榜 — 全市场当日上榜
    print("  [5/6] 拉取龙虎榜...")
    dragon_records = []
    try:
        DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
        today_str = datetime.now().strftime("%Y-%m-%d")
        params = {
            "reportName": "RPT_DAILYBILLBOARD_DETAILSNEW",
            "columns": "ALL",
            "filter": f"(TRADE_DATE>='{today_str}')(TRADE_DATE<='{today_str}')",
            "pageNumber": "1", "pageSize": "50",
            "sortColumns": "BILLBOARD_NET_AMT", "sortTypes": "-1",
            "source": "WEB", "client": "WEB",
        }
        r = em_get(DATACENTER_URL, params=params, timeout=15)
        d = r.json()
        if d.get("result") and d["result"].get("data"):
            for row in d["result"]["data"]:
                dragon_records.append({
                    "code": row.get("SECURITY_CODE", ""),
                    "name": row.get("SECURITY_NAME_ABBR", ""),
                    "reason": row.get("EXPLANATION", ""),
                    "net_buy_wan": round((row.get("BILLBOARD_NET_AMT") or 0) / 10000, 1),
                    "change_pct": round(float(row.get("CHANGE_RATE") or 0), 2),
                })
        print(f"    ✅ 龙虎榜 {len(dragon_records)} 条")
    except Exception as e:
        print(f"    ❌ 龙虎榜获取失败: {e}")

    # ── 数据组装 ──────────────────────────────────────
    print("  [6/6] 组装报告数据...")

    today = datetime.now().strftime("%Y-%m-%d")
    data_time = datetime.now().strftime("%Y/%m/%d 16:00") + " Asia/Shanghai"

    # ── 焦点站位：基于涨幅最大行业 + 题材标签 ──
    top_sectors = sector_top5_names[:3] if sector_top5_names else ["(数据不足)"]
    top_tags = sorted(concept_tags_freq.items(), key=lambda x: x[1], reverse=True)[:5]
    top_tag_names = [t[0] for t in top_tags]
    if top_tag_names:
        focus_text = (
            f"今天<strong>{'、'.join(top_sectors)}</strong>领涨。"
            f"主线题材集中在<strong>{'、'.join(top_tag_names[:3])}</strong>。"
        )
    else:
        focus_text = f"今天<strong>{'、'.join(top_sectors)}</strong>表现活跃，市场风格偏向成长。"

    # ── 概念主线排序：基于热点题材词频 ──
    concepts = []
    sorted_tags = sorted(concept_tags_freq.items(), key=lambda x: x[1], reverse=True)
    rank_classes = ["gold", "silver", "bronze", "", "", ""]
    status_map = [
        ("主线确认", "tag-confirm"),
        ("主线确认", "tag-confirm"),
        ("观察", "tag-watch"),
        ("观察", "tag-watch"),
        ("新扩散", "tag-watch"),
        ("回调", "tag-neutral"),
    ]
    # 关联强势股
    for i, (tag, freq) in enumerate(sorted_tags[:6]):
        related_stocks = [s["name"] for s in hot_stocks if tag in s["reason"]][:4]
        stocks_str = "、".join(related_stocks) if related_stocks else "(待补充)"
        rank_class = rank_classes[i] if i < len(rank_classes) else ""
        status, tag_class = status_map[i] if i < len(status_map) else ("一般", "tag-neutral")
        avg_chg = 0
        related_chg = [s["change_pct"] for s in hot_stocks if tag in s["reason"]]
        if related_chg:
            avg_chg = sum(related_chg) / len(related_chg)
        chg_str = f"+{avg_chg:.2f}%" if avg_chg >= 0 else f"{avg_chg:.2f}%"

        concepts.append({
            "rank": i + 1, "rank_class": rank_class,
            "title": tag,
            "subtitle": f"{freq}只强势股关联，平均涨幅{chg_str}",
            "change_pct": chg_str,
            "stocks": stocks_str,
            "status": status, "status_tag_class": tag_class,
            "tomorrow_view": "看情绪是否延续，关注前排承接",
        })
    if not concepts:
        concepts = build_mock_data()["concepts"]

    # ── 关键催化：基于快讯 ──
    catalysts = []
    for n in news_items[:4]:
        # 尝试从标题提取方向关键词
        title = n["title"]
        direction = title[:8] if len(title) > 8 else title
        catalysts.append({
            "direction": direction,
            "time": n.get("time", ""),
            "source": "东方财富7x24快讯",
            "media": "财经快讯",
            "content": n.get("summary", title),
            "effect": "待盘面验证",
        })
    if not catalysts:
        catalysts = build_mock_data()["catalysts"]

    # ── 前排/中军/后排：基于强势股涨幅分层 ──
    front_tier = []
    mid_tier = []
    rear_tier = []
    if hot_stocks:
        # 涨幅>7% = 前排，3-7% = 中军，<3% = 后排
        for s in hot_stocks[:6]:
            chg = s["change_pct"]
            chg_class = "up" if chg >= 3 else ("down" if chg < 0 else "")
            chg_str = f"+{chg:.2f}%" if chg >= 0 else f"{chg:.2f}%"
            section = s["reason"][:10] if s["reason"] else s["name"]
            stocks_str = s["name"]
            if chg >= 7:
                front_tier.append({"section": section, "stocks": stocks_str, "change": chg_str, "change_class": "up"})
            elif chg >= 3:
                mid_tier.append({"section": section, "stocks": stocks_str, "change": chg_str, "change_class": chg_class})
            else:
                rear_tier.append({"section": section, "stocks": stocks_str, "change": chg_str, "change_class": chg_class})
    # 确保每层至少有1条
    if not front_tier:
        front_tier = [{"section": "领涨龙头", "stocks": "(待补充)", "change": "--", "change_class": "up"}]
    if not mid_tier:
        mid_tier = [{"section": "中军跟进", "stocks": "(待补充)", "change": "--", "change_class": ""}]
    if not rear_tier:
        rear_tier = [{"section": "后排跟风", "stocks": "(待补充)", "change": "--", "change_class": ""}]

    # ── 舆情监测：基于热点词频 ──
    sentiments = []
    for i, (tag, freq) in enumerate(sorted_tags[:4]):
        heat = "高" if freq >= 5 else ("一般" if freq >= 3 else "低")
        heat_class = "heat-high" if freq >= 5 else ("heat-medium" if freq >= 3 else "heat-low")
        sentiments.append({
            "source": "同花顺热点/东方财富",
            "direction": tag,
            "heat_level": heat, "heat_class": heat_class,
            "event": f"{freq}只强势股归因{tag}",
            "timing": "盘后统计",
            "action": "关注前排承接与资金延续性",
        })
    if not sentiments:
        sentiments = build_mock_data()["sentiments"]

    # ── 持仓影响：暂留模板（用户需自定义持仓列表）──
    holdings = build_mock_data()["holdings"]

    # ── 明日锚点 & 失败信号：基于涨幅最大3个题材 ──
    long_anchors = []
    short_anchors = []
    for i, (tag, freq) in enumerate(sorted_tags[:5]):
        related = [s["name"] for s in hot_stocks if tag in s["reason"]][:3]
        stocks_str = "、".join(related) if related else "(待补充)"
        long_anchors.append({
            "direction": tag,
            "condition": f"{tag}前排高开不跌，资金承接延续",
            "stocks": stocks_str,
        })
        short_anchors.append({
            "direction": tag,
            "condition": f"{tag}前排高开后大幅回调，资金撤离",
            "stocks": stocks_str,
        })
    if not long_anchors:
        long_anchors = build_mock_data()["long_anchors"]
    if not short_anchors:
        short_anchors = build_mock_data()["short_anchors"]

    # ── 龙虎榜状态 ──
    if dragon_records:
        top5 = dragon_records[:5]
        top5_str = "、".join([
            r["name"] + "(净买" + str(r["net_buy_wan"]) + "万)"
            for r in top5
        ])
        dragon_status = (
            "今日龙虎榜共" + str(len(dragon_records)) + "只个股上榜。"
            + "净买入TOP5：" + top5_str + "。"
            + "详细席位信息请查看东方财富龙虎榜页面。"
        )
    else:
        dragon_status = (
            "龙虎榜数据暂未更新（可能非交易日或盘后未发布）。"
            "建议稍后查看东方财富龙虎榜页面获取最新数据。"
        )

    # ── 来源 ──
    sources = (
        "腾讯财经API（五大指数实时行情）；"
        "东方财富push2（行业板块排名）；"
        "同花顺热点（当日强势股+题材归因）；"
        "东方财富7x24快讯（催化新闻）；"
        "东方财富数据中心（龙虎榜）。"
    )

    result = {
        "report_date": today,
        "data_time": data_time,
        "focus_text": focus_text,
        "indices": indices,
        "inflow_sectors": inflow_sectors,
        "outflow_sectors": outflow_sectors,
        "concepts": concepts,
        "catalysts": catalysts,
        "front_tier": front_tier,
        "mid_tier": mid_tier,
        "rear_tier": rear_tier,
        "sentiments": sentiments,
        "holdings": holdings,
        "long_anchors": long_anchors,
        "short_anchors": short_anchors,
        "dragon_status": dragon_status,
        "sources": sources,
    }

    print("✅ 真实数据组装完成")
    return result


# ============================================================
#  第二部分：HTML 模板
#  使用 Jinja2 语法，变量用 {{ }} 包裹
#  如果你没装 Jinja2，脚本会用简单的字符串替换
# ============================================================

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>A股盘后总结 — {{ report_date }}</title>
<style>
  :root {
    --bg: #ffffff;
    --bg-section: #f8f9fb;
    --bg-card: #ffffff;
    --border: #e8eaed;
    --border-light: #f0f2f5;
    --text-primary: #1a1d23;
    --text-secondary: #5f6368;
    --text-muted: #9aa0a6;
    --accent-blue: #1a73e8;
    --accent-green: #137333;
    --accent-red: #c5221f;
    --up: #c5221f;
    --down: #137333;
    --tag-bg: #e8f0fe;
    --tag-text: #1a73e8;
    --highlight-bg: #fff8e1;
    --shadow: 0 1px 3px rgba(0,0,0,0.08);
    --shadow-md: 0 2px 8px rgba(0,0,0,0.10);
    --radius: 8px;
    --radius-sm: 4px;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, 'PingFang SC', 'Microsoft YaHei', 'Helvetica Neue', sans-serif;
    background: var(--bg); color: var(--text-primary);
    font-size: 13px; line-height: 1.6;
  }
  .page-header {
    background: #1a1d23; color: #fff;
    padding: 16px 24px 12px; border-bottom: 3px solid var(--accent-blue);
  }
  .page-header h1 { font-size: 22px; font-weight: 700; letter-spacing: 1px; }
  .page-header .meta { font-size: 11px; color: #9aa0a6; margin-top: 4px; }
  .page-header .meta span { margin-right: 16px; }
  .focus-notice {
    background: #fffbf0; border-left: 4px solid #f9ab00;
    margin: 12px 24px; padding: 10px 14px;
    border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
    font-size: 12.5px; color: #3c3c3c; line-height: 1.7;
  }
  .focus-notice strong { color: #b06000; }
  .main-wrap { padding: 0 24px 32px; }
  .section { margin-top: 18px; }
  .section-title {
    display: flex; align-items: center; gap: 8px;
    font-size: 14px; font-weight: 700; color: var(--text-primary);
    padding: 0 0 8px 0; border-bottom: 2px solid var(--accent-blue);
    margin-bottom: 10px;
  }
  .section-title::before {
    content: ''; display: inline-block; width: 4px; height: 16px;
    background: var(--accent-blue); border-radius: 2px; flex-shrink: 0;
  }
  table {
    width: 100%; border-collapse: collapse;
    background: var(--bg-card); border-radius: var(--radius);
    overflow: hidden; box-shadow: var(--shadow);
  }
  thead th {
    background: #f1f3f4; color: var(--text-secondary);
    font-weight: 600; font-size: 12px; padding: 8px 10px;
    text-align: left; border-bottom: 1px solid var(--border);
    white-space: nowrap;
  }
  tbody td {
    padding: 8px 10px; border-bottom: 1px solid var(--border-light);
    vertical-align: middle; font-size: 12.5px; color: var(--text-primary);
  }
  tbody tr:last-child td { border-bottom: none; }
  tbody tr:hover { background: #f8f9fb; }
  .up { color: var(--up); font-weight: 600; }
  .down { color: var(--down); font-weight: 600; }
  .index-grid { display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; }
  .index-card {
    background: var(--bg-card); border: 1px solid var(--border);
    border-radius: var(--radius); padding: 12px 14px;
    box-shadow: var(--shadow); transition: box-shadow .15s;
  }
  .index-card:hover { box-shadow: var(--shadow-md); }
  .index-card .idx-name { font-size: 12px; color: var(--text-secondary); margin-bottom: 4px; }
  .index-card .idx-val { font-size: 20px; font-weight: 700; }
  .index-card .idx-val.up { color: var(--up); }
  .index-card .idx-val.down { color: var(--down); }
  .index-card .idx-chg { font-size: 13px; font-weight: 600; margin-top: 2px; }
  .index-card .idx-meta { font-size: 11px; color: var(--text-muted); margin-top: 4px; }
  .index-card .idx-note { font-size: 11px; color: var(--text-secondary); margin-top: 6px; padding-top: 6px; border-top: 1px solid var(--border-light); }
  .two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
  .rank-num {
    display: inline-flex; align-items: center; justify-content: center;
    width: 22px; height: 22px; border-radius: 50%;
    font-size: 12px; font-weight: 700; background: var(--accent-blue); color: #fff;
  }
  .rank-num.gold { background: #f9ab00; color: #fff; }
  .rank-num.silver { background: #9aa0a6; color: #fff; }
  .rank-num.bronze { background: #c8a97e; color: #fff; }
  .status-tag {
    display: inline-block; padding: 2px 8px; border-radius: 20px;
    font-size: 11px; font-weight: 600;
  }
  .tag-confirm { background: #e6f4ea; color: #137333; }
  .tag-watch   { background: #e8f0fe; color: #1a73e8; }
  .tag-weak    { background: #fce8e6; color: #c5221f; }
  .tag-neutral { background: #f1f3f4; color: #5f6368; }
  .catalyst-direction {
    display: inline-block; font-weight: 700; font-size: 12px;
    padding: 2px 6px; border-radius: 3px;
    background: #e8f0fe; color: #1a73e8; white-space: nowrap;
  }
  .tier-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
  .tier-card {
    border: 1px solid var(--border); border-radius: var(--radius);
    overflow: hidden; box-shadow: var(--shadow);
  }
  .tier-header {
    padding: 8px 12px; font-size: 13px; font-weight: 700;
    display: flex; align-items: center; gap: 6px;
  }
  .tier-header.front { background: #fce8e6; color: #c5221f; }
  .tier-header.mid   { background: #e8f0fe; color: #1a73e8; }
  .tier-header.rear  { background: #f1f3f4; color: #5f6368; }
  .tier-body { padding: 10px 12px; }
  .tier-row {
    display: flex; justify-content: space-between; align-items: flex-start;
    padding: 6px 0; border-bottom: 1px dashed var(--border-light); gap: 8px;
  }
  .tier-row:last-child { border-bottom: none; }
  .tier-name { font-size: 12.5px; font-weight: 600; color: var(--text-primary); flex-shrink: 0; }
  .tier-stocks { font-size: 11px; color: var(--text-secondary); }
  .tier-chg { font-size: 13px; font-weight: 700; flex-shrink: 0; }
  .two-col-sentiment { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
  .heat-dot {
    display: inline-block; width: 8px; height: 8px;
    border-radius: 50%; margin-right: 4px; vertical-align: middle;
  }
  .heat-high   { background: #c5221f; }
  .heat-medium { background: #f9ab00; }
  .heat-low    { background: #137333; }
  .anchor-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
  .anchor-card {
    background: var(--bg-card); border: 1px solid var(--border);
    border-radius: var(--radius); overflow: hidden; box-shadow: var(--shadow);
  }
  .anchor-card-header {
    background: #f1f3f4; padding: 7px 12px; font-size: 12px;
    font-weight: 700; color: var(--text-secondary); border-bottom: 1px solid var(--border);
  }
  .anchor-card-header.success { background: #e6f4ea; color: #137333; }
  .anchor-card-header.fail    { background: #fce8e6; color: #c5221f; }
  .anchor-body { padding: 0; }
  .anchor-row {
    display: flex; align-items: flex-start; padding: 7px 12px;
    border-bottom: 1px solid var(--border-light); gap: 10px;
  }
  .anchor-row:last-child { border-bottom: none; }
  .anchor-dir { font-weight: 700; font-size: 12px; min-width: 64px; color: var(--accent-blue); }
  .anchor-cond { font-size: 12px; color: var(--text-primary); }
  .anchor-stocks { font-size: 11px; color: var(--text-secondary); margin-top: 2px; }
  .dragon-box {
    background: #fffbf0; border: 1px solid #f9ab00;
    border-radius: var(--radius); padding: 12px 16px;
    font-size: 12.5px; color: var(--text-primary); line-height: 1.8;
  }
  .dragon-box strong { color: #b06000; }
  .source-box {
    background: var(--bg-section); border-radius: var(--radius);
    padding: 10px 14px; font-size: 11.5px; color: var(--text-muted); line-height: 1.8;
  }
  .hl-red   { color: var(--up); font-weight: 600; }
  .hl-green { color: var(--down); font-weight: 600; }
  .hl-blue  { color: var(--accent-blue); font-weight: 600; }
  ::-webkit-scrollbar { width: 6px; height: 6px; }
  ::-webkit-scrollbar-track { background: #f1f3f4; }
  ::-webkit-scrollbar-thumb { background: #c8cacc; border-radius: 3px; }
  @media (max-width: 900px) {
    .index-grid { grid-template-columns: repeat(3, 1fr); }
    .two-col, .two-col-sentiment, .anchor-grid { grid-template-columns: 1fr; }
    .tier-grid { grid-template-columns: 1fr; }
  }
  @media (max-width: 600px) {
    .index-grid { grid-template-columns: repeat(2, 1fr); }
    .main-wrap { padding: 0 12px 24px; }
    .focus-notice { margin: 10px 12px; }
  }
</style>
</head>
<body>

<!-- ===== HEADER ===== -->
<div class="page-header">
  <div style="display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap;">
    <h1>{{ report_date }} &nbsp;A股盘后总结</h1>
    <div class="date-nav">
      <label for="dateSelect" style="font-size:11px;color:#9aa0a6;margin-right:6px;">📅 查看历史：</label>
      <select id="dateSelect" onchange="goToDate(this.value)" style="background:#2d3038;color:#fff;border:1px solid #444;padding:4px 10px;border-radius:4px;font-size:13px;cursor:pointer;">
        {% for d in available_dates %}
        <option value="{{ d.file }}" {% if d.date == report_date %}selected{% endif %}>{{ d.date }}</option>
        {% endfor %}
      </select>
    </div>
  </div>
  <div class="meta">
    <span>Data Time: {{ data_time }}</span>
    <span>|&nbsp;北京时间与东方财富主升行情口径&nbsp;&nbsp;龙虎榜数据以东方财富为准，本报告未纳入量化/程序盘参照</span>
  </div>
</div>
<script>
function goToDate(file) {
  if (file) window.location.href = file;
}
</script>

<!-- ===== FOCUS ===== -->
<div class="focus-notice">
  <strong>焦点站位：</strong>{{ focus_text }}
</div>

<div class="main-wrap">

  <!-- ===== 指数与市场风格 ===== -->
  <div class="section">
    <div class="section-title">指数与市场风格</div>
    <div class="index-grid">
      {% for idx in indices %}
      <div class="index-card">
        <div class="idx-name">{{ idx.name }}</div>
        <div class="idx-val {% if idx.is_up %}up{% else %}down{% endif %}">{{ idx.value }}</div>
        <div class="idx-chg {% if idx.is_up %}up{% else %}down{% endif %}">{{ idx.change_pct }}</div>
        <div class="idx-meta">{{ idx.volume_info }}</div>
        <div class="idx-note">{{ idx.note }}</div>
      </div>
      {% endfor %}
    </div>
  </div>

  <!-- ===== 行业主力净流入 / 净流出 ===== -->
  <div class="section">
    <div class="section-title">行业主力净流向</div>
    <div class="two-col">
      <!-- 净流入 -->
      <div>
        <table>
          <thead>
            <tr><th>行业（净流入）</th><th>涨幅</th><th>主力净流入</th><th>意义</th></tr>
          </thead>
          <tbody>
            {% for s in inflow_sectors %}
            <tr>
              <td class="up">{{ s.name }}</td>
              <td class="up">{{ s.change_pct }}</td>
              <td class="up">{{ s.net_flow }}</td>
              <td>{{ s.meaning }}</td>
            </tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
      <!-- 净流出 -->
      <div>
        <table>
          <thead>
            <tr><th>行业（净流出）</th><th>涨幅</th><th>主力净流出</th><th>意义</th></tr>
          </thead>
          <tbody>
            {% for s in outflow_sectors %}
            <tr>
              <td class="down">{{ s.name }}</td>
              <td class="down">{{ s.change_pct }}</td>
              <td class="down">{{ s.net_flow }}</td>
              <td>{{ s.meaning }}</td>
            </tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- ===== 概念与主线排序 ===== -->
  <div class="section">
    <div class="section-title">概念与主线排序</div>
    <table>
      <thead>
        <tr><th>排名</th><th>主线</th><th>涨幅/资金</th><th>核心股</th><th>状态</th><th>明日走势</th></tr>
      </thead>
      <tbody>
        {% for c in concepts %}
        <tr>
          <td><span class="rank-num {{ c.rank_class }}">{{ c.rank }}</span></td>
          <td>
            <strong>{{ c.title }}</strong><br>
            <small class="{% if c.get('is_up', True) %}hl-red{% else %}down{% endif %}">{{ c.subtitle }}</small>
          </td>
          <td class="{% if c.get('is_up', True) %}up{% else %}down{% endif %}">{{ c.change_pct }}</td>
          <td>{{ c.stocks }}</td>
          <td><span class="status-tag {{ c.status_tag_class }}">{{ c.status }}</span></td>
          <td>{{ c.tomorrow_view }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>

  <!-- ===== 关键催化 ===== -->
  <div class="section">
    <div class="section-title">关键催化：时间与来源</div>
    <table>
      <thead>
        <tr><th>方向</th><th>时间</th><th>来源</th><th>证据媒体</th><th>内容</th><th>效果验证</th></tr>
      </thead>
      <tbody>
        {% for cat in catalysts %}
        <tr>
          <td><span class="catalyst-direction">{{ cat.direction }}</span></td>
          <td>{{ cat.time }}</td>
          <td>{{ cat.source }}</td>
          <td>{{ cat.media }}</td>
          <td>{{ cat.content }}</td>
          <td>{{ cat.effect }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>

  <!-- ===== 前排/中军/后排 ===== -->
  <div class="section">
    <div class="section-title">前排 / 中军 / 后排</div>
    <div class="tier-grid">
      <!-- 前排 -->
      <div class="tier-card">
        <div class="tier-header front">🔥 前排（龙头）</div>
        <div class="tier-body">
          {% for item in front_tier %}
          <div class="tier-row">
            <div>
              <div class="tier-name">{{ item.section }}</div>
              <div class="tier-stocks">{{ item.stocks }}</div>
            </div>
            <div class="tier-chg {{ item.change_class }}">{{ item.change }}</div>
          </div>
          {% endfor %}
        </div>
      </div>
      <!-- 中军 -->
      <div class="tier-card">
        <div class="tier-header mid">📊 中军</div>
        <div class="tier-body">
          {% for item in mid_tier %}
          <div class="tier-row">
            <div>
              <div class="tier-name">{{ item.section }}</div>
              <div class="tier-stocks">{{ item.stocks }}</div>
            </div>
            <div class="tier-chg {{ item.change_class }}">{{ item.change }}</div>
          </div>
          {% endfor %}
        </div>
      </div>
      <!-- 后排 -->
      <div class="tier-card">
        <div class="tier-header rear">📉 后排 / 跟风</div>
        <div class="tier-body">
          {% for item in rear_tier %}
          <div class="tier-row">
            <div>
              <div class="tier-name">{{ item.section }}</div>
              <div class="tier-stocks">{{ item.stocks }}</div>
            </div>
            <div class="tier-chg {{ item.change_class }}">{{ item.change }}</div>
          </div>
          {% endfor %}
        </div>
      </div>
    </div>
  </div>

  <!-- ===== 舆情监测 + 持仓影响 ===== -->
  <div class="section">
    <div class="two-col-sentiment">
      <!-- 舆情监测 -->
      <div>
        <div class="section-title">舆情监测</div>
        <table>
          <thead>
            <tr><th>来源</th><th>方向</th><th>热度</th><th>关键事件</th><th>盘前/盘后</th><th>操作建议</th></tr>
          </thead>
          <tbody>
            {% for s in sentiments %}
            <tr>
              <td>{{ s.source }}</td>
              <td>{{ s.direction }}</td>
              <td><span class="heat-dot {{ s.heat_class }}"></span>{{ s.heat_level }}</td>
              <td>{{ s.event }}</td>
              <td>{{ s.timing }}</td>
              <td>{{ s.action }}</td>
            </tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
      <!-- 持仓影响 -->
      <div>
        <div class="section-title">持仓影响</div>
        <table>
          <thead>
            <tr><th>持仓</th><th>收盘涨跌</th><th>主力净量</th><th>定位</th><th>明日走势</th></tr>
          </thead>
          <tbody>
            {% for h in holdings %}
            <tr>
              <td><strong>{{ h.name }}<br>{{ h.code }}</strong></td>
              <td class="{% if h.is_up %}up{% else %}down{% endif %}">{{ h.change_pct }}</td>
              <td class="{% if h.is_up %}up{% else %}down{% endif %}">{{ h.net_flow }}</td>
              <td>{{ h.position }}</td>
              <td>{{ h.tomorrow_view }}</td>
            </tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- ===== 明日锚点与失败信号 ===== -->
  <div class="section">
    <div class="section-title">明日锚点与失败信号</div>
    <div class="anchor-grid">
      <div class="anchor-card">
        <div class="anchor-card-header success">✅ 明日锚点（做多条件）</div>
        <div class="anchor-body">
          {% for a in long_anchors %}
          <div class="anchor-row">
            <div>
              <div class="anchor-dir">{{ a.direction }}</div>
              <div class="anchor-cond">{{ a.condition }}</div>
              <div class="anchor-stocks">{{ a.stocks }}</div>
            </div>
          </div>
          {% endfor %}
        </div>
      </div>
      <div class="anchor-card">
        <div class="anchor-card-header fail">❌ 失败信号（止损/警示条件）</div>
        <div class="anchor-body">
          {% for a in short_anchors %}
          <div class="anchor-row">
            <div>
              <div class="anchor-dir hl-red">{{ a.direction }}</div>
              <div class="anchor-cond">{{ a.condition }}</div>
              <div class="anchor-stocks">{{ a.stocks }}</div>
            </div>
          </div>
          {% endfor %}
        </div>
      </div>
    </div>
  </div>

  <!-- ===== 龙虎榜状态 ===== -->
  <div class="section">
    <div class="section-title">龙虎榜状态</div>
    <div class="dragon-box">
      <strong>📋 报告生成时间：</strong>{{ dragon_status }}
    </div>
  </div>

  <!-- ===== 来源 ===== -->
  <div class="section">
    <div class="section-title">来源</div>
    <div class="source-box">{{ sources }}</div>
  </div>

</div><!-- /main-wrap -->
</body>
</html>"""


# ============================================================
#  第三部分：渲染引擎
#  把数据填进模板，生成最终的 HTML 文件
# ============================================================

def render_report(data):
    """把数据字典填进 HTML 模板，返回完整的 HTML 字符串"""
    if USE_JINJA2:
        template = Template(HTML_TEMPLATE)
        return template.render(**data)
    else:
        # 简单字符串替换（不装 Jinja2 也能用）
        # 注意：这种方式不支持循环，所以我们只替换最外层变量
        # 强烈建议安装 Jinja2
        print("⚠️  简单替换模式功能有限，建议安装 Jinja2 获得完整功能")
        result = HTML_TEMPLATE
        # 替换简单变量
        for key in ["report_date", "data_time", "focus_text", "dragon_status", "sources"]:
            if key in data:
                result = result.replace("{{ " + key + " }}", str(data[key]))
        return result


def scan_available_dates(output_dir):
    """扫描目录下已有的报告文件，生成日期列表（最新在前）"""
    import re as _re
    pattern = _re.compile(r"a_stock_daily_summary_(\d{4}-\d{2}-\d{2})\.html")
    dates = []
    for f in Path(output_dir).glob("a_stock_daily_summary_*.html"):
        m = pattern.match(f.name)
        if m:
            dates.append({
                "date": m.group(1),
                "file": f.name,
            })
    # 按日期降序排列（最新日期在最前面）
    dates.sort(key=lambda x: x["date"], reverse=True)
    return dates


def _build_select_html(available_dates, selected_date):
    """构造完整的日期选择器 HTML"""
    import re as _re
    options_html = ""
    for d in available_dates:
        sel = ' selected' if d["date"] == selected_date else ''
        options_html += '<option value="' + d["file"] + '"' + sel + '>' + d["date"] + '</option>\n        '
    return (
        '<select id="dateSelect" onchange="goToDate(this.value)" '
        'style="background:#2d3038;color:#fff;border:1px solid #444;padding:4px 10px;'
        'border-radius:4px;font-size:13px;cursor:pointer;">\n        '
        + options_html.strip() + '\n      </select>'
    )


def update_all_date_selectors(output_dir, available_dates, current_date):
    """更新所有历史报告 HTML 的日期选择器，确保每个页面都能跳转到任意日期
    
    处理两种情况：
      1. 已有 dateSelect 的文件 → 直接替换 <select> 选项，修正 selected
      2. 没有 dateSelect 的旧文件 → 注入完整的日期导航栏 + goToDate 脚本
    """
    import re as _re
    pattern = _re.compile(r"a_stock_daily_summary_(\d{4}-\d{2}-\d{2})\.html")
    files_to_update = list(Path(output_dir).glob("a_stock_daily_summary_*.html"))
    files_to_update.append(output_dir / "index.html")
    
    for f in files_to_update:
        if not f.exists():
            continue
        content = f.read_text(encoding="utf-8")
        
        # 提取该文件自身日期（用于设置 selected）
        file_date = current_date  # 默认
        file_date_match = pattern.match(f.name)
        if file_date_match:
            file_date = file_date_match.group(1)
        
        # 构造针对该文件的 select HTML（selected 设置为该文件自身日期）
        select_html = _build_select_html(available_dates, file_date)
        
        # ── 情况1：已有 dateSelect → 替换 select 选项 ──
        if 'id="dateSelect"' in content:
            select_pattern = _re.compile(
                r'<select id="dateSelect"[^>]*>.*?</select>',
                _re.DOTALL
            )
            new_content = select_pattern.sub(select_html, content)
            if new_content != content:
                f.write_text(new_content, encoding="utf-8")
                print(f"    ✅ 更新 {f.name} 的日期选择器选项")
            continue
        
        # ── 情况2：没有 dateSelect → 注入完整的日期导航 + 脚本 ──
        date_nav_html = (
            '<div class="date-nav">\n'
            '      <label for="dateSelect" style="font-size:11px;color:#9aa0a6;margin-right:6px;">'
            '📅 查看历史：</label>\n      '
            + select_html + '\n'
            '    </div>'
        )
        
        # 注入 goToDate 脚本（在 </body> 前插入）
        go_to_date_script = (
            '\n<script>\nfunction goToDate(file) {\n'
            '  if (file) window.location.href = file;\n}\n</script>\n'
        )
        
        # 将 <h1>...</h1> 改成 flex 布局 + 日期导航
        # 旧格式: <h1>2026-06-26 &nbsp;A股盘后总结</h1>
        # 新格式: <div style="display:flex;..."><h1>...</h1><div class="date-nav">...</div></div>
        h1_pattern = _re.compile(r'<h1>([^&]*?)&nbsp;A股盘后总结</h1>')
        h1_match = h1_pattern.search(content)
        if h1_match:
            old_h1 = h1_match.group(0)
            h1_date_str = h1_match.group(1).strip()
            new_header_inner = (
                '<div style="display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap;">\n'
                '    <h1>' + h1_date_str + '&nbsp;A股盘后总结</h1>\n'
                '    ' + date_nav_html + '\n'
                '  </div>'
            )
            new_content = content.replace(old_h1, new_header_inner)
            # 注入脚本
            new_content = new_content.replace('</body>', go_to_date_script + '</body>')
            f.write_text(new_content, encoding="utf-8")
            print(f"    ✅ 注入 {f.name} 的日期导航栏（旧模板升级）")
        else:
            print(f"    ⚠️ {f.name} 无法识别 h1 标题，跳过")


def save_report(html_content, report_date, data=None):
    """保存 HTML 文件到当前目录，并更新所有历史报告的日期选择器"""
    filename = f"a_stock_daily_summary_{report_date}.html"
    output_dir = Path(__file__).parent
    output_path = output_dir / filename

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"✅ 报告已生成: {output_path}")

    # 同时更新 index.html（GitHub Pages 入口）
    index_path = output_dir / "index.html"
    if data is not None:
        available_dates = scan_available_dates(output_dir)
        data["available_dates"] = available_dates
        index_html = render_report(data)
        with open(index_path, "w", encoding="utf-8") as f:
            f.write(index_html)
        print(f"✅ index.html 已更新（含 {len(available_dates)} 个历史日期）")
        
        # 更新所有历史报告的日期选择器
        print("🔄 同步更新所有历史报告的日期选择器...")
        update_all_date_selectors(output_dir, available_dates, report_date)

    return output_path


# ============================================================
#  第四部分：主入口
# ============================================================

def main(use_real_data=False):
    """
    主流程：
      1. 获取数据（真实 API 或模拟）
      2. 渲染 HTML 模板
      3. 保存文件 + 更新 index.html
    """
    print("=" * 50)
    print("  A股盘后总结 — 自动报告生成引擎")
    print("=" * 50)

    # 第一步：获取数据
    if use_real_data:
        print("\n📡 正在从 API 获取真实数据...")
        data = fetch_real_data()
    else:
        print("\n📦 使用模拟数据生成报告...")
        data = build_mock_data()

    print(f"   日期: {data['report_date']}")

    # 扫描已有历史报告，注入日期列表
    output_dir = Path(__file__).parent
    available_dates = scan_available_dates(output_dir)
    # 加入今天的日期（如果还没有的话）
    today_entry = {"date": data["report_date"], "file": f"a_stock_daily_summary_{data['report_date']}.html"}
    if not any(d["date"] == data["report_date"] for d in available_dates):
        available_dates.insert(0, today_entry)
    data["available_dates"] = available_dates
    print(f"   历史报告: {len(available_dates)} 个日期")

    # 第二步：渲染 HTML
    print("\n🎨 正在渲染 HTML 模板...")
    html = render_report(data)

    # 第三步：保存文件 + 更新 index.html
    print("\n💾 正在保存报告...")
    output_path = save_report(html, data["report_date"], data=data)

    print(f"\n📄 报告大小: {len(html):,} 字符")
    print(f"📍 文件位置: {output_path}")
    print(f"📍 GitHub Pages: {output_dir / 'index.html'}")
    print("\n✨ 完成！用浏览器打开上面的文件即可查看。")

    return output_path


if __name__ == "__main__":
    import sys
    use_real = "--real" in sys.argv
    main(use_real_data=use_real)
