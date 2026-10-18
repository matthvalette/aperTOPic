import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from ...services.classify import ClassificationOutcome, ClassificationService, CustomTopic
from ...services.documents import DocumentResolver
from ..dependencies import classification_service, document_resolver
from ..schemas import ClassifyRequest

router = APIRouter(prefix="/classify", tags=["classify"])

MAX_UPLOAD_BYTES = 25_000_000


@router.post("", summary="Topic probabilities for an affair, a document link or text")
async def classify(
    body: ClassifyRequest,
    service: ClassificationService = Depends(classification_service),
    resolver: DocumentResolver = Depends(document_resolver),
) -> ClassificationOutcome:
    try:
        if body.reference:
            document = await resolver.from_reference(
                body.reference, language=body.language, include_answer=body.include_answer
            )
        else:
            document = resolver.from_text(body.text or "", title=body.title)
        return await service.classify(document, body.taxonomies, body.custom_topics, body.threshold)
    except KeyError as error:
        raise HTTPException(422, str(error).strip("'\"")) from None
    except LookupError as error:
        raise HTTPException(404, str(error)) from None
    except ValueError as error:
        raise HTTPException(422, str(error)) from None


@router.post("/upload", summary="Topic probabilities for an uploaded PDF, DOCX, HTML or text file")
async def classify_upload(
    file: UploadFile = File(...),
    taxonomies: str = Form("curia_subject_areas", description="Comma-separated label set ids"),
    custom_topics: str = Form("", description='JSON list, e.g. [{"name": "Digitalisierung"}]'),
    title: str | None = Form(None),
    threshold: float | None = Form(None),
    service: ClassificationService = Depends(classification_service),
    resolver: DocumentResolver = Depends(document_resolver),
) -> ClassificationOutcome:
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File is larger than 25 MB")
    try:
        topics = [CustomTopic(**t) for t in json.loads(custom_topics)] if custom_topics.strip() else []
        document = resolver.from_upload(data, filename=file.filename, content_type=file.content_type, title=title)
        ids = [t.strip() for t in taxonomies.split(",") if t.strip()]
        return await service.classify(document, ids, topics, threshold)
    except KeyError as error:
        raise HTTPException(422, str(error).strip("'\"")) from None
    except (ValueError, json.JSONDecodeError) as error:
        raise HTTPException(422, str(error)) from None
