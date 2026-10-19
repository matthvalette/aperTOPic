from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from ...domain.models import PARLIAMENT_LANGUAGES
from ...services.documents import DocumentResolver
from ...services.similar import SimilarCasesService, SimilarOptions, SimilarOutcome
from ..dependencies import document_resolver, similar_service
from ..schemas import SimilarRequest

router = APIRouter(prefix="/similar", tags=["similar"])

MAX_UPLOAD_BYTES = 25_000_000


@router.post("", summary="Similar cases for an affair, a document link or text")
async def similar(
    body: SimilarRequest,
    service: SimilarCasesService = Depends(similar_service),
    resolver: DocumentResolver = Depends(document_resolver),
) -> SimilarOutcome:
    """Apertus lists the words titles on the document's subject contain, in every parliament language;
    OpenParlData finds the affairs; Jev rates how similar each is. Cases come with the labels people
    gave them (Curia Vista subject areas, cantonal schemes, PolitMonitor tags)."""
    try:
        if body.reference:
            document = await resolver.from_reference(
                body.reference, language=body.language, include_answer=body.include_answer
            )
        else:
            document = resolver.from_text(body.text or "", title=body.title)
        options = SimilarOptions(**body.model_dump(include=set(SimilarOptions.model_fields)))
        return await service.find(document, options)
    except KeyError as error:
        raise HTTPException(422, str(error).strip("'\"")) from None
    except LookupError as error:
        raise HTTPException(404, str(error)) from None
    except ValueError as error:
        raise HTTPException(422, str(error)) from None


@router.post("/upload", summary="Similar cases for an uploaded PDF, DOCX, HTML or text file")
async def similar_upload(
    file: UploadFile = File(...),
    title: str | None = Form(None),
    languages: str = Form(",".join(PARLIAMENT_LANGUAGES), description="Comma-separated language codes"),
    max_results: int = Form(10, ge=1, le=50),
    service: SimilarCasesService = Depends(similar_service),
    resolver: DocumentResolver = Depends(document_resolver),
) -> SimilarOutcome:
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File is larger than 25 MB")
    try:
        document = resolver.from_upload(data, filename=file.filename, content_type=file.content_type, title=title)
        wanted = [lang.strip() for lang in languages.split(",") if lang.strip()]
        options = SimilarOptions(languages=wanted or list(PARLIAMENT_LANGUAGES), max_results=max_results)
        return await service.find(document, options)
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
