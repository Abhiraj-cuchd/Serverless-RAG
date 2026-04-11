import json
import logging
import boto3
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger(__name__)

TITAN_MODEL_ID = "amazon.titan-embed-text-v2:0"


def get_bedrock_client(region: str) -> boto3.client:
    """Create and return a Bedrock runtime client."""
    return boto3.client("bedrock-runtime", region_name=region)


def embed_text(text: str, region: str) -> list[float]:
    """
    Send a single piece of text to Amazon Titan Embeddings.
    Returns a list of 1536 floats representing the text as a vector.
    """
    try:
        client = get_bedrock_client(region)
        body = json.dumps({"inputText": text})

        response = client.invoke_model(
            modelId=TITAN_MODEL_ID,
            body=body,
            contentType="application/json",
            accept="application/json"
        )

        result = json.loads(response["body"].read())
        embedding = result["embedding"]

        logger.info(f"Generated embedding with {len(embedding)} dimensions")
        return embedding

    except (BotoCoreError, ClientError) as e:
        raise RuntimeError(f"Failed to generate embedding from Titan: {e}")


def embed_many(texts: list[str], region: str) -> list[list[float]]:
    """
    Embed a list of texts one by one.
    Returns a list of vectors in the same order as the input texts.
    """
    embeddings = []
    for i, text in enumerate(texts):
        embedding = embed_text(text, region)
        embeddings.append(embedding)
        logger.info(f"Embedded chunk {i + 1} of {len(texts)}")
    return embeddings