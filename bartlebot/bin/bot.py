#!/usr/bin/env python3

import os
import sys
import logging
import typer
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from proscenium.verbs.display import header
from proscenium.bin import production_from_config
from proscenium.interfaces.slack import slack_main

logging.basicConfig(
    stream=sys.stdout,
    format="%(asctime)s  %(levelname)-8s %(name)s: %(message)s",
    level=logging.WARNING,
)

default_config_path = Path("bartlebot.yml")

app = typer.Typer(help="Bartlebot")

log = logging.getLogger(__name__)


@app.command(help="Build all prerequisite resources for the law library.")
def build(
    config_file: Path = typer.Option(
        default=default_config_path,
        help="Path to the configuration file.",
    ),
    verbose: bool = False,
):
    console = Console()
    sub_console = None

    if verbose:
        log.setLevel(logging.INFO)
        logging.getLogger("proscenium").setLevel(logging.INFO)
        logging.getLogger("bartlebot").setLevel(logging.INFO)
        sub_console = console

    console.print(header())

    production, config = production_from_config(
        config_file, os.environ.get, sub_console=sub_console
    )

    console.print("Building all resources")
    production.prepare_props()
    console.print("Done.)")

    production.curtain()


@app.command(
    help="""Ask a legal question using the knowledge graph and entity resolver props."""
)
def handle(
    loop: bool = False,
    question: str = None,
    config_file: Path = typer.Option(
        default=default_config_path,
        help="Path to the configuration file.",
    ),
    verbose: bool = False,
):
    console = Console()
    sub_console = None

    if verbose:
        log.setLevel(logging.INFO)
        logging.getLogger("proscenium").setLevel(logging.INFO)
        logging.getLogger("bartlebot").setLevel(logging.INFO)
        sub_console = console

    console.print(header())

    from bartlebot.scenes.law_library.query_handler import user_prompt
    from bartlebot.scenes.law_library.query_handler import default_question

    production, config = production_from_config(
        config_file, os.environ.get, sub_console=sub_console
    )

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


@app.command(help="""Attach Bartlebot to the configured Slack App.""")
def slack(
    config_file: Path = typer.Option(
        default_config_path,
        help="The name of the Proscenium YAML configuration file.",
    ),
    verbose: bool = False,
):

    console = Console()
    sub_console = None

    if verbose:
        log.setLevel(logging.INFO)
        logging.getLogger("proscenium").setLevel(logging.INFO)
        logging.getLogger("bartlebot").setLevel(logging.INFO)
        sub_console = console

    console.print(header())

    production, config = production_from_config(
        config_file, os.environ.get, sub_console
    )

    console.print("Preparing props...")
    production.prepare_props()
    console.print("Props are up-to-date.")

    slack_main(production, config, console)


if __name__ == "__main__":

    app()
