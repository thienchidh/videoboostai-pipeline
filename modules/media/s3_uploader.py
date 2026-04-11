#!/usr/bin/env python3
"""
S3 upload utility for videopipeline.
Uploads local files to MinIO/S3 and returns public URL.
"""
import boto3
import os
from pathlib import Path

# S3 Config from k8s secret
S3_ENDPOINT = "https://s3.trachanhtv.top"
S3_ACCESS_KEY = "minio-admin"
S3_SECRET_KEY = "minio-password-change-me"
S3_REGION = "us-east-1"
S3_BUCKET = "videopipeline"

# Public URL base (Cloudflare CDN)
PUBLIC_URL_BASE = "https://s3.trachanhtv.top/videopipeline"


def get_s3_client():
    return boto3.client(
        's3',
        endpoint_url=S3_ENDPOINT,
        aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_SECRET_KEY,
        region_name=S3_REGION
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
    file_path = Path(file_path)
    key = f"{key_prefix}/{file_path.name}"
    
    client = get_s3_client()
    client.upload_file(
        str(file_path),
        S3_BUCKET,
        key,
        ExtraArgs={"ContentType": _guess_content_type(file_path.suffix)}
    )
    
    return f"{PUBLIC_URL_BASE}/{key}"


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