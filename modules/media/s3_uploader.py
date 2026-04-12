#!/usr/bin/env python3
"""
S3 upload utility for videopipeline.
Uploads local files to MinIO/S3 and returns public URL.
"""
import boto3
import os
from pathlib import Path


_s3_config = None


def configure(config: dict = None):
    """Update S3 config from a config dict. Call before get_s3_client()."""
    global _s3_config
    if config is None:
        return
    _s3_config = {
        'endpoint': config.get('endpoint', 'https://s3.trachanhtv.top'),
        'access_key': config.get('access_key', 'minio-admin'),
        'secret_key': config.get('secret_key', 'minio-password-change-me'),
        'bucket': config.get('bucket', 'videopipeline'),
        'region': config.get('region', 'us-east-1'),
        'public_url_base': config.get('public_url_base', 'https://s3.trachanhtv.top/videopipeline'),
    }


def get_s3_config():
    """Load S3 config from global config dict or environment variables."""
    if _s3_config is not None:
        return _s3_config
    return {
        'endpoint': os.environ.get('S3_ENDPOINT', 'https://s3.trachanhtv.top'),
        'access_key': os.environ.get('S3_ACCESS_KEY', 'minio-admin'),
        'secret_key': os.environ.get('S3_SECRET_KEY', 'minio-password-change-me'),
        'bucket': os.environ.get('S3_BUCKET', 'videopipeline'),
        'region': os.environ.get('S3_REGION', 'us-east-1'),
        'public_url_base': os.environ.get('S3_PUBLIC_URL_BASE', 'https://s3.trachanhtv.top/videopipeline'),
    }


def get_s3_client():
    cfg = get_s3_config()
    return boto3.client(
        's3',
        endpoint_url=cfg['endpoint'],
        aws_access_key_id=cfg['access_key'],
        aws_secret_access_key=cfg['secret_key'],
        region_name=cfg['region']
    )


def upload_file(file_path: str, key_prefix: str = "uploads") -> str:
    """
    Upload a file to S3 and return public URL.
    
    Args:
        file_path: Local file path
        key_prefix: Prefix for the S3 key (e.g. 'images', 'audio', 'video')
    
    Returns:
        Public URL of uploaded file
    """
    cfg = get_s3_config()
    file_path = Path(file_path)
    key = f"{key_prefix}/{file_path.name}"
    
    client = get_s3_client()
    client.upload_file(
        str(file_path),
        cfg['bucket'],
        key,
        ExtraArgs={"ContentType": _guess_content_type(file_path.suffix)}
    )
    
    return f"{cfg['public_url_base']}/{key}"


def _guess_content_type(ext: str) -> str:
    """Guess content type from file extension."""
    types = {
        '.mp4': 'video/mp4',
        '.mp3': 'audio/mpeg',
        '.wav': 'audio/wav',
        '.png': 'image/png',
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.webp': 'image/webp',
        '.json': 'application/json',
        '.txt': 'text/plain',
    }
    return types.get(ext.lower(), 'application/octet-stream')


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <file_path> [prefix]")
        sys.exit(1)
    
    path = sys.argv[1]
    prefix = sys.argv[2] if len(sys.argv) > 2 else "test"
    
    url = upload_file(path, prefix)
    print(f"Uploaded: {url}")