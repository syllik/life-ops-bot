from __future__ import annotations

from collections.abc import Awaitable, Callable

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    MessageOriginChannel,
    MessageOriginChat,
    MessageOriginHiddenUser,
    MessageOriginUser,
)

from .core import Capture, Issue, LifeOps
from .github import GitHubError

SAVE_ERROR = "❌ Couldn't save this item. Please try again."
ACTION_ERROR = "❌ Couldn't update this item. Please try again."


def build_router(
    life_ops: LifeOps,
    allowed_user_id: int,
    *,
    propagate_github_errors: bool = False,
) -> Router:
    router = Router(name="life-ops")

    @router.message()
    async def capture_message(message: Message) -> None:
        await handle_message(
            message,
            life_ops,
            allowed_user_id,
            propagate_github_errors=propagate_github_errors,
        )

    @router.callback_query()
    async def issue_callback(callback: CallbackQuery) -> None:
        await handle_callback(
            callback,
            life_ops,
            allowed_user_id,
            propagate_github_errors=propagate_github_errors,
        )

    return router


async def handle_message(
    message: Message,
    life_ops: LifeOps,
    allowed_user_id: int,
    *,
    propagate_github_errors: bool = False,
) -> None:
    sender = message.from_user
    if sender is None or sender.id != allowed_user_id:
        return

    text = message.text
    if text is None:
        return

    capture = Capture(
        text=text,
        chat_id=message.chat.id,
        message_id=message.message_id,
        forwarded_from=describe_forward_origin(message),
        link_targets=text_link_targets(message),
    )
    try:
        issue = await life_ops.capture(capture)
    except GitHubError as exc:
        if propagate_github_errors and exc.retryable:
            raise
        await message.answer(SAVE_ERROR)
        return

    await message.answer(
        f"✅ Saved #{issue.number}\n{issue.url}",
        reply_markup=saved_keyboard(issue),
        disable_web_page_preview=True,
    )


async def handle_callback(
    callback: CallbackQuery,
    life_ops: LifeOps,
    allowed_user_id: int,
    *,
    propagate_github_errors: bool = False,
) -> None:
    sender = callback.from_user
    if sender.id != allowed_user_id:
        return

    parsed = parse_callback(callback.data)
    if parsed is None:
        await _answer_callback(callback, ACTION_ERROR, show_alert=True)
        return

    action, issue_number = parsed
    operation: Callable[[int], Awaitable[Issue]] = (
        life_ops.done if action == "done" else life_ops.later
    )
    try:
        await operation(issue_number)
    except GitHubError as exc:
        if propagate_github_errors and exc.retryable:
            raise
        await _answer_callback(callback, ACTION_ERROR, show_alert=True)
        return

    await _answer_callback(
        callback,
        "Done" if action == "done" else "Moved to Later",
    )


async def _answer_callback(
    callback: CallbackQuery,
    text: str,
    *,
    show_alert: bool = False,
) -> None:
    try:
        if show_alert:
            await callback.answer(text, show_alert=True)
        else:
            await callback.answer(text)
    except TelegramBadRequest:
        # Callback answers are time-limited by Telegram. A 400 cannot be repaired by
        # redelivering the immutable callback, while network/5xx errors still propagate.
        return


def saved_keyboard(issue: Issue) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Done", callback_data=f"done:{issue.number}"),
                InlineKeyboardButton(text="Later", callback_data=f"later:{issue.number}"),
                InlineKeyboardButton(text="GitHub", url=issue.url),
            ]
        ]
    )


def parse_callback(data: str | None) -> tuple[str, int] | None:
    if data is None:
        return None
    action, separator, raw_number = data.partition(":")
    if separator != ":" or action not in {"done", "later"}:
        return None
    try:
        issue_number = int(raw_number)
    except ValueError:
        return None
    if issue_number <= 0:
        return None
    return action, issue_number


def text_link_targets(message: Message) -> tuple[str, ...]:
    entities = message.entities or ()
    return tuple(
        entity.url
        for entity in entities
        if entity.type == "text_link" and entity.url is not None
    )


def describe_forward_origin(message: Message) -> str | None:
    origin = message.forward_origin
    if origin is None:
        return None
    if isinstance(origin, MessageOriginUser):
        username = f"@{origin.sender_user.username}" if origin.sender_user.username else None
        name = origin.sender_user.full_name
        return f"user {username or name} (id={origin.sender_user.id})"
    if isinstance(origin, MessageOriginHiddenUser):
        return f"hidden user {origin.sender_user_name}"
    if isinstance(origin, MessageOriginChat):
        return f"chat {origin.sender_chat.title} (id={origin.sender_chat.id})"
    if isinstance(origin, MessageOriginChannel):
        return (
            f"channel {origin.chat.title} (id={origin.chat.id}), "
            f"message_id={origin.message_id}"
        )
    return "unknown forward origin"
