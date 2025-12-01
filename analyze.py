#!/usr/bin/env python3
"""
24h crypto watcher for BTC/ETH/BNB.

Fetches the last 24h of Binance spot klines, summarizes change/high/low/volume,
and grabs recent headlines from a couple of public RSS feeds (Coindesk, Binance Feed).
No API keys required.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
import textwrap
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Iterable, List, Sequence

import requests

BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"

# Public RSS feeds; filtered by keywords below.
RSS_FEEDS = {
    "Coindesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "BinanceFeed": "https://www.binance.com/en/feed/rss",
}

# Keywords used to match headlines to tracked assets.
NEWS_KEYWORDS = ["btc", "bitcoin", "eth", "ethereum", "bnb", "binance"]

DEFAULT_SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT"]


@dataclass
class SymbolSummary:
    symbol: str
    start_price: float
    end_price: float
    high: float
    low: float
    base_volume: float
    quote_volume: float

    @property
    def change(self) -> float:
        return self.end_price - self.start_price

    @property
    def change_pct(self) -> float:
        return (self.change / self.start_price) * 100 if self.start_price else 0.0


@dataclass
class NewsItem:
    source: str
    title: str
    link: str
    published: dt.datetime


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Summarize 24h Binance klines and recent news for tracked symbols."
    )
    parser.add_argument(
        "-s",
        "--symbols",
        nargs="+",
        default=DEFAULT_SYMBOLS,
        help="Trading pairs to track (default: %(default)s)",
    )
    parser.add_argument(
        "--hours",
        type=int,
        default=24,
        help="Lookback window in hours (default: %(default)s)",
    )
    parser.add_argument(
        "--interval",
        default="1h",
        help="Binance kline interval (default: %(default)s)",
    )
    return parser.parse_args(argv)


def fetch_klines(symbol: str, start: dt.datetime, end: dt.datetime, interval: str) -> List[list]:
    params = {
        "symbol": symbol.upper(),
        "interval": interval,
        "startTime": int(start.timestamp() * 1000),
        "endTime": int(end.timestamp() * 1000),
    }
    resp = requests.get(BINANCE_KLINES_URL, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if not data:
        raise ValueError(f"No kline data returned for {symbol}")
    return data


def summarize_klines(symbol: str, klines: Iterable[list]) -> SymbolSummary:
    klines = list(klines)
    start_price = float(klines[0][1])
    end_price = float(klines[-1][4])
    high = max(float(k[2]) for k in klines)
    low = min(float(k[3]) for k in klines)
    base_volume = sum(float(k[5]) for k in klines)
    quote_volume = sum(float(k[7]) for k in klines)
    return SymbolSummary(
        symbol=symbol,
        start_price=start_price,
        end_price=end_price,
        high=high,
        low=low,
        base_volume=base_volume,
        quote_volume=quote_volume,
    )


def fetch_news(feeds: dict[str, str], cutoff: dt.datetime) -> List[NewsItem]:
    items: List[NewsItem] = []
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/rss+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    for source, url in feeds.items():
        try:
            resp = requests.get(url, timeout=10, headers=headers)
            resp.raise_for_status()
            # Binance feed sometimes returns a CloudFront/WAF 202 challenge with empty body.
            if resp.headers.get("x-amzn-waf-action") or not resp.text.strip():
                print(f"[info] Skipping {source} feed (blocked/empty response).", file=sys.stderr)
                continue
            doc = ET.fromstring(resp.text)
        except Exception as exc:  # noqa: BLE001 - this is a simple reporting script
            print(f"[warn] Failed to read {source} feed: {exc}", file=sys.stderr)
            continue

        channel = doc.find("channel")
        if channel is None:
            continue

        for item in channel.findall("item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            pub_text = (item.findtext("pubDate") or "").strip()
            try:
                published = parsedate_to_datetime(pub_text)
                if published.tzinfo is None:
                    published = published.replace(tzinfo=dt.timezone.utc)
                published = published.astimezone(dt.timezone.utc)
            except Exception:
                continue

            if published < cutoff:
                continue

            content = f"{title} {item.findtext('description') or ''}".lower()
            if not any(keyword in content for keyword in NEWS_KEYWORDS):
                continue

            items.append(
                NewsItem(
                    source=source,
                    title=title,
                    link=link,
                    published=published,
                )
            )

    items.sort(key=lambda i: i.published, reverse=True)
    return items


def format_symbol_summary(summary: SymbolSummary) -> str:
    change_sign = "+" if summary.change >= 0 else "-"
    return (
        f"{summary.symbol}: "
        f"{change_sign}{abs(summary.change):.2f} ({change_sign}{abs(summary.change_pct):.2f}%) "
        f"start={summary.start_price:.2f} end={summary.end_price:.2f} "
        f"high={summary.high:.2f} low={summary.low:.2f} "
        f"volume={summary.base_volume:.4f} ({summary.quote_volume:.2f} quote)"
    )


def format_news(items: Sequence[NewsItem]) -> str:
    if not items:
        return "No matching headlines in the last 24h."

    lines = []
    for idx, item in enumerate(items, start=1):
        published = item.published.strftime("%Y-%m-%d %H:%MZ")
        lines.append(f"{idx}. [{item.source}] {published} - {item.title} ({item.link})")
    return "\n".join(lines)


def main(argv: Sequence[str]) -> int:
    args = parse_args(argv)
    now = dt.datetime.now(dt.timezone.utc)
    start = now - dt.timedelta(hours=args.hours)

    print(f"Window: {start:%Y-%m-%d %H:%MZ} -> {now:%Y-%m-%d %H:%MZ} (interval {args.interval})")
    print(f"Symbols: {', '.join(args.symbols)}\n")

    summaries: List[SymbolSummary] = []
    for symbol in args.symbols:
        try:
            klines = fetch_klines(symbol, start, now, args.interval)
            summaries.append(summarize_klines(symbol, klines))
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] {symbol}: failed to fetch/summarize - {exc}", file=sys.stderr)

    if summaries:
        print("Market move (last 24h):")
        for summary in summaries:
            print(f"- {format_symbol_summary(summary)}")
    else:
        print("No kline data available.")

    print("\nNews (last 24h, keyword-filtered):")
    cutoff = start
    news_items = fetch_news(RSS_FEEDS, cutoff)
    print(textwrap.indent(format_news(news_items), prefix="- "))

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
