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
        client.create_bucket(Bucket=settings.storage_bucket)
        print(f"Created bucket {settings.storage_bucket}.")


if __name__ == "__main__":
    main()
