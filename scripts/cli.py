import click

from .audit import audit_places
from .build import build_vilf
from .cross_reference import cross_reference_md
from .enrich import enrich
from .spatula import scrape_and_gen_md


@click.group()
def cli():
    """
    VILF CLI interface
    """
    pass


cli.add_command(build_vilf, "build")
cli.add_command(scrape_and_gen_md, "spatula")
cli.add_command(cross_reference_md, "check")
cli.add_command(audit_places, "audit")
cli.add_command(enrich, "enrich")


if __name__ == "__main__":
    cli()
