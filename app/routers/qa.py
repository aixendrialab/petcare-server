from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
from app.routers.security import current_user_id
from app.core.db import get_conn

router = APIRouter()

class QuestionIn(BaseModel):
    question: str

class AnswerIn(BaseModel):
    answer: str

@router.get("/shop/products/{product_id}/qa")
async def product_qa(product_id: int, limit: int = Query(20, ge=1, le=50), user_id: int = Depends(current_user_id)):
    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute(
            """
            SELECT q.id, q.question, u.name, q.created_at
            FROM item_questions q
            JOIN users u ON u.id=q.user_id
            WHERE q.product_id=%s
            ORDER BY q.created_at DESC
            LIMIT %s
            """,
            (product_id, limit),
        )
        qrows = await cur.fetchall()

        items = []
        for qid, qtext, qby, qat in qrows:
            await cur.execute(
                """
                SELECT a.id, a.answer, u.name, a.created_at
                FROM item_answers a
                JOIN users u ON u.id=a.user_id
                WHERE a.question_id=%s
                ORDER BY a.created_at DESC
                LIMIT 1
                """,
                (qid,),
            )
            ar = await cur.fetchone()
            items.append({
                "question_id": int(qid),
                "question": qtext,
                "asked_by": qby or "User",
                "asked_at": qat.isoformat() if hasattr(qat, "isoformat") else str(qat),
                "answer_id": int(ar[0]) if ar else None,
                "answer": ar[1] if ar else None,
                "answered_by": (ar[2] if ar else None),
                "answered_at": (ar[3].isoformat() if (ar and hasattr(ar[3], "isoformat")) else (str(ar[3]) if ar else None)),
            })
    return {"items": items}

@router.post("/shop/products/{product_id}/questions")
async def ask_question(product_id: int, body: QuestionIn, user_id: int = Depends(current_user_id)):
    if not body.question.strip():
        raise HTTPException(400, "Question cannot be empty")
    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute("SELECT id FROM catalog_products WHERE id=%s", (product_id,))
        if not await cur.fetchone():
            raise HTTPException(404, "Product not found")
        await cur.execute(
            "INSERT INTO item_questions (product_id, user_id, question) VALUES (%s,%s,%s) RETURNING id",
            (product_id, user_id, body.question.strip()),
        )
        qid = int((await cur.fetchone())[0])
    return {"ok": True, "question_id": qid}

@router.post("/shop/questions/{question_id}/answers")
async def answer_question(question_id: int, body: AnswerIn, user_id: int = Depends(current_user_id)):
    if not body.answer.strip():
        raise HTTPException(400, "Answer cannot be empty")
    async with get_conn() as conn, conn.cursor() as cur:
        await cur.execute("SELECT id FROM item_questions WHERE id=%s", (question_id,))
        if not await cur.fetchone():
            raise HTTPException(404, "Question not found")
        await cur.execute(
            "INSERT INTO item_answers (question_id, user_id, answer) VALUES (%s,%s,%s) RETURNING id",
            (question_id, user_id, body.answer.strip()),
        )
        aid = int((await cur.fetchone())[0])
    return {"ok": True, "answer_id": aid}
