from fastapi import HTTPException
from docx.image.image import Image
from docx.image.exceptions import InvalidImageStreamError, UnrecognizedImageError, UnexpectedEndOfFileError
from sqlalchemy import select

from ..models import DocumentImage, DocumentWorkspace
from .richtext import image_ids

MAX_IMAGE_BYTES = 10 * 1024 * 1024
IMAGE_TYPES = {'image/png', 'image/jpeg'}


def image_dimensions(data):
    import pymupdf

    try:
        header = Image.from_blob(data)
        if header.content_type not in IMAGE_TYPES or not 0 < header.px_width * header.px_height <= 24_000_000:
            raise ValueError()
        decoded = pymupdf.Pixmap(data)
        if (decoded.width, decoded.height) != (header.px_width, header.px_height):
            raise ValueError()
    except (InvalidImageStreamError, UnrecognizedImageError, UnexpectedEndOfFileError, ValueError, RuntimeError) as error:
        raise HTTPException(422, '请选择可读取的 PNG 或 JPEG 图片，像素总数不超过 2400 万') from error
    return header.content_type, header.px_width, header.px_height


def workspace_image_ids(db, workspace, content):
    ids = image_ids(content)
    if not ids:
        return []
    images = db.execute(select(DocumentImage.id, DocumentWorkspace.document_id, DocumentImage.workspace_id)
                        .join(DocumentWorkspace, DocumentWorkspace.id == DocumentImage.workspace_id)
                        .where(DocumentImage.id.in_(ids))).all()
    allowed = {image_id for image_id, document_id, workspace_id in images
               if workspace_id == workspace.id or (workspace.document_id and document_id == workspace.document_id)}
    if allowed != set(ids):
        raise HTTPException(422, '正文含有未上传至此软需的图片，请重新插入')
    return ids


def version_images(db, version):
    ids = version.provenance.get('image_ids', [])
    if not ids:
        return {}
    images = db.scalars(select(DocumentImage).join(DocumentWorkspace, DocumentImage.workspace_id == DocumentWorkspace.id)
                        .where(DocumentImage.id.in_(ids), DocumentWorkspace.document_id == version.document_id))
    return {image.id: image for image in images}
