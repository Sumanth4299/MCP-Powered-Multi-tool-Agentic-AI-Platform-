from datetime import datetime, timezone
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.agent.graph import create_agent_graph
from backend.agent.state import ToolExecutionRecord
from backend.api.deps import get_current_user
from backend.database import get_db
from backend.models.conversation import Conversation
from backend.models.user import User

router = APIRouter(prefix="/conversations", tags=["Conversations"])


class ConversationCreate(BaseModel):
    title: str = Field(default="New Conversation", max_length=255)


class ConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    thread_id: str
    title: str
    summary: str | None
    created_at: datetime
    updated_at: datetime


class SendMessageRequest(BaseModel):
    message: str = Field(..., min_length=1)


class SendMessageResponse(BaseModel):
    thread_id: str
    response: str
    tool_calls: list[ToolExecutionRecord]


@router.post("", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    payload: ConversationCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConversationResponse:
    thread_id = f"thread_{uuid.uuid4().hex[:16]}"
    conversation = Conversation(
        user_id=current_user.id,
        title=payload.title,
        thread_id=thread_id,
    )
    db.add(conversation)
    await db.commit()
    await db.refresh(conversation)
    return ConversationResponse.model_validate(conversation)


@router.get("", response_model=list[ConversationResponse])
async def list_conversations(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ConversationResponse]:
    stmt = (
        select(Conversation)
        .where(Conversation.user_id == current_user.id)
        .order_by(Conversation.updated_at.desc())
    )
    result = await db.execute(stmt)
    return [ConversationResponse.model_validate(c) for c in result.scalars().all()]


@router.post("/{thread_id}/messages", response_model=SendMessageResponse)
async def send_message(
    thread_id: str,
    payload: SendMessageRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SendMessageResponse:
    # Verify thread ownership
    stmt = select(Conversation).where(
        Conversation.thread_id == thread_id,
        Conversation.user_id == current_user.id,
    )
    result = await db.execute(stmt)
    convo = result.scalar_one_or_none()
    if not convo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation thread not found.",
        )

    # Initialize graph without persistent checkpointer for direct testing,
    # or pass AsyncPostgresSaver instance in production
    app_graph = create_agent_graph()

    config = {"configurable": {"thread_id": thread_id}}
    initial_state = {
        "messages": [HumanMessage(content=payload.message)],
        "user_id": current_user.id,
        "current_thread_id": thread_id,
        "tool_call_history": [],
        "pending_confirmation": False,
    }

    final_state = await app_graph.ainvoke(initial_state, config=config)

    # Update conversation audit timestamp
    convo.updated_at = datetime.now(timezone.utc)
    await db.commit()

    agent_message = final_state["messages"][-1].content
    return SendMessageResponse(
        thread_id=thread_id,
        response=agent_message,
        tool_calls=final_state.get("tool_call_history", []),
    )