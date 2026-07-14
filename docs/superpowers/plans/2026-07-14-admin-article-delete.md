# 后台管理删除文章功能 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在内容管理页（`/admin/events`）给每篇文章加一个真正的硬删除操作，级联清理所有引用它的数据库记录。

**Architecture:** 新增一个 repository 方法 `delete_raw_article(event_id)`，在单个事务内按 FK 依赖顺序删除 `daily_report_entries` → `article_embeddings`/`article_translations`/`editorial_overrides` → `event_cluster_articles`（含主条转移或事件整体删除）→ `processed_articles` → `raw_articles`；新增 `DELETE /api/admin/events/{event_id}` 端点复用现有鉴权；前端 admin-proxy 透传路由补上 `DELETE`；`events-manager.tsx` 表格新增删除按钮 + 确认弹窗。

**Tech Stack:** FastAPI + SQLAlchemy（后端），Next.js App Router + React（前端），pytest（后端测试，SQLite 内存库），Python `unittest` 风格的字符串结构测试（前端测试）。

## Global Constraints

- 删除是硬删除，不是软删除/回收站（`docs/superpowers/specs/2026-07-14-admin-article-delete-design.md` 已确认）。
- 主信源被删除时，自动把主信源转移给该事件下发布时间最早的其他成员；若没有其他成员，整个事件一起删除。
- 文章已出现在历史日报（`daily_report_entries`）里的，删除时也一并移除那条条目。
- 删除按钮放在表格每行操作列，点击后需要确认弹窗，不做二次文字确认。
- 所有新增/修改代码必须遵循仓库现有代码风格（repository 方法用 `delete(Model).where(...)` 的 SQLAlchemy Core 语法，不是 ORM cascade；前端确认弹窗复用 `events-manager.tsx` 里"编辑"按钮已有的 state 驱动 fixed-overlay 模式，**不是** `ui.tsx` 里不存在的 `Modal` 组件）。

---

### Task 1: Repository 方法 `delete_raw_article`

**Files:**
- Modify: `apps/api/app/repositories/radar_repository.py`（在 `update_event_moderation` 方法后面新增，约第 1321 行之后）
- Test: `tests/test_repositories.py`（在文件末尾 fixture 帮手函数之前新增测试方法，参考现有 `test_event_item_includes_coverage_from_every_clustered_source` 的 fixture 搭建风格）

**Interfaces:**
- Consumes：`RadarRepository._resolve_processed_row(event_id) -> tuple[ProcessedArticleModel, RawArticleModel, SourceModel, Optional[EventClusterModel]] | None`（已存在，第 1261 行）；`RadarRepository._find_cluster_for_raw_article(raw_article_id: str) -> Optional[EventClusterModel]`（已存在，第 1245 行）；`RadarRepository._count_distinct_sources(event_cluster_id: str) -> int`（已存在，第 496 行）；`DailyReportEntryModel`、`ArticleEmbeddingModel`、`ArticleTranslationModel`、`EditorialOverrideModel`、`EventClusterArticleModel`、`EventEditorialOverrideModel`、`EventClusterModel`、`ProcessedArticleModel`、`RawArticleModel`（均已 import，见文件顶部 `from app.db.models import (...)`）。
- Produces：`RadarRepository.delete_raw_article(self, event_id: str) -> bool`，供 Task 2 的 API 端点调用。`event_id` 找不到对应文章时返回 `False`（不抛异常，session 不做任何改动）；成功删除返回 `True`（调用方负责 `session.commit()`，与 `update_event_moderation` 的约定一致）。

- [ ] **Step 1: 写失败测试（6 个场景）**

在 `tests/test_repositories.py` 里，找到 `test_update_event_moderation_edits_and_restores` 所在的测试方法群（约第 1860 行附近），在其后新增以下测试方法：

