import boto3
from botocore.exceptions import BotoCoreError, ClientError

from config import (
    AWS_REGION,
    S3_BUCKET_NAME,
    S3_PRESIGNED_URL_EXPIRE_SECONDS,
)


def _get_s3_client():
    return boto3.client("s3", region_name=AWS_REGION)


def upload_file_to_s3(
    local_path: str,
    s3_key: str,
    content_type: str,
) -> None:
    if not S3_BUCKET_NAME:
        raise RuntimeError("S3_BUCKET_NAME is not configured")

    s3 = _get_s3_client()

    try:
        s3.upload_file(
            local_path,
            S3_BUCKET_NAME,
            s3_key,
            ExtraArgs={"ContentType": content_type},
        )
    except (BotoCoreError, ClientError) as e:
        raise RuntimeError(f"Failed to upload file to S3: {e}") from e


def create_presigned_download_url(s3_key: str) -> str:
    if not S3_BUCKET_NAME:
        raise RuntimeError("S3_BUCKET_NAME is not configured")

    s3 = _get_s3_client()

    try:
        return s3.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": S3_BUCKET_NAME,
                "Key": s3_key,
            },
            ExpiresIn=S3_PRESIGNED_URL_EXPIRE_SECONDS,
        )
    except (BotoCoreError, ClientError) as e:
        raise RuntimeError(f"Failed to create S3 download URL: {e}") from e