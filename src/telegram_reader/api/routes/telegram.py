from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from ...security import UNTRUSTED_CONTENT_NOTICE
from ..auth import AuthContext, require_reader_auth
from ..schemas import (
    ConfirmMarkReadRequest,
    ContextRequest,
    PrepareMarkReadRequest,
    SearchChannelsRequest,
    SearchPrivateRequest,
    SurfaceCommitRequest,
    UnreadRequest,
    as_utc_iso,
)


router = APIRouter(prefix="/v1", tags=["telegram-reader"])


def runtime(request: Request):
    return request.app.state.telegram_reader


def reader_error(error: Exception) -> HTTPException:
    if isinstance(error, NotImplementedError):
        return HTTPException(status_code=501, detail=str(error))
    if isinstance(error, LookupError):
        return HTTPException(status_code=404, detail=str(error))
    if isinstance(error, PermissionError):
        return HTTPException(status_code=409, detail=str(error))
    if isinstance(error, ValueError):
        return HTTPException(status_code=422, detail=str(error))
    if isinstance(error, RuntimeError) and "not connected" in str(error):
        return HTTPException(status_code=503, detail="Telegram client is not connected")
    return HTTPException(status_code=502, detail="Telegram Reader operation failed")


@router.get("/status")
async def status_route(request: Request, _auth: AuthContext = Depends(require_reader_auth)):
    return runtime(request).status()


@router.post("/telegram/unread")
async def unread_route(body: UnreadRequest, request: Request, auth: AuthContext = Depends(require_reader_auth)):
    try:
        result = await runtime(request).unread.unread(
            auth.owner_id, body.mode, as_utc_iso(body.since), body.max_people, body.max_messages_per_person,
        )
        return {**result, "timezone": runtime(request).settings.timezone, "untrusted_content_notice": UNTRUSTED_CONTENT_NOTICE}
    except Exception as error:
        raise reader_error(error) from error


@router.post("/telegram/unread/commit", include_in_schema=False)
async def unread_commit_route(body: SurfaceCommitRequest, request: Request, auth: AuthContext = Depends(require_reader_auth)):
    return await runtime(request).unread.commit(auth.owner_id, body.batch_id)


@router.post("/telegram/search/private")
async def search_private_route(body: SearchPrivateRequest, request: Request, _auth: AuthContext = Depends(require_reader_auth)):
    try:
        result = await runtime(request).search.search_private(
            body.query, body.person, body.mode, as_utc_iso(body.date_from), as_utc_iso(body.date_to),
            body.media_type, body.limit, body.cursor,
        )
        return {**result, "timezone": runtime(request).settings.timezone, "untrusted_content_notice": UNTRUSTED_CONTENT_NOTICE}
    except Exception as error:
        raise reader_error(error) from error


@router.post("/telegram/search/channels")
async def search_channels_route(body: SearchChannelsRequest, request: Request, _auth: AuthContext = Depends(require_reader_auth)):
    try:
        result = await runtime(request).search.search_channels(
            body.query, body.mode, body.scope, body.channel_names,
            as_utc_iso(body.date_from), as_utc_iso(body.date_to), body.limit, body.cursor,
            body.include_context, body.semantic_top_k, body.confirm_public_global,
        )
        return {**result, "timezone": runtime(request).settings.timezone, "untrusted_content_notice": UNTRUSTED_CONTENT_NOTICE}
    except Exception as error:
        raise reader_error(error) from error


@router.post("/telegram/context")
async def context_route(body: ContextRequest, request: Request, _auth: AuthContext = Depends(require_reader_auth)):
    try:
        return await runtime(request).search.context(body.peer_id, body.message_id, body.before, body.after)
    except Exception as error:
        raise reader_error(error) from error


@router.post("/telegram/read/prepare")
async def prepare_read_route(body: PrepareMarkReadRequest, request: Request, auth: AuthContext = Depends(require_reader_auth)):
    try:
        return await runtime(request).mark_read.prepare(auth.owner_id, body.person, body.max_message_id)
    except Exception as error:
        raise reader_error(error) from error


@router.post("/telegram/read/confirm")
async def confirm_read_route(body: ConfirmMarkReadRequest, request: Request, auth: AuthContext = Depends(require_reader_auth)):
    try:
        return await runtime(request).mark_read.confirm(auth.owner_id, body.confirmation_token)
    except Exception as error:
        raise reader_error(error) from error