```python
    def test_delete_raw_article_removes_standalone_article_and_all_dependents(self):
        from app.db.models import (
            ArticleEmbeddingModel,
            ArticleTranslationModel,
            EditorialOverrideModel,
            ProcessedArticleModel,
            RawArticleModel,
        )
        from app.repositories.radar_repository import RadarRepository

        with self.Session() as session:
            repository = RadarRepository(session)
            repository.upsert_sources([self._source()])
            repository.upsert_raw_articles([self._article(article_id="solo1", title="孤立文章")])
            repository.upsert_processed_articles([self._processed("solo1")])
            session.commit()
            repository.upsert_article_embedding(
                "solo1", embedding_model="fake", vector=self._vec([0.1]), source_hash="h1"
            )
            session.add(
                ArticleTranslationModel(
                    raw_article_id="solo1",
                    translated_paragraphs=["译文"],
                    translated_blocks=[],
                    source_language="en",
                    target_language="zh",
                    source_hash="h1",
                )
            )
            session.add(EditorialOverrideModel(raw_article_id="solo1", hidden=False))
            session.commit()

            deleted = repository.delete_raw_article("asolo1")
            session.commit()

            self.assertTrue(deleted)
            self.assertIsNone(session.get(RawArticleModel, "solo1"))
            self.assertIsNone(
                session.scalar(
                    select(ProcessedArticleModel).where(
                        ProcessedArticleModel.raw_article_id == "solo1"
                    )
                )
            )
            self.assertIsNone(
                session.scalar(
                    select(ArticleEmbeddingModel).where(
                        ArticleEmbeddingModel.raw_article_id == "solo1"
                    )
                )
            )
            self.assertIsNone(
                session.scalar(
                    select(ArticleTranslationModel).where(
                        ArticleTranslationModel.raw_article_id == "solo1"
                    )
                )
            )
            self.assertIsNone(
                session.scalar(
                    select(EditorialOverrideModel).where(
                        EditorialOverrideModel.raw_article_id == "solo1"
                    )
                )
            )

    def test_delete_raw_article_unknown_event_id_returns_false(self):
        from app.repositories.radar_repository import RadarRepository

        with self.Session() as session:
            repository = RadarRepository(session)

            deleted = repository.delete_raw_article("anonexistent12")

            self.assertFalse(deleted)

    def test_delete_raw_article_removes_only_event_in_its_cluster(self):
        from app.db.models import EventClusterModel
        from app.repositories.radar_repository import RadarRepository
        from dataclasses import replace as dc_replace

        with self.Session() as session:
            repository = RadarRepository(session)
            repository.upsert_sources([self._source()])
            repository.upsert_raw_articles([self._article(article_id="lone1", title="唯一主条", url_hash="ul1")])
            repository.upsert_processed_articles(
                [dc_replace(self._processed("lone1"), event_cluster_id="e-lone")]
            )
            repository.upsert_event_clusters([self._cluster("e-lone", main_article_id="lone1")])
            session.commit()

            deleted = repository.delete_raw_article("e-lone")
            session.commit()

            self.assertTrue(deleted)
            self.assertIsNone(session.get(EventClusterModel, "e-lone"))

    def test_delete_raw_article_reassigns_main_to_earliest_remaining_coverage(self):
        from app.db.models import EventClusterArticleModel, EventClusterModel
        from app.models.domain import RawArticle
        from app.repositories.radar_repository import RadarRepository
        from dataclasses import replace as dc_replace

        with self.Session() as session:
            repository = RadarRepository(session)
            repository.upsert_sources([self._source(), self._other_source()])
            repository.upsert_raw_articles(
                [
                    self._article(article_id="main1", title="主条", url_hash="um1"),
                    RawArticle(
                        id="cov1",
                        source_id="techcrunch",
                        source_name="TechCrunch",
                        source_role="signal",
                        source_tier="T2",
                        source_url="https://techcrunch.com/cov1",
                        title="较早的跟进报道",
                        content="AI model release",
                        author="TechCrunch",
                        published_at=datetime(2026, 7, 1, 7, tzinfo=timezone.utc),
                        language="en",
                        raw_score={"score": 1},
                        metadata={"origin": "fixture"},
                        title_hash="title-cov1",
                        url_hash="uc1",
                    ),
                    RawArticle(
                        id="cov2",
                        source_id="techcrunch",
                        source_name="TechCrunch",
                        source_role="signal",
                        source_tier="T2",
                        source_url="https://techcrunch.com/cov2",
                        title="较晚的跟进报道",
                        content="AI model release",
                        author="TechCrunch",
                        published_at=datetime(2026, 7, 1, 13, tzinfo=timezone.utc),
                        language="en",
                        raw_score={"score": 1},
                        metadata={"origin": "fixture"},
                        title_hash="title-cov2",
                        url_hash="uc2",
                    ),
                ]
            )
            repository.upsert_processed_articles(
                [
                    dc_replace(self._processed("main1"), event_cluster_id="e-main"),
                    dc_replace(self._processed("cov1"), event_cluster_id="e-main"),
                    dc_replace(self._processed("cov2"), event_cluster_id="e-main"),
                ]
            )
            cluster = self._cluster("e-main", main_article_id="main1")
            cluster.article_ids = ["main1", "cov1", "cov2"]
            repository.upsert_event_clusters([cluster])
            session.commit()

            deleted = repository.delete_raw_article("e-main")
            session.commit()

            self.assertTrue(deleted)
            event_cluster = session.get(EventClusterModel, "e-main")
            self.assertIsNotNone(event_cluster)
            # cov1 (07:00) is earlier than cov2 (13:00) - must become the new main
            self.assertEqual(event_cluster.main_article_id, "cov1")
            self.assertEqual(event_cluster.source_count, 1)  # both remaining members are techcrunch
            memberships = {
                m.raw_article_id: m.is_main
                for m in session.scalars(
                    select(EventClusterArticleModel).where(
                        EventClusterArticleModel.event_cluster_id == "e-main"
                    )
                ).all()
            }
            self.assertEqual(memberships, {"cov1": True, "cov2": False})

    def test_delete_raw_article_non_main_member_keeps_cluster_and_recounts_sources(self):
        from app.db.models import EventClusterArticleModel, EventClusterModel
        from app.models.domain import RawArticle
        from app.repositories.radar_repository import RadarRepository
        from dataclasses import replace as dc_replace

        with self.Session() as session:
            repository = RadarRepository(session)
            repository.upsert_sources([self._source(), self._other_source()])
            repository.upsert_raw_articles(
                [
                    self._article(article_id="main2", title="主条", url_hash="um2"),
                    RawArticle(
                        id="cov3",
                        source_id="techcrunch",
                        source_name="TechCrunch",
                        source_role="signal",
                        source_tier="T2",
                        source_url="https://techcrunch.com/cov3",
                        title="待删除的跟进报道",
                        content="AI model release",
                        author="TechCrunch",
                        published_at=datetime(2026, 7, 1, 11, tzinfo=timezone.utc),
                        language="en",
                        raw_score={"score": 1},
                        metadata={"origin": "fixture"},
                        title_hash="title-cov3",
                        url_hash="uc3",
                    ),
                ]
            )
            repository.upsert_processed_articles(
                [
                    dc_replace(self._processed("main2"), event_cluster_id="e-nonmain"),
                    dc_replace(self._processed("cov3"), event_cluster_id="e-nonmain"),
                ]
            )
            cluster = self._cluster("e-nonmain", main_article_id="main2")
            cluster.article_ids = ["main2", "cov3"]
            repository.upsert_event_clusters([cluster])
            session.commit()

            deleted = repository.delete_raw_article("acov3")
            session.commit()

            self.assertTrue(deleted)
            event_cluster = session.get(EventClusterModel, "e-nonmain")
            self.assertIsNotNone(event_cluster)
            self.assertEqual(event_cluster.main_article_id, "main2")
            self.assertEqual(event_cluster.source_count, 1)
            remaining_ids = {
                m.raw_article_id
                for m in session.scalars(
                    select(EventClusterArticleModel).where(
                        EventClusterArticleModel.event_cluster_id == "e-nonmain"
                    )
                ).all()
            }
            self.assertEqual(remaining_ids, {"main2"})

    def test_delete_raw_article_removes_historical_daily_report_entry(self):
        from app.db.models import DailyReportEntryModel
        from app.repositories.radar_repository import RadarRepository

        with self.Session() as session:
            repository = RadarRepository(session)
            repository.upsert_sources([self._source()])
            repository.upsert_raw_articles([self._article(article_id="reported1", title="上过日报的文章")])
            repository.upsert_processed_articles([self._processed("reported1")])
            repository.upsert_daily_report(self._report(date(2026, 7, 1), article_count=1))
            session.commit()
            repository.replace_daily_report_entries(
                date(2026, 7, 1),
                [
                    {
                        "event_id": "areported1",
                        "raw_article_id": "reported1",
                        "reason": "推荐理由",
                        "final_score": 90.0,
                    }
                ],
            )
            session.commit()

            deleted = repository.delete_raw_article("areported1")
            session.commit()

            self.assertTrue(deleted)
            self.assertIsNone(
                session.scalar(
                    select(DailyReportEntryModel).where(
                        DailyReportEntryModel.raw_article_id == "reported1"
                    )
                )
            )
```

