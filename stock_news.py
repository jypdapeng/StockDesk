import re
import urllib.request
from html import unescape


SINA_NEWS_URL = "https://vip.stock.finance.sina.com.cn/corp/go.php/vCB_AllNewsStock/symbol/{market}{symbol}.phtml"

POSITIVE_KEYWORDS = [
    "签订",
    "中标",
    "增长",
    "增持",
    "回购",
    "盈利",
    "预增",
    "突破",
    "扩产",
    "复产",
    "利好",
    "合作",
]

NEGATIVE_KEYWORDS = [
    "风险",
    "下跌",
    "减持",
    "亏损",
    "预亏",
    "警惕",
    "终止",
    "诉讼",
    "处罚",
    "调查",
    "违约",
    "压力",
]


def fetch_stock_news(symbol: str, market: str, limit: int = 12) -> list[dict]:
    url = SINA_NEWS_URL.format(market=market, symbol=symbol)
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=20) as response:
        html = response.read().decode("gb2312", errors="replace")

    match = re.search(r'<div class="datelist"><ul>(.*?)</ul>', html, re.S)
    if not match:
        return []

    block = match.group(1)
    pattern = re.compile(
        r'(\d{4}-\d{2}-\d{2})&nbsp;(\d{2}:\d{2}).*?<a[^>]+href=[\'"]([^\'"]+)[\'"][^>]*>(.*?)</a>',
        re.S,
    )
    items = []
    for found in pattern.finditer(block):
        title = unescape(re.sub(r"<[^>]+>", "", found.group(4))).strip()
        if not title:
            continue
        items.append(
            {
                "time": f"{found.group(1)} {found.group(2)}",
                "title": title,
                "url": found.group(3),
            }
        )
        if len(items) >= limit:
            break
    return items


def analyze_news_bias(items: list[dict]) -> dict:
    positive_hits: list[str] = []
    negative_hits: list[str] = []
    neutral_titles: list[str] = []

    for item in items:
        title = item["title"]
        pos_score = sum(1 for keyword in POSITIVE_KEYWORDS if keyword in title)
        neg_score = sum(1 for keyword in NEGATIVE_KEYWORDS if keyword in title)
        if pos_score > neg_score and pos_score > 0:
            positive_hits.append(title)
        elif neg_score > pos_score and neg_score > 0:
            negative_hits.append(title)
        else:
            neutral_titles.append(title)

    if len(positive_hits) > len(negative_hits):
        overall = "偏正向"
    elif len(negative_hits) > len(positive_hits):
        overall = "偏负向"
    else:
        overall = "中性"

    return {
        "overall": overall,
        "positive": positive_hits[:5],
        "negative": negative_hits[:5],
        "neutral": neutral_titles[:5],
    }
