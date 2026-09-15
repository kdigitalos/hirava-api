"""Private legacy-format object keys, shared by migrated upload consumers."""
from pathlib import PurePosixPath
from botocore.exceptions import ClientError

from fastapi import HTTPException

from app.core.object_storage import s3_client, require_bucket


def safe_key(key):
    parts = PurePosixPath(key).parts
    if not parts or key.startswith('/') or '\\' in key or ':' in key or any(ord(c) < 32 for c in key) or any(p in {'', '.', '..'} for p in key.split('/')):
        raise HTTPException(400, 'Invalid file path')
    return key


def save(settings, key, content, mime):
    key = safe_key(key)
    require_bucket(settings)
    try:
        s3_client(settings).put_object(Bucket=settings.aws_bucket_name, Key=key, Body=content, ContentType=mime)
    except Exception:
        raise HTTPException(503, 'Configured object storage upload failed') from None
    return key


def remove(settings, key):
    safe_key(key)
    require_bucket(settings)
    s3_client(settings).delete_object(Bucket=settings.aws_bucket_name, Key=key)


def open_file(settings, key):
    safe_key(key)
    require_bucket(settings)
    try:
        result = s3_client(settings).get_object(Bucket=settings.aws_bucket_name, Key=key)
        return result['Body'], result.get('ContentType', 'application/octet-stream')
    except ClientError as error:
        if error.response.get('Error', {}).get('Code') in ('NoSuchKey', '404', 'NotFound'):
            raise HTTPException(404, 'File is unavailable') from None
        raise HTTPException(503, 'Object storage is temporarily unavailable') from None
    except Exception:
        raise HTTPException(503, 'Object storage is temporarily unavailable') from None
