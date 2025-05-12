#!/usr/bin/env python3

import os
import sys
import logging
import typer
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from proscenium.admin import Admin

from proscenium.interfaces.slack import (
    get_slack_auth,
    channel_table,
    bot_user_id,
    places_table,
    channel_maps,
    make_slack_listener,
    connect,
    send_curtain_up,
    listen,
    send_curtain_down,
    shutdown,
)

from proscenium.verbs.display import header

from bartlebot.bin import production_from_config

logging.basicConfig(
    stream=sys.stdout,
    format="%(asctime)s  %(levelname)-8s %(name)s: %(message)s",
    level=logging.WARNING,
)

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

    production, config = production_from_config(config_file, sub_console=sub_console)

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

    slack_admin_channel_id = os.environ.get("SLACK_ADMIN_CHANNEL_ID")
    # Note that the checking of the existence of the admin channel id is delayed
    # until after the subscribed channels are shown.

    production, config = production_from_config(config_file, sub_console)

    console.print("Preparing props...")
    production.prepare_props()
    console.print("Props are up-to-date.")

    slack_app_token, slack_bot_token = get_slack_auth()

    socket_mode_client = connect(slack_app_token, slack_bot_token)

    user_id = bot_user_id(socket_mode_client, console)
    console.print()

    channels_by_id, channel_name_to_id = channel_maps(socket_mode_client)
    console.print(channel_table(channels_by_id))
    console.print()

    if slack_admin_channel_id is None:
        raise ValueError(
            "SLACK_ADMIN_CHANNEL_ID environment variable not set. "
            "Please set it to the channel ID of the Proscenium admin channel."
        )
    if slack_admin_channel_id not in channels_by_id:
        raise ValueError(
            f"Admin channel {slack_admin_channel_id} not found in subscribed channels."
        )

    admin = Admin(slack_admin_channel_id)
    log.info("Admin handler started.")

    log.info("Places, please!")
    channel_id_to_character = production.places(channel_name_to_id)
    channel_id_to_character[slack_admin_channel_id] = admin

    console.print(places_table(channel_id_to_character, channels_by_id))
    console.print()

    slack_listener = make_slack_listener(
        user_id,
        slack_admin_channel_id,
        channels_by_id,
        channel_id_to_character,
        console,
    )

    send_curtain_up(socket_mode_client, production, slack_admin_channel_id)

    console.print("Starting the show. Listening for events...")
    listen(
        socket_mode_client,
        slack_listener,
        user_id,
        console,
    )

    send_curtain_down(socket_mode_client, slack_admin_channel_id)

    shutdown(
        socket_mode_client,
        slack_listener,
        user_id,
        production,
        console,
    )


if __name__ == "__main__":

    app()
