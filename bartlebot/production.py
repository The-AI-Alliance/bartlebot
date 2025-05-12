import logging
from pathlib import Path
from rich.console import Console

from proscenium.core import Production
from proscenium.core import Character
from proscenium.core import Scene

from bartlebot.scenes import law_library

log = logging.getLogger(__name__)


class BartlebotProduction(Production):
    """
    BartlebotProduction"""

    def __init__(
        self,
        legal_channel_name: str,
        docs_per_dataset: int,
        enrichment_jsonl_file: Path,
        delay: float,
        neo4j_uri: str,
        neo4j_username: str,
        neo4j_password: str,
        milvus_uri: str,
        admin_channel_id: str,
        embedding_model_id: str,
        extraction_model: str,
        generator_model_id: str,
        control_flow_model_id: str,
        console: Console,
    ) -> None:

        self.law_library = law_library.LawLibrary(
            legal_channel_name,
            docs_per_dataset,
            enrichment_jsonl_file,
            delay,
            neo4j_uri,
            neo4j_username,
            neo4j_password,
            milvus_uri,
            admin_channel_id,
            embedding_model_id,
            extraction_model,
            generator_model_id,
            control_flow_model_id,
            console=console,
        )

    def scenes(self) -> list[Scene]:

        return [
            self.law_library,
        ]

    def places(
        self,
        channel_name_to_id: dict,
    ) -> dict[str, Character]:

        channel_id_to_handler = {}
        for scene in self.scenes():
            channel_id_to_handler.update(scene.places(channel_name_to_id))

        return channel_id_to_handler
