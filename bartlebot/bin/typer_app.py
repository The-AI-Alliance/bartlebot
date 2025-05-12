from typing import Optional

import typer
import os
import logging
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from neo4j import GraphDatabase

from bartlebot.scenes.law_library import DocumentEnrichments
from bartlebot.scenes.law_library import docs
from bartlebot.scenes.law_library.kg import CaseLawKnowledgeGraph
from bartlebot.scenes.law_library.kg import display_knowledge_graph
from bartlebot.scenes.law_library.entity_resolvers import EntityResolvers
from bartlebot.scenes.law_library.query_handler import LawLibrarian
from bartlebot.scenes.law_library.query_handler import user_prompt
from bartlebot.scenes.law_library.query_handler import default_question

from bartlebot.bin import production_from_config

app = typer.Typer(
    help="""
Graph extraction and question answering with GraphRAG on caselaw.
"""
)

default_embedding_model_id = "all-MiniLM-L6-v2"

default_neo4j_uri = "bolt://localhost:7687"
default_neo4j_username = "neo4j"
default_neo4j_password = "password"

neo4j_help = f"""Uses Neo4j at NEO4J_URI, with a default of {default_neo4j_uri}, and
auth credentials NEO4J_USERNAME and NEO4J_PASSWORD, with defaults of
{default_neo4j_username} and {default_neo4j_password}."""

console = Console()

log = logging.getLogger(__name__)


@app.command(help="Build all prerequisite resources for the law library.")
def build(
    config_file: Path = typer.Option(
        default=Path("bartlebot.yaml"),
        help="Path to the configuration file.",
    ),
    verbose: bool = False,
):
    sub_console = None
    if verbose:
        logging.getLogger("proscenium").setLevel(logging.INFO)
        logging.getLogger("demo").setLevel(logging.INFO)
        sub_console = Console()

    production, config = production_from_config(config_file, sub_console=sub_console)

    console.print("Building all resources")
    production.prepare_props()
    console.print("Done.)")


@app.command(
    help=f"""Ask a legal question using the knowledge graph and entity resolver established in the previous steps.
{neo4j_help}"""
)
def handle(
    loop: bool = False,
    question: str = None,
    config_file: Path = typer.Option(
        default=Path("bartlebot.yaml"),
        help="Path to the configuration file.",
    ),
    verbose: bool = False,
):
    sub_console = None
    if verbose:
        logging.getLogger("proscenium").setLevel(logging.INFO)
        logging.getLogger("demo").setLevel(logging.INFO)
        sub_console = Console()

    production, config = production_from_config(config_file, sub_console=sub_console)

    while True:

        if question is None:
            q = Prompt.ask(
                user_prompt,
                default=default_question,
            )
        else:
            q = question

        console.print(Panel(q, title="Question"))

        for channel_id, answer in production.law_library.law_librarian.handle(
            None, None, q
        ):
            console.print(Panel(answer, title="Answer"))

        if loop:
            question = None
        else:
            break

    production.curtain()
