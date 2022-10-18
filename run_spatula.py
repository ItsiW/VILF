"""Click binding to make a CLI for GoogleMapsScraper's spatula and markdown generator"""
import click
from spatula.spatula import GoogleMapsScraper


@click.command()
@click.option(
    '--search-query', '-s', default='',
    help="Google Maps search query to start interactive mode automatically. "
         "--url is ignored if --search-query is used."
)
@click.option(
    '--url', default='',
    help="Google Maps restaurant URL (or leave off to use interactive search)."
         "Do not enclose URL in quotes in most terminals (e.g. zsh)"
)
@click.option(
    '--city-as-area/--no-city-as-area', default=False,
    help="Whether to use the city as the output file's 'area' field (False by default)"
)
@click.option(
    '--street-in-filename/--no-street-in-filename', default=False,
    help="Whether to include the street address in the output filename (False by default)"
)
@click.option('--manual-filename', default='',
              help='Manual filename to use for output. Include full path with directories. '
                   'Leave off to autogenerate a smart filename (suggested).'
)
@click.option('--directory', default='',
              help="Directory for output file (only used if NOT using --manual-filename)"
)
@click.option('--timeout', default=5.0,
              help="Timeout for webdriver actions in seconds (default 5.0)"
)
@click.option('--headless/--no-headless', default=True,
              help="Whether to use GUI-less (headless) or full GUI web browser. Headless "
                   "by default (recommended unless debugging)."
)
def scrape_and_gen_md(
        search_query: str = '',
        url: str = '',
        city_as_area: bool = False,
        street_in_filename: bool = False,
        manual_filename: str = '',
        directory: str = '',
        timeout: float = 5.0,
        headless: bool = True
) -> None:
    if not search_query:
        search_query = None
    if not url:
        url = None
    if not manual_filename:
        manual_filename = None
    if not directory:
        directory = None

    gmd = GoogleMapsScraper(url=url, timeout=timeout, headless=headless)
    if url is None:
        gmd.search_for_restaurant(search_query=search_query)
    gmd.scrape()
    gmd.print_results()

    path = gmd.write_data_to_markdown(
        city_as_area=city_as_area,
        street_in_filename=street_in_filename,
        manual_filename=manual_filename,
        directory=directory
    )
    print(f"\nSuccessfully wrote markdown to file {str(path)}")

if __name__ == "__main__":
    scrape_and_gen_md()