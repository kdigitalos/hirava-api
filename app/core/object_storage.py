"""Private S3 storage for native FastAPI documents."""
from fastapi import HTTPException


def require_bucket(settings):
    if not settings.aws_bucket_name:
        raise HTTPException(503, "S3 storage is not configured")


def s3_client(settings):
    import boto3
    from botocore.config import Config
    credentials = {}
    if settings.aws_access_key_id.get_secret_value():
        credentials = {
            "aws_access_key_id": settings.aws_access_key_id.get_secret_value(),
            "aws_secret_access_key": settings.aws_secret_access_key.get_secret_value(),
        }
        if settings.aws_session_token.get_secret_value():
            credentials["aws_session_token"] = settings.aws_session_token.get_secret_value()
    return boto3.client("s3", region_name=settings.aws_region or None,
        config=Config(connect_timeout=10, read_timeout=30, retries={"max_attempts": 2}), **credentials)


def object_key(settings, storage_key):
    return f"core/{settings.customer_id}/{storage_key}"


def upload(settings, storage_key, file):
    require_bucket(settings)
    try:
        s3_client(settings).upload_fileobj(file, settings.aws_bucket_name, object_key(settings, storage_key),
                                         ExtraArgs={"ContentType": "application/octet-stream"})
    except Exception:
        raise HTTPException(503, "Object storage upload failed") from None


def download(settings, storage_key):
    require_bucket(settings)
    try:
        return s3_client(settings).get_object(Bucket=settings.aws_bucket_name,
                                             Key=object_key(settings, storage_key))["Body"]
    except Exception:
        raise HTTPException(503, "Document content temporarily unavailable") from None
