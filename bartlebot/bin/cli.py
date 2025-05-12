import logging
import typer
from rich import print
from proscenium.verbs.display import header

from .typer_app import app as legal_app

log = logging.getLogger(__name__)

logging.getLogger("bartlebot").setLevel(logging.WARNING)
logging.getLogger("proscenium").setLevel(logging.WARNING)

app = typer.Typer(help="CLI Build for Bartlebot")
app.add_typer(legal_app, name="legal")

if __name__ == "__main__":
    print(header())
    app()