- [ ] **Step 2: 跑测试确认全部失败**

Run: `cd /Users/sue/Documents/HotAI && source .venv/bin/activate && python -m pytest tests/test_repositories.py -k delete_raw_article -v`
Expected: 6 个测试全部 FAIL，报错信息类似 `AttributeError: 'RadarRepository' object has no attribute 'delete_raw_article'`

- [ ] **Step 3: 实现 `delete_raw_article`**

在 `apps/api/app/repositories/radar_repository.py` 的 `update_event_moderation` 方法结束处（第 1321 行 `return True` 之后，`get_event_item` 定义之前）插入：

```python
    def delete_raw_article(self, event_id: str) -> bool:
        """Permanently remove one article and every row that references it,
        in FK-dependency order, inside the caller's transaction. Mirrors
        update_event_moderation's event_id resolution and commit contract:
        returns False (session untouched) when event_id doesn't resolve to
        a real article; the caller commits on True."""
        row = self._resolve_processed_row(event_id)
        if row is None:
            return False
        _processed, raw, _source, cluster = row
        raw_article_id = raw.id

        self.session.execute(
            delete(DailyReportEntryModel).where(
                DailyReportEntryModel.raw_article_id == raw_article_id
            )
        )
        self.session.execute(
            delete(ArticleEmbeddingModel).where(
                ArticleEmbeddingModel.raw_article_id == raw_article_id
            )
        )
        self.session.execute(
            delete(ArticleTranslationModel).where(
                ArticleTranslationModel.raw_article_id == raw_article_id
            )
        )
        self.session.execute(
            delete(EditorialOverrideModel).where(
                EditorialOverrideModel.raw_article_id == raw_article_id
            )
        )

        cluster_id = cluster.id if cluster is not None else None
        if cluster_id is None:
            found = self._find_cluster_for_raw_article(raw_article_id)
            cluster_id = found.id if found is not None else None

        if cluster_id is not None:
            event_cluster = self.session.get(EventClusterModel, cluster_id)
            remaining = self.session.scalars(
                select(EventClusterArticleModel)
                .where(EventClusterArticleModel.event_cluster_id == cluster_id)
                .where(EventClusterArticleModel.raw_article_id != raw_article_id)
            ).all()
            self.session.execute(
                delete(EventClusterArticleModel).where(
                    EventClusterArticleModel.raw_article_id == raw_article_id
                )
            )
            # flush before touching `remaining`'s is_main: the partial unique
            # index (one main per event) is checked per statement, so the old
            # main's membership row must actually be gone first (same
            # ordering concern as upsert_event_clusters's demote/promote split)
            self.session.flush()

            if not remaining:
                self.session.execute(
                    delete(EventEditorialOverrideModel).where(
                        EventEditorialOverrideModel.event_cluster_id == cluster_id
                    )
                )
                self.session.execute(
                    delete(EventClusterModel).where(EventClusterModel.id == cluster_id)
                )
            elif event_cluster is not None and event_cluster.main_article_id == raw_article_id:
                earliest_id = self.session.execute(
                    select(EventClusterArticleModel.raw_article_id)
                    .join(
                        RawArticleModel,
                        RawArticleModel.id == EventClusterArticleModel.raw_article_id,
                    )
                    .where(EventClusterArticleModel.event_cluster_id == cluster_id)
                    .order_by(RawArticleModel.published_at.asc())
                    .limit(1)
                ).scalar_one()
                for member in remaining:
                    member.is_main = member.raw_article_id == earliest_id
                event_cluster.main_article_id = earliest_id
                event_cluster.source_count = self._count_distinct_sources(cluster_id)
            elif event_cluster is not None:
                event_cluster.source_count = self._count_distinct_sources(cluster_id)

        self.session.execute(
            delete(ProcessedArticleModel).where(
                ProcessedArticleModel.raw_article_id == raw_article_id
            )
        )
        self.session.execute(delete(RawArticleModel).where(RawArticleModel.id == raw_article_id))
        self.session.flush()
        return True
```

