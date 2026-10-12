import os, time
import boto3
from botocore.client import Config
from botocore.exceptions import ClientError, EndpointConnectionError

_access_key = os.environ.get("S3_ACCESS_KEY", "dummy")
_secret_key = os.environ.get("S3_SECRET_KEY", "dummy")
_config = Config(signature_version="s3v4")

# cliente "de verdade": faz upload/download/delete, fala com o SeaweedFS
# pelo nome interno do Docker (ex: http://seaweedfs:8333)
client = boto3.client(
    "s3",
    endpoint_url=os.environ["S3_ENDPOINT"],
    aws_access_key_id=_access_key,
    aws_secret_access_key=_secret_key,
    region_name="us-east-1",
    config=_config,
)

# cliente só para ASSINAR urls públicas (nunca faz chamada de rede sozinho) --
# aponta pro endereço que o navegador do usuário, fora do Docker, consegue
# resolver (ex: http://localhost:8333). Sem isso, o link do e-mail quebra.
_public_client = boto3.client(
    "s3",
    endpoint_url=os.environ["S3_PUBLIC_ENDPOINT"],
    aws_access_key_id=_access_key,
    aws_secret_access_key=_secret_key,
    region_name="us-east-1",
    config=_config,
)

BUCKET_UPLOADS = os.environ["BUCKET_UPLOADS"]
BUCKET_CONVERTED = os.environ["BUCKET_CONVERTED"]
URL_EXPIRES = int(os.environ.get("PRESIGNED_URL_EXPIRES", 86400))

def ensure_buckets(retries: int = 10, delay: int = 3):
    """Cria os buckets se não existirem. Tenta de novo caso o storage ainda esteja subindo."""
    for attempt in range(retries):
        try:
            for bucket in (BUCKET_UPLOADS, BUCKET_CONVERTED):
                try:
                    client.create_bucket(Bucket=bucket)
                except ClientError:
                    pass  # já existe
            return
        except EndpointConnectionError:
            time.sleep(delay)
    raise RuntimeError("Não foi possível conectar ao object storage")

def upload_bytes(bucket: str, object_name: str, data: bytes):
    client.put_object(Bucket=bucket, Key=object_name, Body=data)

def upload_file(bucket: str, object_name: str, file_path: str):
    client.upload_file(file_path, bucket, object_name)

def download_file(bucket: str, object_name: str, file_path: str):
    client.download_file(bucket, object_name, file_path)

def delete_object(bucket: str, object_name: str):
    client.delete_object(Bucket=bucket, Key=object_name)

def public_url(bucket: str, object_name: str) -> str:
    """Gera uma URL pré-assinada (RF04) válida por PRESIGNED_URL_EXPIRES segundos,
    já apontando para o endereço público (não o interno do Docker)."""
    return _public_client.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": object_name},
        ExpiresIn=URL_EXPIRES,
    )