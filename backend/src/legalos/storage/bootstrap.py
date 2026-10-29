"""Create the documents bucket if it does not exist (local development).

Usage: python -m legalos.storage.bootstrap
In production the bucket is created by infrastructure code with encryption, versioning
and public access blocked.
"""

import time

from botocore.exceptions import ClientError, EndpointConnectionError
from botocore.exceptions import ConnectionClosedError as BotoConnectionClosedError

from legalos.config import get_settings
from legalos.storage.s3 import _client


def main(wait_seconds: int = 60) -> None:
    settings = get_settings()
    client = _client(public=False)
    deadline = time.monotonic() + wait_seconds
    # The storage container may still be starting.
    while True:
        try:
            client.list_buckets()
            break
        except (EndpointConnectionError, BotoConnectionClosedError):
            if time.monotonic() > deadline:
                raise
            time.sleep(2)
    try:
        client.head_bucket(Bucket=settings.storage_bucket)
        print(f"Bucket {settings.storage_bucket} already exists.")
    except ClientError:
        if settings.storage_region == "us-east-1":
            client.create_bucket(Bucket=settings.storage_bucket)
        else:
            # AWS requires the region to be named for buckets outside us-east-1.
            client.create_bucket(
                Bucket=settings.storage_bucket,
                CreateBucketConfiguration={"LocationConstraint": settings.storage_region},  # type: ignore[typeddict-item]
            )
        print(f"Created bucket {settings.storage_bucket}.")
    # Browsers upload files straight to storage with signed URLs; only our own web
    # origins may do so.
    client.put_bucket_cors(
        Bucket=settings.storage_bucket,
        CORSConfiguration={
            "CORSRules": [
                {
                    "AllowedOrigins": settings.allowed_origins,
                    "AllowedMethods": ["PUT", "GET"],
                    "AllowedHeaders": ["content-type"],
                    "MaxAgeSeconds": 3000,
                }
            ]
        },
    )


if __name__ == "__main__":
    main()
