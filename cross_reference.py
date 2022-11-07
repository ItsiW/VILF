from typing import Optional, Generator
from contextlib import contextmanager
import sys
import io
import glob
import re
from spatula import GoogleMapsScraper
import click


LAT_RES = 1e-6
LON_RES = 1e-6


@contextmanager
def redirect_std(
    input_override: str = '1',
    redirect_stdout: bool = True,
    redirect_stderr: bool = True
) -> Generator[None, None, None]:
    """
    Redirects std input and output

    Give a substitute response to input() (default '1') and optionally
    override the stdout to silence the output in testing
    """
    old_stdin = sys.stdin
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    sys.stdin = io.StringIO(input_override)
    if redirect_stdout:
        sys.stdout = io.StringIO()
    if redirect_stderr:
        sys.stderr = io.StringIO()
    yield
    sys.stdin = old_stdin
    sys.stdout = old_stdout
    sys.stderr = old_stderr


def get_all_markdown_files(directory) -> list[str]:
    """Return all markdown files in a given directory"""
    if not directory.endswith('/'):
        directory += '/'
    return sorted(glob.glob(rf'{directory}*.md'))


def get_content(files: list[str]) -> dict[str, str]:
    "Return all markdown content from a list of files"
    all_markdown = {}
    for file in files:
        with open(file, 'r') as f:
            all_markdown[file] = f.read()

    return all_markdown


def find_item(markdown: str, key: str) -> Optional[str]:
    """
    Return a field value from markdown content

    :param markdown: markdown content
    :param key: Field label to use
    :return: the value associated with the field e.g. key: value
             returns None if not found
    """
    search = re.findall(rf'{key}: (.*)', markdown)
    if search:
        return search[0]


@click.command()
@click.argument('files', type=click.Path(exists=True), nargs=-1)
def cross_reference_md(files: tuple[str]) -> None:
    if not files:
        print("No files to check.")
        return
    if any(not file.endswith('.md') for file in files):
        raise ValueError("Files must all be markdown (.md).")
    content = get_content(files)
    gmd = GoogleMapsScraper(headless=True)
    potentially_bad_files = []
    errors = {}
    print('\nTesting files:')
    for file, md in content.items():
        error_report = file + '\n'
        try:
            name = find_item(md, key='name').strip()
            address = find_item(md, key='address').strip()
            phone_number = find_item(md, key='phone')
            if phone_number is None:
                phone_number = ''
            phone_number.strip()
            lat = find_item(md, key='lat').strip()
            lon = find_item(md, key='lon').strip()
            query = f'{name} restaurant at {address}'
            with redirect_std(redirect_stdout=True):
                gmd.search_for_restaurant(search_query=query)
            gmd.scrape(close_browser=False)
            perfect_match = True
            if name != gmd.name:
                perfect_match = False
                error_report += f'Current name: {name} | Determined name: {gmd.name}\n'
            if address != gmd.street_address:
                perfect_match = False
                error_report += f'Current address: {address} | Determined address: {gmd.street_address}\n'
            if gmd.phone_number is None:
                gmd_phone_number = ''
            else:
                gmd_phone_number = f'"+1{gmd.phone_number}"'
            if phone_number != gmd_phone_number:
                perfect_match = False
                error_report += f'Current phone number: {phone_number} | Determined phone number: {gmd_phone_number}\n'
            if abs(float(lat) - gmd.lat_lon[0]) > LAT_RES:
                perfect_match = False
                error_report += f'Current latitude: {lat} | Determined latitude: {gmd.lat_lon[0]}\n'
            if abs(float(lon) - gmd.lat_lon[1]) > LON_RES:
                perfect_match = False
                error_report += f'Current longitude: {lon} | Determined longitude: {gmd.lat_lon[1]}\n'
        except Exception as e:
            error_report += str(e)
            errors[file] = error_report
            potentially_bad_files.append(file)
            print(u'\u2718 ' + f"{file}")
        else:
            if not perfect_match:
                errors[file] = error_report
                potentially_bad_files.append(file)
                print(u'\u2718 ' + f"{file}")
            else:
                print(u'\u2714 ' + f"{file}")

    if potentially_bad_files:
        print('\nThe following files may need inspection:\n')
        for file in potentially_bad_files:
            print(errors[file])
    else:
        print("\nAll staged files look good.")


if __name__ == "__main__":
    cross_reference_md()