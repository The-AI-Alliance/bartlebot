#!/usr/bin/env python3

import os
import sys
import logging
import typer
import yaml

import importlib

from pathlib import Path
from rich.console import Console
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

app = typer.Typer(help="Bartlebot")

log = logging.getLogger(__name__)


def load_config(config_file_name: str) -> dict:

    if not os.path.exists(config_file_name):
        raise FileNotFoundError(
            f"Configuration file {config_file_name} not found. "
            "Please provide a valid configuration file."
        )

    with open(config_file_name, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
        return config


@app.command(help="""Start Bartlebot.""")
def start(
    config_file_name: str = typer.Option(
        Path("bartlebot.yml"),
        "-c",
        "--config",
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

    config = load_config(config_file_name)

    production_config = config.get("production", {})

    inference_config = config.get("inference", {})
    # slack_config = config.get("slack", {})
    graph_config = config.get("graph", {})
    vectors_config = config.get("vectors", {})
    enrichments_config = config.get("enrichments", {})
    scenes_config = production_config.get("scenes", {})
    law_library_config = scenes_config.get("law_library", {})

    production_module_name = production_config.get("module", None)
    production_class_name = production_config.get("class", None)
    production_module = importlib.import_module(production_module_name, package=None)
    ProductionClass = production_module.BartlebotProduction
    # PC = production_module.__getattr__(production_class_name)

    # production = production_module.make_production(slack_admin_channel_id, sub_console)
    production = ProductionClass(
        law_library_config["channel"],
        enrichments_config["docs_per_dataset"],
        Path(enrichments_config["jsonl_file"]),
        inference_config["delay"],
        graph_config.get("neo4j_uri", os.environ.get("NEO4J_URI")),
        graph_config.get("neo4j_username", os.environ.get("NEO4J_USERNAME")),
        graph_config.get("neo4j_password", os.environ.get("NEO4J_PASSWORD")),
        vectors_config["milvus_uri"],
        slack_admin_channel_id,
        vectors_config["embedding_model"],
        inference_config["extraction_model"],
        inference_config["generator_model"],
        inference_config["control_flow_model"],
        sub_console,
    )

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