- [ ] **Step 4: 跑测试确认全部通过**

Run: `cd /Users/sue/Documents/HotAI && source .venv/bin/activate && python -m pytest tests/test_repositories.py -k delete_raw_article -v`
Expected: 6 个测试全部 PASS

- [ ] **Step 5: 跑全量后端测试确认无回归**

Run: `cd /Users/sue/Documents/HotAI && source .venv/bin/activate && python -m pytest tests/ -q`
Expected: 全部 PASS，数量应为之前的 389 + 6 = 395

- [ ] **Step 6: Commit**

```bash
cd /Users/sue/Documents/HotAI
git add apps/api/app/repositories/radar_repository.py tests/test_repositories.py
git commit -m "feat(admin): add cascading delete_raw_article repository method"
```

---

### Task 2: API 端点 `DELETE /api/admin/events/{event_id}`

**Files:**
- Modify: `apps/api/app/main.py`（在 `admin_moderate_event` 之后，约第 893 行 `return {"status": "ok", "updated": sorted(fields)}` 之后新增）
- Create: `tests/test_admin_events_api.py`

**Interfaces:**
- Consumes：Task 1 的 `RadarRepository.delete_raw_article(event_id: str) -> bool`；已存在的 `_admin_repository_context()`（`main.py:593`）、`admin_guard`（`main.py:263`）、`HTTPException`。
- Produces：`DELETE /api/admin/events/{event_id}` 端点，成功返回 `200 {"status": "ok", "deleted_raw_article_id": "<raw_article_id>"}`，未找到返回 `404`。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_admin_events_api.py`（结构参照 `tests/test_admin_sources.py` 的 fake-repository + TestClient 模式）：

```python
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parents[1] / "apps" / "api"))

