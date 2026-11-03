"""Upload/download endpoints for the local-folder storage backend only (see local.py).

Like S3 signed URLs, a valid, unexpired token is the only credential: it is issued by
the API to an authenticated member of the firm that owns the key.
"""

from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse

from legalos.config import get_settings
from legalos.documents.service import MAX_UPLOAD_BYTES
from legalos.storage import local

router = APIRouter(prefix="/api/storage", tags=["storage"], include_in_schema=False)


def _claims(token: str, operation: str) -> dict[str, str]:
    if get_settings().storage_backend != "local":
        raise HTTPException(404)
    try:
        return local.verify(token, operation)
    except local.InvalidTokenError as e:
        raise HTTPException(403, "invalid_or_expired_link") from e


@router.put("/objects/{token}", status_code=200)
async def upload(token: str, request: Request) -> Response:
    claims = _claims(token, "put")
    if request.headers.get("content-type") != claims["ct"]:
        raise HTTPException(403, "content_type_mismatch")
    path = local.path_for(claims["key"])
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    size = 0
    with tmp.open("wb") as out:
        async for chunk in request.stream():
            size += len(chunk)
            # Stop early; the API also checks the size when the upload is completed.
            if size > MAX_UPLOAD_BYTES + 1:
                out.close()
                tmp.unlink(missing_ok=True)
                raise HTTPException(413, "file_too_large")
            out.write(chunk)
    tmp.replace(path)
    return Response(status_code=200)


@router.get("/objects/{token}")
def download(token: str) -> FileResponse:
    claims = _claims(token, "get")
    path = local.path_for(claims["key"])
    if not path.is_file():
        raise HTTPException(404)
    headers = {
        # Allow the app's own pages to show the file in a frame (document viewer).
        "X-Frame-Options": "SAMEORIGIN",
        "Content-Security-Policy": "frame-ancestors 'self'",
    }
    if claims.get("fn"):
        headers["Content-Disposition"] = f"inline; filename*=UTF-8''{quote(claims['fn'])}"
    return FileResponse(
        path, media_type=claims.get("ct") or "application/octet-stream", headers=headers
    )
