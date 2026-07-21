"""Database smoke test for the governed knowledge orchestration path.

Run this only against a disposable or local development database.  It creates
and removes its own user, document and derived knowledge assets.
"""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import delete, select

from infra.storage.database import AsyncSessionLocal
from infra.storage.models import Document, DocumentChunk, KnowledgeSource, User
from knowledge.compiler import compile_document_knowledge_in_session
from knowledge.lint import run_knowledge_lint
from knowledge.query import search_knowledge


async def main() -> None:
    suffix = uuid.uuid4().hex[:12]
    user_id = str(uuid.uuid4())
    document_id = str(uuid.uuid4())
    tenant_id = "knowledge-test-tenant"
    workspace_id = "knowledge-test-workspace"
    try:
        async with AsyncSessionLocal() as db:
            db.add(
                User(
                    id=user_id,
                    email=f"knowledge-{suffix}@example.test",
                    display_name="Knowledge Test",
                    status="active",
                )
            )
            db.add(
                Document(
                    id=document_id,
                    owner_id=user_id,
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    title="退款制度",
                    file_type="md",
                    content="退款需要在订单完成后七天内申请。提交申请后由客服审核。",
                    status="ready",
                    chunk_count=1,
                )
            )
            db.add(
                DocumentChunk(
                    id=str(uuid.uuid4()),
                    document_id=document_id,
                    chunk_index=0,
                    content="退款需要在订单完成后七天内申请。提交申请后由客服审核。",
                    chunk_metadata='{"heading": "退款流程"}',
                )
            )
            await db.commit()

        async with AsyncSessionLocal() as db:
            compiled = await compile_document_knowledge_in_session(db, document_id)
            lint = await run_knowledge_lint(
                db,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                owner_id=user_id,
            )
            await db.commit()

        # A source update must publish a new version and remove the old version
        # from the active retrieval path without deleting its audit history.
        async with AsyncSessionLocal() as db:
            document = await db.get(Document, document_id)
            assert document is not None
            document.version = 2
            document.content = "退款需要在订单完成后十四天内申请。提交申请后由客服审核。"
            chunk = await db.scalar(select(DocumentChunk).where(DocumentChunk.document_id == document_id))
            assert chunk is not None
            chunk.content = "退款需要在订单完成后十四天内申请。提交申请后由客服审核。"
            await db.commit()

        async with AsyncSessionLocal() as db:
            recompiled = await compile_document_knowledge_in_session(db, document_id)
            lint = await run_knowledge_lint(
                db,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                owner_id=user_id,
            )
            await db.commit()

        hits = await search_knowledge(
            query="十四天",
            user_id=user_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            top_k=5,
        )
        assert compiled["status"] == "succeeded", compiled
        assert compiled["claims"] >= 1, compiled
        assert recompiled["status"] == "succeeded", recompiled
        assert any(hit["source_type"] == "knowledge_page" for hit in hits), hits
        assert any(hit["source_type"] == "knowledge_claim" for hit in hits), hits
        assert all(hit["provenance"].get("document_id") == document_id for hit in hits), hits
        assert all(hit["source_version_id"] != compiled.get("source_version_id") for hit in hits)
        stale_hits = await search_knowledge(
            query="七天",
            user_id=user_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            top_k=5,
        )
        denied_hits = await search_knowledge(
            query="十四天",
            user_id="other-user",
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            top_k=5,
        )
        assert not stale_hits, stale_hits
        assert not denied_hits, denied_hits
        assert lint["open_count"] == 0, lint
        print("knowledge database integration: passed")
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(KnowledgeSource).where(KnowledgeSource.document_id == document_id))
            await db.execute(delete(Document).where(Document.id == document_id))
            await db.execute(delete(User).where(User.id == user_id))
            await db.commit()


if __name__ == "__main__":
    asyncio.run(main())