try:
    from fastapi.testclient import TestClient
except ModuleNotFoundError:
    TestClient = None

AUTH = {"Authorization": "Bearer secret-token"}


class _FakeSession:
    def commit(self):
        pass


class _FakeEventRepository:
    def __init__(self):
        self.session = _FakeSession()
        self.deleted_event_ids: list[str] = []
        self.deletable_event_ids = {"e-real", "apseudo12345"}

    def delete_raw_article(self, event_id: str) -> bool:
        self.deleted_event_ids.append(event_id)
        return event_id in self.deletable_event_ids


@unittest.skipIf(TestClient is None, "FastAPI is not installed in this environment")
class AdminEventsDeleteApiTests(unittest.TestCase):
    def setUp(self):
        self.repository = _FakeEventRepository()
        env = patch.dict("os.environ", {"ADMIN_TOKEN": "secret-token"})
        env.start()
        self.addCleanup(env.stop)

    def _client(self):
        from app import main as module

        app = module.create_app(report_repository_factory=lambda: self.repository)
        return TestClient(app)

    def test_delete_event_requires_auth(self):
        client = self._client()

        denied = client.delete("/api/admin/events/e-real")

        self.assertEqual(denied.status_code, 401)
        self.assertEqual(self.repository.deleted_event_ids, [])

    def test_delete_known_event_returns_ok_with_raw_article_id(self):
        client = self._client()

        response = client.delete("/api/admin/events/e-real", headers=AUTH)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "deleted_raw_article_id": "e-real"})
        self.assertEqual(self.repository.deleted_event_ids, ["e-real"])

    def test_delete_unknown_event_returns_404(self):
        client = self._client()

        response = client.delete("/api/admin/events/nope", headers=AUTH)

        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
