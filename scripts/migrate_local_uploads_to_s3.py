"""Preserve old imported uploads in S3 without overwriting different objects.

Run with --apply to copy missing objects; local files are never deleted here.
No credentials, object keys, file names, or contents are printed.
"""
import argparse
import hashlib
import mimetypes
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from botocore.exceptions import ClientError
from app.core.config import Settings
from app.core.object_storage import require_bucket, s3_client


def digest(stream):
    result = hashlib.sha256()
    for chunk in iter(lambda: stream.read(65536), b''):
        result.update(chunk)
    return result.digest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    settings = Settings()
    require_bucket(settings)
    client = s3_client(settings)
    root = (ROOT / 'storage' / 'imported-uploads').resolve()
    files = [p for p in root.rglob('*') if p.is_file()]
    verified = 0
    for path in files:
        if not path.resolve().is_relative_to(root):
            raise ValueError('Local upload resolves outside the expected storage directory')
        key = path.relative_to(root).as_posix()
        with path.open('rb') as source:
            expected = digest(source)
        try:
            remote = client.get_object(Bucket=settings.aws_bucket_name, Key=key)['Body']
        except ClientError as error:
            if error.response.get('Error', {}).get('Code') not in ('NoSuchKey', '404', 'NotFound'):
                raise
            if not args.apply:
                print('A local file is missing in S3; rerun with --apply.')
                continue
            with path.open('rb') as source:
                client.put_object(Bucket=settings.aws_bucket_name, Key=key, Body=source,
                    ContentType=mimetypes.guess_type(path.name)[0] or 'application/octet-stream',
                    IfNoneMatch='*')
            remote = client.get_object(Bucket=settings.aws_bucket_name, Key=key)['Body']
        try:
            if digest(remote) != expected:
                raise ValueError('An S3 object differs from the local file; nothing was overwritten or deleted')
        finally:
            remote.close()
        verified += 1
    print(f'Local files: {len(files)}; exact S3 copies verified: {verified}. Local files retained.')
    if verified != len(files):
        raise SystemExit(1)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('Storage migration stopped:', type(error).__name__, '(private details withheld)')
        raise SystemExit(1)
