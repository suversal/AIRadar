"""Reject digest posts - 早报 / 晚报 / 快讯合集 - before they cost an AI call.

A digest bundles several unrelated stories under one headline. The pipeline
treats every article as one event, which leaves no honest way to present one:
title it from the body and the reader clicks 「DeepSeek API 正式执行峰谷定价」
to land on a round-up of car sales and phone launches; keep the publisher's
title and the summary underneath it talks about something the title never
mentions. Measured on 2026-08-18, the publisher's three headline items were all
non-AI while the AI summary covered DeepSeek pricing - the two halves of the
card had nothing in common.

Dropping them costs no coverage. Every AI story a digest carried was also filed
as a standalone report by a primary source that same day - 「DeepSeek API 峰谷
定价」 and 「DeepSeek V4 Pro 上线国家超算互联网」 both had their own IT之家
article, already selected. A digest is a re-telling, not a source.

Detection is deliberately a title rule rather than an AI judgement: it is free,
runs before the prefilter call, and - more importantly - is auditable. You can
read the regex and know exactly which articles it removes, which matters for a
filter that silently drops content.

The rule needs BOTH halves, because the column name alone does not mean digest:

    早报｜A/B/C                       -> digest (3 items)
    IT早报 0818：A；B；C；D           -> digest (4 items)
    派早报：A、B等                    -> digest (2 items)
    快讯｜范式PhanRouter上线智谱GLM-5.3 -> NOT a digest, one story with a 快讯 label
    圆通速递：6月快递产品收入58.83亿元  -> NOT a digest, 速递 here is a company name

Chinese comma (，) is not a separator: single-story headlines are full of them.

Known limit: this reads the title only, so a round-up whose headline carries no
column name still gets through. It is a proxy, not a content judgement.
"""

from __future__ import annotations

import re

#: 栏目名前最多 4 个字（"IT早报""氪星晚报""派早报"），名后允许夹日期
#: （"早报 0818"），再接一个冒号或竖线。限制前缀长度是为了不让标题中段
#: 出现的"快讯""要闻"等字眼把整条普通新闻误判成合集。
_MARKER = re.compile(
    r"^[^：:｜|]{0,4}(早报|晚报|午报|日报|周报|快讯|简讯|速览|要闻)\s*\d{0,6}\s*[｜|：:]\s*(.+)$"
)

#: 条目之间的分隔符。中文逗号刻意不在其中。
_ITEM_SEPARATOR = re.compile(r"[/／；;、]")

#: 达到几段才算合集。1 段说明这是一条带栏目标签的单条新闻。
MIN_DIGEST_ITEMS = 2


def is_digest_title(title: str | None) -> bool:
    """标题是否形如「栏目名 + 多条互不相关的新闻」。"""
    match = _MARKER.match((title or "").strip())
    if not match:
        return False
    items = [part for part in _ITEM_SEPARATOR.split(match.group(2)) if part.strip()]
    return len(items) >= MIN_DIGEST_ITEMS
