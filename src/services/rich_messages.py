from __future__ import annotations

import logging
from typing import Any

import markdown
from bs4 import BeautifulSoup, NavigableString, Tag
from pyrogram import raw
from pyrogram.types import InputRichMessage

from src.services.local_web import save_to_local_web

logger = logging.getLogger(__name__)
RICH_MESSAGE_LIMIT = 32_768


def _inline(node: Tag | NavigableString):
    if isinstance(node, NavigableString):
        return raw.types.TextPlain(text=str(node))
    if node.name.lower() == "br":
        return raw.types.TextPlain(text="\n")
    children = [_inline(child) for child in node.children]
    children = [child for child in children if child is not None]
    value = children[0] if len(children) == 1 else raw.types.TextConcat(texts=children)
    if not children:
        value = raw.types.TextPlain(text="")
    name = node.name.lower()
    if name in {"strong", "b"}:
        return raw.types.TextBold(text=value)
    if name in {"em", "i"}:
        return raw.types.TextItalic(text=value)
    if name in {"del", "s", "strike"}:
        return raw.types.TextStrike(text=value)
    if name == "u":
        return raw.types.TextUnderline(text=value)
    if name == "mark":
        return raw.types.TextMarked(text=value)
    if name == "code":
        return raw.types.TextFixed(text=value)
    if name == "a" and node.get("href"):
        return raw.types.TextUrl(text=value, url=str(node["href"]), webpage_id=0)
    return value


def _list_block(node: Tag, ordered: bool):
    items = []
    for index, item in enumerate(node.find_all("li", recursive=False), start=1):
        text = _inline(item)
        if ordered:
            items.append(raw.types.PageListOrderedItemText(text=text, num=str(index)))
        else:
            items.append(raw.types.PageListItemText(text=text))
    if ordered:
        return raw.types.PageBlockOrderedList(items=items, start=1, type="1")
    return raw.types.PageBlockList(items=items)


def _table_block(node: Tag):
    rows = []
    for tr in node.find_all("tr"):
        cells = []
        for cell in tr.find_all(["th", "td"], recursive=False):
            cells.append(
                raw.types.PageTableCell(text=_inline(cell), header=cell.name == "th")
            )
        if cells:
            rows.append(raw.types.PageTableRow(cells=cells))
    return raw.types.PageBlockTable(
        title=raw.types.TextPlain(text=""), rows=rows, bordered=True, striped=True
    )


def markdown_to_rich_blocks(text: str) -> list[Any]:
    """Convert the AI's GFM-like Markdown into Telegram PageBlock objects."""
    rendered = markdown.markdown(
        text.expandtabs(4), extensions=["fenced_code", "tables", "sane_lists", "nl2br"]
    )
    soup = BeautifulSoup(rendered, "html.parser")
    blocks: list[Any] = []
    for node in soup.children:
        if isinstance(node, NavigableString):
            if str(node).strip():
                blocks.append(raw.types.PageBlockParagraph(text=_inline(node)))
            continue
        name = node.name.lower()
        if name == "h1":
            blocks.append(raw.types.PageBlockTitle(text=_inline(node)))
        elif name == "h2":
            blocks.append(raw.types.PageBlockHeader(text=_inline(node)))
        elif name in {"h3", "h4", "h5", "h6"}:
            blocks.append(raw.types.PageBlockSubheader(text=_inline(node)))
        elif name == "pre":
            code = node.find("code")
            classes = code.get("class", []) if code else []
            language = next(
                (
                    item.removeprefix("language-")
                    for item in classes
                    if item.startswith("language-")
                ),
                "",
            )
            blocks.append(
                raw.types.PageBlockPreformatted(
                    text=raw.types.TextPlain(text=node.get_text()), language=language
                )
            )
        elif name == "blockquote":
            blocks.append(
                raw.types.PageBlockBlockquote(
                    text=_inline(node), caption=raw.types.TextPlain(text="")
                )
            )
        elif name == "ul":
            blocks.append(_list_block(node, False))
        elif name == "ol":
            blocks.append(_list_block(node, True))
        elif name == "table":
            blocks.append(_table_block(node))
        elif name == "hr":
            blocks.append(raw.types.PageBlockDivider())
        else:
            blocks.append(raw.types.PageBlockParagraph(text=_inline(node)))
    return blocks or [raw.types.PageBlockParagraph(text=raw.types.TextPlain(text=text))]


async def send_rich_or_article(
    client, status_message, markdown_text: str, *, title: str
) -> str:
    """Send from the Pyrogram user account; use a web article only as fallback."""
    if len(markdown_text) <= RICH_MESSAGE_LIMIT:
        try:
            rich = InputRichMessage(blocks=markdown_to_rich_blocks(markdown_text))
            await client.send_rich_message(
                status_message.chat.id,
                rich,
                reply_to_message_id=(
                    status_message.reply_to_message.id
                    if status_message.reply_to_message
                    else None
                ),
            )
            await status_message.delete()
            return "rich"
        except Exception as error:  # noqa: BLE001 - unsupported MTProto feature must fall back
            logger.warning(
                "RichMessage unavailable, falling back to article: %s",
                type(error).__name__,
            )

    link = await save_to_local_web(title, markdown_text)
    await status_message.edit(
        f"📝 **{title} (Longread):**\n👉 {link}", disable_web_page_preview=False
    )
    return "article"
