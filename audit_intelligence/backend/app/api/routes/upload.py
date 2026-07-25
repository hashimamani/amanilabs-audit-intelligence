import uuid

from fastapi import APIRouter, UploadFile, File, HTTPException

from app.core.datasets import REQUIRED_FILES, UPLOADS_DIR
from app.api.schemas import UploadOut

router = APIRouter(prefix="/upload", tags=["upload"])


@router.post("", response_model=UploadOut)
async def upload_dataset(files: list[UploadFile] = File(...)):
    received = {f.filename: f for f in files}
    missing = [name for name in REQUIRED_FILES if name not in received]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Missing required file(s): {', '.join(missing)}. "
                   f"Expected exactly: {', '.join(REQUIRED_FILES)}",
        )

    dataset_id = uuid.uuid4().hex[:12]
    dataset_dir = UPLOADS_DIR / dataset_id
    dataset_dir.mkdir(parents=True, exist_ok=True)

    for name in REQUIRED_FILES:
        upload = received[name]
        contents = await upload.read()
        (dataset_dir / name).write_bytes(contents)

    return UploadOut(dataset_id=dataset_id, files_received=REQUIRED_FILES)
