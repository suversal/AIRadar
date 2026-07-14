# 后台管理删除文章功能设计

日期：2026-07-14
状态：用户已确认

## 背景

内容管理页（`/admin/events`）目前只有"隐藏"（`hidden`）能处理错误内容，隐藏只是不在公开页面展示，文章记录本身仍留在数据库里、仍可能参与事件聚簇/热点计算。用户需要的是能彻底清除脏数据（抓错的、测试数据、重复内容）的硬删除，而不是软删除/回收站。

## 数据模型与级联范围

`raw_articles` 被以下表通过外键引用：`processed_articles`、`editorial_overrides`、`article_translations`、`article_embeddings`、`event_cluster_articles`、`event_clusters.main_article_id`、`daily_report_entries`。删除一篇文章必须在一次事务内按依赖顺序清理干净，否则会留下外键约束冲突或孤儿数据。

## 删除顺序（单个事务内，失败整体回滚）

1. `daily_report_entries` where `raw_article_id = X` —— 历史日报也一并移除这条条目（日报是从 `raw_articles`/`processed_articles` 实时渲染的快照式列表，不单独存正文，删除后自然不再出现）。
2. `article_embeddings`、`article_translations`、`editorial_overrides` where `raw_article_id = X`。
3. 处理事件归属（`event_cluster_articles`，事件成员关系的唯一真相来源）：
   - 查这篇文章是否属于某个 `event_clusters`。
   - 若它是该事件的 `main_article_id`：
     - 查同一事件里除它之外、按 `raw_articles.published_at` 最早的成员；若存在，把 `event_clusters.main_article_id` 和该成员在 `event_cluster_articles` 里的 `is_main` 转移过去。
     - 若不存在其他成员（这是事件下唯一文章），删除整个 `event_clusters` 行及其 `event_editorial_overrides` 行。
   - 若它只是非主要成员：仅移除它自己的 `event_cluster_articles` 行，并调用现有的 `_count_distinct_sources(cluster.id)` 重新写回 `event_clusters.source_count`（避免删除后信源数量显示比实际多）。
   - 最后删除这篇文章自己的 `event_cluster_articles` 行（如果上面还没删）。
4. `processed_articles` where `raw_article_id = X`。
5. `raw_articles` where `id = X`。

复用现有的 `RadarRepository._resolve_processed_row(event_id)` 把内容管理表格行携带的 `event_id`（可能是真实 `event_clusters.id`，也可能是伪地址 `a{raw_id前12位}`）解析回 `raw_article_id`，与 `update_event_moderation` 用的是同一套解析逻辑，行为一致。

新增 repository 方法：`delete_raw_article(event_id: str) -> bool`（找不到对应文章返回 `False`，成功返回 `True`）。

## API

新增 `DELETE /api/admin/events/{event_id}`，与现有 `PATCH /api/admin/events/{event_id}` 同级、复用同一套 admin 鉴权（`admin_guard`）。

- 成功：`200 {"status": "ok", "deleted_raw_article_id": "<raw_article_id>"}`
- 未找到：`404`

## 前端

`events-manager.tsx` 表格每行操作列（现有隐藏/编辑按钮旁）新增一个删除图标按钮：

- 点击后弹出确认框（复用现有 `ui.tsx` 的 `Modal` 组件，与编辑弹窗风格一致），文案："确定要彻底删除这篇文章吗？此操作不可恢复。"
- 确认后调用 `DELETE` 接口，复用现有 `run()` 帮手函数的 busy/error 处理模式，成功后 `router.refresh()` 刷新当前页列表。
- 网络/接口失败沿用现有的 `message` 状态展示错误提示，不额外设计新的错误 UI。

## 测试

**后端**（`tests/test_repositories.py`，参考现有 repository 测试的 fixture 风格）：
- 删除一篇孤立文章（无事件成员关系）：断言 `raw_articles`/`processed_articles`/`editorial_overrides`/`article_translations`/`article_embeddings` 对应行都被清空。
- 删除某事件的 `main_article_id`、且事件还有其他成员：断言 `main_article_id` 和 `is_main` 转移给了发布时间最早的剩余成员，事件本身未被删除。
- 删除某事件下唯一的文章：断言 `event_clusters` 行本身也被删除。
- 删除某事件的非主要成员：断言该事件保留、`source_count` 正确递减、主条不受影响。
- 删除一篇已出现在某天 `daily_report_entries` 里的文章：断言那条历史条目也被移除。
- 删除不存在的 `event_id`：返回 `False`，不抛异常。

**前端**（`tests/test_web_app_structure.py`，沿用该文件"检查源码关键字符串/结构"的风格）：
- 断言 `events-manager.tsx` 里存在删除按钮、确认弹窗文案、对 `DELETE` 接口的调用。

## 验证方式

跑通后端 pytest 全量套件 + 前端 `tsc --noEmit`/`next build`；用管理后台真实点一次删除，确认列表刷新后该文章消失，且同事件的其他 coverage 文章仍正常展示。