```

Note: `deleted_raw_article_id` 在这个 fake 测试里就是 `event_id` 本身（fake repository 不做真正的 id 解析，只验证 API 层的调度/状态码/鉴权行为；真正的 `raw_article_id` 解析已经在 Task 1 的 repository 测试里覆盖过）。

- [ ] **Step 2: 跑测试确认全部失败**

Run: `cd /Users/sue/Documents/HotAI && source .venv/bin/activate && python -m pytest tests/test_admin_events_api.py -v`
Expected: 3 个测试全部 FAIL（`test_delete_event_requires_auth` 可能因为路由不存在返回 404 而非 401，其余两个因为 405 Method Not Allowed 或 404 而失败）

- [ ] **Step 3: 实现端点**

在 `apps/api/app/main.py` 的 `admin_moderate_event` 函数后面（第 893 行之后，`@app.post("/api/admin/refresh-latest"...)` 之前）插入：

```python
    @app.delete("/api/admin/events/{event_id}", dependencies=[admin_guard])
    def admin_delete_event(event_id: str) -> dict:
        from app.repositories.radar_repository import RadarRepository

        with _admin_repository_context() as repository:
            deleted = repository.delete_raw_article(event_id)
            if not deleted:
                raise HTTPException(status_code=404, detail="Event not found")
            commit = getattr(getattr(repository, "session", None), "commit", None)
            if callable(commit):
                commit()
        return {"status": "ok", "deleted_raw_article_id": event_id}
