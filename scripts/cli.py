import click

from .build import build_vilf
from .cross_reference import cross_reference_md
from .spatula import scrape_and_gen_md


@click.group()
def cli():
    """
    VILF CLI interface
    """
    pass


if __name__ == "__main__":
    cli.add_command(build_vilf, "build")
    cli.add_command(scrape_and_gen_md, "spatula")
    cli.add_command(cross_reference_md, "check")
    cli()
