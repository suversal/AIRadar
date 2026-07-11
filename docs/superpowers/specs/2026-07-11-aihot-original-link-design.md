# AI HOT 原文链接提取设计

日期：2026-07-11  
状态：用户已确认

## 规则

AI HOT RSS 的 `<link>` 是聚合站条目页，不是业务需要的原文链接。解析 `aihot_feed` 时，从 `<description>` 中匹配 `阅读原文：<URL>`，将该 URL 直接写入现有 `RawArticle.source_url` 字段。

仅当 description 中没有合法的 HTTP(S) 原文链接时，才回退使用 RSS `<link>`，保证条目仍可入库。该行为由来源配置显式开启，不影响其他 RSS 源。不新增数据库字段，也不回填历史记录。

## 验证

使用用户提供的完整 RSS item 作为测试夹具，断言 `source_url` 为 `https://casp.ac/reports/ai-enabled-terrorism`，并覆盖无“阅读原文”时回退 `<link>` 的情况。
