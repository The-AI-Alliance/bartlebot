from typing import Dict, Optional, Callable

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
        admin_channel_id: str,
        legal_channel_name: str,
        docs_per_dataset: int,
        enrichment_jsonl_file: Path,
        delay: float,
        neo4j_uri: str,
        neo4j_username: str,
        neo4j_password: str,
        milvus_uri: str,
        embedding_model_id: str,
        extraction_model: str,
        generator_model_id: str,
        control_flow_model_id: str,
        console: Console,
    ) -> None:
        super().__init__(admin_channel_id, console)

        self.law_library = law_library.LawLibrary(
            admin_channel_id,
            legal_channel_name,
            docs_per_dataset,
            enrichment_jsonl_file,
            delay,
            neo4j_uri,
            neo4j_username,
            neo4j_password,
            milvus_uri,
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


def make_production(
    config: Dict,
    get_secret: Callable[[str, str], str],
    console: Optional[Console] = None,
) -> BartlebotProduction:

    production_config = config.get("production", {})

    inference_config = config.get("inference", {})
    slack_config = config.get("slack", {})
    graph_config = config.get("graph", {})
    vectors_config = config.get("vectors", {})
    enrichments_config = config.get("enrichments", {})
    scenes_config = production_config.get("scenes", {})
    law_library_config = scenes_config.get("law_library", {})

    return BartlebotProduction(
        slack_config.get("admin_channel", get_secret("SLACK_ADMIN_CHANNEL_ID")),
        law_library_config["channel"],
        enrichments_config["docs_per_dataset"],
        Path(enrichments_config["jsonl_file"]),
        inference_config["delay"],
        graph_config.get("neo4j_uri", get_secret("NEO4J_URI")),
        graph_config.get("neo4j_username", get_secret("NEO4J_USERNAME")),
        graph_config.get("neo4j_password", get_secret("NEO4J_PASSWORD")),
        vectors_config["milvus_uri"],
        vectors_config["embedding_model"],
        inference_config["extraction_model"],
        inference_config["generator_model"],
        inference_config["control_flow_model"],
        console=console,
    )
