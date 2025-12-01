# XHS Daily Crypto Reporter

Python tools to:
- 拉取 Binance 24h 行情（BTC/ETH/BNB 默认）并汇总涨跌、区间、成交量。
- 抓取公开 RSS 新闻（Coindesk 为主），关键词筛选后附上标题列表。
- 读取你的日度快照（默认自动按日期拼 `https://logs.gleaftex.com/.../report_<YYYYMMDD>.txt`）。
- 调用 OpenRouter 生成 ~300 字中文小红书风格文案。
- 将文案上传到 R2（生成 7 天预签名链接），Bark 推送文案 + 3 张图的外链。

## 准备
1) Python 3，可直接安装依赖：
```bash
pip install -r requirements.txt
```
2) 在 `.env` 写入你的 OpenRouter key（放在仓库根，已在 .gitignore 内）：
```
OPENROUTER_API_KEY=...
```
运行前加载环境变量：
```bash
set -a; source .env; set +a
```
3) 将密钥放入 `secrets.env`（不进 Git），内容示例：
```
STATE_BUCKET=lucas
STATE_ENDPOINT_URL=https://26ba3fd3c81b98fb6f3526af1b9a0b30.r2.cloudflarestorage.com
STATE_ACCESS_KEY=...
STATE_SECRET_KEY=...
STATE_REGION=auto
BARK_SERVER=https://api.day.app
BARK_KEY=...
```
运行时会根据这些变量生成临时 `state.runtime.yaml`。

## 用法
- 生成文案并上传 R2 + Bark 推送（默认当天 UTC）：
```bash
python3 xhs_summary.py
```
- 指定日期（格式 YYYYMMDD，自动拼快照 URL 与图片链接）：
```bash
python3 xhs_summary.py --date 20251201
```
- 自定义快照来源：
```bash
python3 xhs_summary.py --snapshot https://logs.gleaftex.com/.../report_20251201.txt
```
- 仅查看喂给模型的 prompt（不调 OpenRouter，不上传/推送）：
```bash
python3 xhs_summary.py --dry-run
```
- 跳过 R2 上传或推送：
```bash
python3 xhs_summary.py --no-upload   # 不上传 R2
python3 xhs_summary.py --no-notify   # 不发 Bark
```

输出与存储：
- 文案上传键：`xhs/xxxx_<YYYY-MM-DD>.txt`（R2 预签名有效期 7 天）。
- Bark 推送：标题 `XHS摘要 <date>`，正文含文案 + 三张图片外链  
  `https://logs.gleaftex.com/runs/fa888/martingale/reports/<YYYY-MM-DD>-1/2/3.png`，如上传成功还会附 R2 预签名链接。

## 组件
- `analyze.py`：Binance K线汇总 + RSS 新闻抓取。
- `xhs_summary.py`：构造 prompt，调 OpenRouter 生成文案，上传 R2，Bark 推送。
- `state.yaml`：R2 与 Bark 配置。
- `requirements.txt`：依赖列表。

## 备注
- Binance Feed 如遇 Cloudflare/WAF 会被跳过，不影响生成。
- 图片已在公网可访问的 logs.gleaftex.com，无需额外上传。