```

注：这里 `deleted_raw_article_id` 暂时回传 `event_id` 本身以保持与 fake-repository 测试的契约一致——真实 `RadarRepository.delete_raw_article` 内部才知道解析出的真实 `raw_article_id`，如果需要在响应里回传真实值，可以后续把 `delete_raw_article` 的返回类型从 `bool` 改为 `Optional[str]`（成功时返回 `raw_article_id`，失败返回 `None`）。本计划范围内保持 `bool` 返回值，响应体的 `deleted_raw_article_id` 用 `event_id` 占位即可，不影响功能正确性（该字段目前没有前端消费方）。

- [ ] **Step 4: 跑测试确认全部通过**

Run: `cd /Users/sue/Documents/HotAI && source .venv/bin/activate && python -m pytest tests/test_admin_events_api.py -v`
Expected: 3 个测试全部 PASS

- [ ] **Step 5: 跑全量后端测试确认无回归**

Run: `cd /Users/sue/Documents/HotAI && source .venv/bin/activate && python -m pytest tests/ -q`
Expected: 全部 PASS，数量应为 395 + 3 = 398

- [ ] **Step 6: Commit**

```bash
cd /Users/sue/Documents/HotAI
git add apps/api/app/main.py tests/test_admin_events_api.py
git commit -m "feat(admin): add DELETE /api/admin/events/{event_id} endpoint"
```

---

### Task 3: 前端 admin-proxy 透传 DELETE 方法

**Files:**
- Modify: `apps/web/app/api/admin-proxy/[...path]/route.ts`
- Modify: `tests/test_web_app_structure.py`

**Interfaces:**
- Consumes：已存在的 `forward(request, path, method)` 帮手函数（`route.ts` 顶部已定义，`PUT`/`PATCH`/`POST`/`GET` 都是薄封装）。
- Produces：`export async function DELETE(request: Request, { params }: Params)`，供 Task 4 的前端调用 `/api/admin-proxy/events/{event_id}` 时使用。

- [ ] **Step 1: 写失败测试**

在 `tests/test_web_app_structure.py` 的 `test_admin_dashboard_exposes_schedule_panel` 方法内（约第 242 行 `self.assertIn("export async function PUT", proxy_route)` 之后）新增一行：

```python
        self.assertIn("export async function DELETE", proxy_route)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /Users/sue/Documents/HotAI && source .venv/bin/activate && python -m pytest tests/test_web_app_structure.py -k test_admin_dashboard_exposes_schedule_panel -v`
Expected: FAIL，`AssertionError: 'export async function DELETE' not found in ...`

- [ ] **Step 3: 实现 DELETE 透传**

在 `apps/web/app/api/admin-proxy/[...path]/route.ts` 的 `export async function PUT` 定义之后追加：

```typescript
export async function DELETE(request: Request, { params }: Params) {
  return forward(request, (await params).path, "DELETE");
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd /Users/sue/Documents/HotAI && source .venv/bin/activate && python -m pytest tests/test_web_app_structure.py -k test_admin_dashboard_exposes_schedule_panel -v`
Expected: PASS

- [ ] **Step 5: 前端类型检查**

Run: `cd /Users/sue/Documents/HotAI/apps/web && npx tsc --noEmit`
Expected: 无输出（无类型错误）

- [ ] **Step 6: Commit**

```bash
cd /Users/sue/Documents/HotAI
git add apps/web/app/api/admin-proxy/\[...path\]/route.ts tests/test_web_app_structure.py
git commit -m "feat(admin): forward DELETE through admin-proxy route"
```

---

### Task 4: 前端删除按钮 + 确认弹窗

**Files:**
- Modify: `apps/web/app/admin/events/events-manager.tsx`
- Modify: `tests/test_web_app_structure.py`

**Interfaces:**
- Consumes：Task 3 的 `/api/admin-proxy/events/{event_id}` DELETE 透传；文件内已有的 `api(path, init)` 帮手函数（第 48-58 行）、`run(eventId, action)` 帮手函数（第 98-109 行）、`AdminEvent` 类型（第 7-20 行）。
- Produces：无（叶子任务，UI 层）。

- [ ] **Step 1: 写失败测试**

在 `tests/test_web_app_structure.py` 里找到内容管理相关的测试（可放在 `test_admin_content_manager_filters_by_configured_main_source` 附近，约第 244 行之后），新增：

```python
    def test_admin_content_manager_supports_deleting_an_article(self):
        manager_source = (
            WEB / "app" / "admin" / "events" / "events-manager.tsx"
        ).read_text(encoding="utf-8")

        self.assertIn("deleteEvent", manager_source)
        self.assertIn('method: "DELETE"', manager_source)
        self.assertIn("确定要彻底删除这篇文章吗", manager_source)
        self.assertIn("此操作不可恢复", manager_source)
        self.assertIn("deletingEvent", manager_source)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /Users/sue/Documents/HotAI && source .venv/bin/activate && python -m pytest tests/test_web_app_structure.py -k test_admin_content_manager_supports_deleting_an_article -v`
Expected: FAIL（`deleteEvent`/`deletingEvent` 等字符串都不存在）

- [ ] **Step 3: 实现删除按钮 + 确认弹窗**

3a. 在 `apps/web/app/admin/events/events-manager.tsx` 的 state 声明区（约第 85 行 `const [editing, setEditing] = useState<AdminEvent | null>(null);` 之后）新增一行：

```typescript
  const [deletingEvent, setDeletingEvent] = useState<AdminEvent | null>(null);
```

3b. 在 `toggleHidden` 函数定义之后（约第 118 行之后）新增删除的 action 函数：

```typescript
  async function deleteEvent(event: AdminEvent) {
    await run(event.event_id, async () => {
      await api(`events/${event.event_id}`, { method: "DELETE" });
      setDeletingEvent(null);
    });
  }
```

3c. 在表格操作列（约第 324-346 行，"编辑"按钮后面）新增删除按钮：

```tsx
                <td className="px-4 py-3">
                  <div className="flex flex-nowrap gap-1.5 text-xs font-semibold">
                    <button
                      className={`shrink-0 whitespace-nowrap rounded border px-2.5 py-1 ${
                        event.hidden
                          ? "border-success/40 text-success hover:bg-success/10"
                          : "border-line text-ink-mid hover:border-danger/40 hover:text-danger"
                      }`}
                      disabled={busy === event.event_id}
                      onClick={() => toggleHidden(event)}
                      type="button"
                    >
                      {event.hidden ? "恢复" : "隐藏"}
                    </button>
                    <button
                      className="shrink-0 whitespace-nowrap rounded border border-line px-2.5 py-1 text-ink-mid hover:border-signal/40 hover:text-signal"
                      onClick={() => setEditing(event)}
                      type="button"
                    >
                      编辑
                    </button>
                    <button
                      className="shrink-0 whitespace-nowrap rounded border border-line px-2.5 py-1 text-ink-mid hover:border-danger/40 hover:text-danger"
                      disabled={busy === event.event_id}
                      onClick={() => setDeletingEvent(event)}
                      type="button"
                    >
                      删除
                    </button>
                  </div>
                </td>
```

（这一步是把现有的 `<td>...</td>` 操作列整体替换为上面这段，只是在"编辑"按钮后新增了"删除"按钮，其余不变。）

3d. 在文件末尾"编辑"弹窗（约第 437-490 行 `{editing ? (...) : null}`）之后新增删除确认弹窗，紧跟其后：

```tsx
      {deletingEvent ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4">
          <div className="w-full max-w-md rounded-md border border-line bg-panel p-6">
            <h2 className="text-lg font-semibold text-ink">删除文章</h2>
            <p className="mt-3 text-sm text-ink-mid">
              确定要彻底删除这篇文章吗？此操作不可恢复。
            </p>
            <p className="mt-2 truncate text-sm font-semibold text-ink" title={deletingEvent.title}>
              {deletingEvent.title}
            </p>
            <div className="mt-5 flex justify-end gap-3 text-sm font-semibold">
              <button
                className="rounded border border-line px-4 py-2 text-ink-mid hover:text-ink"
                onClick={() => setDeletingEvent(null)}
                type="button"
              >
                取消
              </button>
              <button
                className="rounded border border-danger bg-danger px-4 py-2 text-canvas hover:bg-danger/90"
                disabled={busy === deletingEvent.event_id}
                onClick={() => deleteEvent(deletingEvent)}
                type="button"
              >
                确认删除
              </button>
            </div>
          </div>
        </div>
      ) : null}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd /Users/sue/Documents/HotAI && source .venv/bin/activate && python -m pytest tests/test_web_app_structure.py -k test_admin_content_manager_supports_deleting_an_article -v`
Expected: PASS

- [ ] **Step 5: 跑全量前端结构测试 + 类型检查**

Run:
```bash
cd /Users/sue/Documents/HotAI && source .venv/bin/activate && python -m pytest tests/test_web_app_structure.py -q
cd /Users/sue/Documents/HotAI/apps/web && npx tsc --noEmit
```
Expected: 两条命令都无失败/无类型错误

- [ ] **Step 6: Commit**

```bash
cd /Users/sue/Documents/HotAI
git add apps/web/app/admin/events/events-manager.tsx tests/test_web_app_structure.py
git commit -m "feat(admin): add delete button with confirmation dialog to content manager"
```

---

### Task 5: 端到端验证

**Files:** 无新增/修改，纯验证任务。

- [ ] **Step 1: 跑全量后端测试套件**

Run: `cd /Users/sue/Documents/HotAI && source .venv/bin/activate && python -m pytest tests/ -q`
Expected: 全部 PASS（数量应为 Task 1-4 之前的 389 + 6 + 3 + 1 + 1 = 400）

- [ ] **Step 2: 跑前端生产构建**

Run: `cd /Users/sue/Documents/HotAI/apps/web && npm run build`
Expected: `✓ Compiled successfully`，无类型/构建错误

- [ ] **Step 3: 真实点击验证**

登录管理后台 `/admin/events`，找一篇测试用/可删除的文章：
1. 点击"删除"按钮，确认弹窗正确弹出，标题显示正确
2. 点击"取消"，弹窗关闭，文章仍在列表中
3. 再次点击"删除" → "确认删除"，确认列表刷新后该文章消失
4. 如果该文章曾是某个多信源事件的主条，确认事件详情页 `/event/{event_id}` 主信源已经变成原来 coverage 里最早的那条，其余报道依然可见
5. 检查后端日志/admin overview 的 `counts` 是否相应减少（可选，非阻塞项）

- [ ] **Step 4: 更新计划文件，标记全部完成**

把本文件里所有 `- [ ]` 改成 `- [x]`。
