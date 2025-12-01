#!/usr/bin/env python3
"""
Generate a ~300-word Xiaohongshu-style summary that blends:
- your daily snapshot file (report_YYYYMMDD.txt)
- the latest 24h market/news summary from Binance + public RSS
- OpenRouter LLM completion (no curl required)
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from typing import List, Optional, Sequence

import requests
import yaml
from boto3.session import Session
from botocore.config import Config

import analyze

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

DEFAULT_MODEL = "x-ai/grok-4.1-fast:free"


def read_snapshot(path: str) -> str:
    if path.startswith("http://") or path.startswith("https://"):
        try:
            resp = requests.get(path, timeout=10)
            resp.raise_for_status()
            return resp.text.strip()
        except Exception as exc:  # noqa: BLE001
            raise SystemExit(f"Failed to fetch snapshot from URL {path}: {exc}") from exc

    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except OSError as exc:  # noqa: BLE001
        raise SystemExit(f"Failed to read snapshot {path}: {exc}")


def build_market_block(
    symbols: Sequence[str], hours: int, interval: str
) -> str:
    now = dt.datetime.now(dt.timezone.utc)
    start = now - dt.timedelta(hours=hours)
    summaries: List[analyze.SymbolSummary] = []

    for symbol in symbols:
        try:
            klines = analyze.fetch_klines(symbol, start, now, interval)
            summaries.append(analyze.summarize_klines(symbol, klines))
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] {symbol}: failed to fetch/summarize - {exc}", file=sys.stderr)

    market_lines = []
    if summaries:
        market_lines.append("Market move (last 24h):")
        for summary in summaries:
            market_lines.append(f"- {analyze.format_symbol_summary(summary)}")
    else:
        market_lines.append("Market move: unavailable")

    news_items = analyze.fetch_news(analyze.RSS_FEEDS, start)
    market_lines.append("\nNews (last 24h, keyword-filtered):")
    market_lines.append(analyze.format_news(news_items))

    header = f"Window: {start:%Y-%m-%d %H:%MZ} -> {now:%Y-%m-%d %H:%MZ} (interval {interval})"
    return f"{header}\n" + "\n".join(market_lines)


def build_prompt(snapshot: str, market_block: str) -> str:
    return (
        "以下是我的日常收益/持仓快照和最近24小时的市场&新闻摘要，"
        "请写一段约300字的中文小红书风格总结，"
        "要求口语化、有吸引点，兼顾行情情绪、风险提示和我的仓位表现，"
        "不要逐条罗列数据、避免刻板数字堆砌，结尾给一个轻提示。\n\n"
        "【持仓快照】\n"
        f"{snapshot}\n\n"
        "不要显示字数统计。\n\n"
        "Simple Earn翻译成活期理财"
        "【市场与新闻】\n"
        f"{market_block}\n"
    )


def call_openrouter(api_key: str, model: str, prompt: str) -> str:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "你是一名面向小红书读者的加密市场解说员，语气亲和、简洁、有画面感。",
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        "temperature": 0.7,
        "max_tokens": 600,
    }
    resp = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=30)
    try:
        resp.raise_for_status()
    except requests.HTTPError as exc:
        raise SystemExit(f"OpenRouter request failed: {exc} - {resp.text}") from exc

    data = resp.json()
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:  # noqa: BLE001
        raise SystemExit(f"Unexpected OpenRouter response: {json.dumps(data, ensure_ascii=False)}") from exc


def load_state(path: str) -> Optional[dict]:
    if not path:
        return None
    if not os.path.exists(path):
        print(f"[info] State file not found at {path}, skip upload/notify.", file=sys.stderr)
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] Failed to load state file {path}: {exc}", file=sys.stderr)
        return None


def format_date_dash(date_str: str) -> str:
    if "-" in date_str:
        return date_str
    try:
        return dt.datetime.strptime(date_str, "%Y%m%d").strftime("%Y-%m-%d")
    except Exception:
        return date_str


def build_image_links(date_str: str) -> list[str]:
    date_dash = format_date_dash(date_str)
    base = "https://logs.gleaftex.com/runs/fa888/martingale/reports"
    return [
        f"{base}/{date_dash}-1.png",
        f"{base}/{date_dash}-2.png",
        f"{base}/{date_dash}-3.png",
    ]


def upload_to_r2(conf: dict, key: str, body: str) -> Optional[str]:
    bucket = conf.get("bucket")
    endpoint = conf.get("endpoint_url")
    access_key = conf.get("access_key")
    secret_key = conf.get("secret_key")
    region = conf.get("region", "auto")
    if not all([bucket, endpoint, access_key, secret_key]):
        print("[warn] R2 config incomplete; skip upload.", file=sys.stderr)
        return None

    session = Session(
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region,
    )
    s3 = session.client(
        "s3",
        endpoint_url=endpoint,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )
    try:
        s3.put_object(Bucket=bucket, Key=key, Body=body.encode("utf-8"), ContentType="text/plain; charset=utf-8")
        url = s3.generate_presigned_url(
            "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=7 * 24 * 3600
        )
        print(f"[info] Uploaded to r2://{bucket}/{key}", file=sys.stderr)
        return url
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] Failed to upload to R2: {exc}", file=sys.stderr)
        return None


def send_bark(conf: dict, title: str, body: str, url: Optional[str] = None, extra_urls: Optional[list[str]] = None) -> None:
    server = conf.get("server", "https://api.day.app").rstrip("/")
    key = conf.get("key")
    if not key:
        print("[warn] Bark config missing key; skip notify.", file=sys.stderr)
        return
    body_with_links = body
    # if extra_urls:
    #     body_with_links += "\n" + "\n".join(extra_urls)
    payload = {"title": title, "body": body_with_links}
    # if url:
    #     payload["url"] = url
    try:
        resp = requests.post(f"{server}/push", json={"device_key": key, **payload}, timeout=10)
        resp.raise_for_status()
        print("[info] Bark notification sent.", file=sys.stderr)
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] Failed to send Bark notification: {exc}", file=sys.stderr)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate ~300-word Xiaohongshu-style summary using OpenRouter."
    )
    parser.add_argument(
        "--snapshot",
        default=None,
        help="Path or URL to daily snapshot file. If omitted, will auto-use --date to build the URL.",
    )
    parser.add_argument(
        "--date",
        default=dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d"),
        help="Date (UTC) for the default snapshot URL, format YYYYMMDD (default: today UTC)",
    )
    parser.add_argument(
        "--state-file",
        default="state.yaml",
        help="Path to YAML with R2/Bark config (default: %(default)s)",
    )
    parser.add_argument(
        "-s",
        "--symbols",
        nargs="+",
        default=analyze.DEFAULT_SYMBOLS,
        help="Symbols to summarize (default: %(default)s)",
    )
    parser.add_argument(
        "--hours",
        type=int,
        default=24,
        help="Lookback hours for market summary (default: %(default)s)",
    )
    parser.add_argument(
        "--interval",
        default="1h",
        help="Kline interval (default: %(default)s)",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help="OpenRouter model id (default: %(default)s)",
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("OPENROUTER_API_KEY"),
        help="OpenRouter API key (default: env OPENROUTER_API_KEY)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print prompt and exit without calling the API",
    )
    parser.add_argument(
        "--no-upload",
        action="store_true",
        help="Skip uploading summary to R2 even if state config exists.",
    )
    parser.add_argument(
        "--no-notify",
        action="store_true",
        help="Skip Bark push even if notify config exists.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str]) -> int:
    args = parse_args(argv)
    if not args.api_key and not args.dry_run:
        raise SystemExit("Missing OpenRouter API key. Set OPENROUTER_API_KEY or --api-key.")

    snapshot_source = (
        args.snapshot
        if args.snapshot
        else f"https://logs.gleaftex.com/runs/fa888/martingale/reports/report_{args.date}.txt"
    )
    snapshot_text = read_snapshot(snapshot_source)
    market_block = build_market_block(args.symbols, args.hours, args.interval)
    prompt = build_prompt(snapshot_text, market_block)

    state = None
    if not (args.no_upload and args.no_notify):
        state = load_state(args.state_file)
    bark_conf = state.get("notify", {}).get("bark") if state else None

    if args.dry_run:
        print(prompt)
        return 0

    try:
        content = call_openrouter(args.api_key, args.model, prompt)
    except Exception as exc:  # noqa: BLE001
        msg = f"OpenRouter 调用失败: {exc}"
        print(f"[warn] {msg}", file=sys.stderr)
        if bark_conf and not args.no_notify:
            send_bark(bark_conf, title=f"XHS摘要失败 {args.date}", body=msg)
        return 1

    print(content.strip())

    upload_url = None
    state_conf = state.get("state") if state else None
    if state_conf and not args.no_upload:
        key = f"xhs/xhs_summary_{format_date_dash(args.date)}.txt"
        upload_url = upload_to_r2(state_conf, key, content)

    if bark_conf and not args.no_notify:
        preview = content.strip()
        # if len(preview) > 200:
        #     preview = preview[:200] + "..."
        extra_urls = build_image_links(args.date)
        send_bark(
            bark_conf,
            title=f"XHS摘要 {args.date}",
            body=preview,
            url=upload_url,
            extra_urls=extra_urls,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
