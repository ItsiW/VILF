import click
from .build import build_vilf
from .cross_reference import cross_reference_md
from .spatula import scrape_and_gen_md

@click.group()
def vilf():
    """
    VILF CLI
    """
    pass

if __name__ == "__main__":
    vilf.add_command(build_vilf, 'build')
    vilf.add_command(scrape_and_gen_md, 'spatula')
    vilf.add_command(cross_reference_md, 'check')
    vilf()