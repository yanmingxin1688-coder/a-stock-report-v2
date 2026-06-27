# A股盘后报告项目记忆

## 项目定位
- A股盘后自动报告生成引擎 + GitHub Pages 部署
- 仓库: https://github.com/yanmingxin1688-coder/a-stock-report-v2.git
- Pages地址: https://yanmingxin1688-coder.github.io/a-stock-report-v2/

## 核心文件
- `generate_report.py` — 报告引擎（模拟/真实双模式）
- `deploy_to_github.py` — 一键部署脚本
- `index.html` — GitHub Pages 入口（最新报告，带日期选择器）
- `a_stock_daily_summary_YYYY-MM-DD.html` — 每日历史报告

## 新功能
- **日期选择器**：顶部下拉菜单，可切换查看历史报告
- `scan_available_dates()` 自动扫描已有报告生成日期列表
- `save_report()` 同时更新 index.html（含完整日期选择器）
- 每个历史报告也是独立 HTML 文件，互相可跳转
- **日期选择器同步更新**：每次生成新报告时，`update_all_date_selectors()` 会：
  - 对已有 dateSelect 的文件 → 替换 `<select>` 选项，修正 selected 指向该文件自身日期
  - 对没有 dateSelect 的旧模板文件 → 注入完整日期导航栏 + goToDate 脚本

## 数据源架构（fetch_real_data）
| 优先级 | 数据源 | 用途 | 状态 |
|--------|--------|------|------|
| 1 | 腾讯财经 qt.gtimg.cn | 五大指数实时行情 | ✅ 不封IP |
| 2 | **东财 push2delay 镜像 → push2 → akshare** | 行业板块排名 | ✅ 沙盒/生产双通 |
| 3 | 同花顺热点 zx.10jqka.com.cn | 当日强势股+题材归因 | ✅ 零鉴权 |
| 4 | 东财 np-weblist | 7x24财经快讯 | ✅ |
| 5 | 东财 datacenter-web | 龙虎榜 | ✅ |

## 指数代码映射（注意：指数不遵循个股前缀规则）
- sh000001=上证指数, sz399001=深证成指, sz399006=创业板指
- sh000300=沪深300, sh000688=科创50

## 定时任务
- automation-1782410690342: 每周一到五 16:05 运行 --real 模式

## 已知坑
- **push2.eastmoney.com 镜像降级链**：push2delay → push2 → akshare → mock
  - 沙盒 IP 被 push2 RST，但 `push2delay.eastmoney.com` 镜像通
  - 生产环境 push2 直连，push2delay 不需要
- 科创50代码000688必须用sh前缀（不是bj/sz）
- f-string嵌套引号会导致SyntaxError，用字符串拼接替代
- 沙盒里**Python requests 不通**但**curl 通**的奇怪现象：Python TLS 握手被服务端拒绝（不是代理问题），用 `subprocess.check_output(["curl", ...])` 绕过
- 腾讯指数API vals[48]/[49]（涨跌家数）可能返回浮点字符串如"0.96"，需要 `int(float(...))` 处理
