"""
Module to scrape Google Maps and output markdown corresponding to the VILF standard
"""
from typing import Optional
from dataclasses import dataclass, field
from collections import OrderedDict
from selenium import webdriver
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager
import re
from unidecode import unidecode
from tqdm.auto import tqdm
from pathlib import Path
import click



# The following are complex regex searches that check for valid lat/long coords
# The lat must be between -90 and +90 (to whatever precision) and similar for long
# but +/- 180. The regex is designed to search against a Google Maps URL where the
# lat, long will be located like "...google.com/maps...@LAT,LONG,..."
LAT_RE = r'([+-]?(?:(?:[1-8]?[0-9])(?:\.[0-9]+)?|90(?:\.0+)?))'
LONG_RE = r'([+-]?(?:(?:(?:[1-9]?[0-9]|1[0-7][0-9])(?:\.[0-9]+)?)|180(?:\.0{1,6})?))'
LAT_LONG_RE = '@' + LAT_RE + ',' + LONG_RE + ','

GOOGLE_MAPS_URL = "https://www.google.com/maps"
MAX_NUM_RESULTS = 5 # max number of results to show in interactive mode


def get_chrome_browser(headless: bool = True) -> webdriver.Chrome:
    """
    Return an automated browser.

    If headless=True, browser will not have GUI.
    """
    options = Options()
    if headless:
        options.add_argument("--headless")
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=options)


@dataclass
class GoogleMapsScraper:
    """
    Container dataclass for restaurant information.

    If a URL is specified at instatiation, it sends the browser there.
    Otherwise, the 'search' method supports interactive searches.

    Note that web scraping may be unstable if Google Maps alters its page layout.
    Effort has been made to not use queries based on HTML classes or absolute XPaths
    to avoid predictable instability, however, this approach may still need upkeep in
    the future.
    """
    name: str = field(init=False)
    street_address: str = field(init=False)
    city: str = field(init=False)
    state: str = field(init=False)
    zip: str = field(init=False)
    lat_long: tuple[float] = field(init=False) # Lat and long coordinates
    phone_number: Optional[str] = None
    url: Optional[str] = None
    headless: bool = True # headless = no browser GUI (recommended)
    timeout: float = field(default=5.0) # seconds - max time to wait for browser

    def __post_init__(self) -> None:
        if self.timeout < 0:
            self.timeout = 1.0
        self.browser = get_chrome_browser(headless=self.headless)
        self.wait = WebDriverWait(self.browser, timeout=self.timeout)
        if self.url is not None:
            self.browser.get(self.url)
            self._wait_for_maps_to_redirect()

    def scrape(self, close_browser: bool = True) -> None:
        try:
            self.name = self._get_name()
            address_info = self._get_address()
            self.phone_number = self._get_phone_number()
            if close_browser:
                self.close_browser()
            self.lat_long = self._parse_lat_long()

            self.street_address = address_info['street_address']
            self.city = address_info['city']
            self.state = address_info['state']
            self.zip = address_info['zip']
        except (NoSuchElementException, IndexError):
            print("\nMake sure search terms or supplied URL correspond to a restaurant location. "
                  "Try searching instead/again with better terms (ex: 'Battambang restaurant "
                  "Oakland' instead of 'Battambang'):\n")
            self.search_for_restaurant()
            self.scrape()

    def _get_name(self, silent: bool = False) -> str:
        """ Get the h1 field (seems reliable)"""
        try:
            return self.browser.find_element(By.TAG_NAME, value="h1").text
        except NoSuchElementException as e:
            if not silent:
                print("\nA name could not be located.")
            raise e


    def _get_address(self, silent: bool = False) -> dict[str, Optional[str]]:
        """
        Get the address using the 'Copy address' (pin) button

        The address is located several places, but this method seems more robust
        to random changes in the class names and structure since it's likely to
        always be attached to the button interface. It is possible for a location
        to not have an address (just coordinates), however, this is rare and probably
        not the desired behavior. An exception with message is raised if this doesn't
        succeed.
        """
        try:
            output = {'street_address': None, 'city': None, 'state': None, 'zip': None}
            button = self.browser.find_element(
                By.XPATH,
                "//button[starts-with(@aria-label, 'Address:')]"
            )
            full_address = button.get_attribute('aria-label').split(':')[1].strip()
            # occasionally restaurants will add extra info to the address
            # e.g. "inside mall, 100 First St, Suite #2, Springfield, ...". To parse this,
            # we split the address string by comma, then use a regex to identify the first
            # component that begins with a digit. This is presumably the street address. We
            # ignore anything before this (these tend to be instructions like "inside mall,
            # between 2nd and 3rd street, etc). There are some edge cases not caught by this
            # (e.g. One Ferry Building, S. Street...) so if we can't find what we need, just
            # set first_number_idx = 0. We then look through the remaining items and
            # locate the STATE ZIP with a regex. We assume we're only using US addresses.
            # From this position we assume the index to the left is the city and everything
            # between the street address up to the city is useful address info.
            address_list = [item.strip() for item in full_address.split(',')]
            first_number_idx = 0 # in case we fail to find a digit, we fall back to using the first item
            state_zip_idx = -1
            for idx, item in enumerate(address_list):
                if re.findall(r'^\d', item):
                    first_number_idx = idx
                    break
            if first_number_idx > len(address_list) - 3:
                # must have enough room for city and state-zip.
                raise IndexError("Error parsing address.")

            for idx, item in enumerate(address_list[first_number_idx + 1:]):
                if re.findall(r'([A-z]{2} \d{5})(?=-\d{4})?', item):
                    state_zip_idx = first_number_idx + 1 + idx
                    break
            if state_zip_idx < 2:
                raise IndexError("Error parsing address.")
            output['state'], output['zip'] = address_list[state_zip_idx].split(' ')
            output['city'] = address_list[state_zip_idx - 1]
            output['street_address'] = ', '.join(address_list[first_number_idx:state_zip_idx - 1])
            return output
        except NoSuchElementException as e:
            if not silent:
                print("\nAn address could not be located. This utility does not support " 
                      "Google Maps locations without addresses (cannot be only coordinates).")
            raise e

    def _get_phone_number(self) -> Optional[str]:
        """
        Get the phone number from the 'Copy phone number' button

        Many restaurants to not have phone numbers so this is not required
        to succeed.
        """
        try:
            button = self.browser.find_element(
                By.XPATH,
                "//button[starts-with(@aria-label, 'Phone:')]"
            )
            label = button.get_attribute('aria-label')
            return ''.join(filter(str.isdigit, label))
        except NoSuchElementException:
            return None

    def _parse_lat_long(self) -> tuple[float, float]:
        """
        Parse the URL with a regex for the lat and long coordinates

        This regex only searches for values within [-90, 90] for lattitude
        and [-180, 180] for longitude (decimals can be any precision). The
        regex looks for the pattern @LAT,LONG, with LAT in [-90, 90] and
        LONG in [-180, 180] (decimals can be any precision).

        :return: Tuple containing the lattitude and langitude
        """
        lat, long = re.findall(LAT_LONG_RE, self.url)[0]
        return (float(lat), float(long))

    def search_for_restaurant(self, search_query: Optional[str] = None) -> None:
        """
        Perform an interactive search for a restaurant's Google Maps site.

        Upon searching, either the restaurant is found unambiguously and the
        browser is redirected or multiple restaurants are found. In the latter
        case, the top few results (with info) are displayed and the user can
        select one or search again.
        """
        self.browser.get(GOOGLE_MAPS_URL)
        if search_query is None:
            search_query = input('Enter Google Maps search terms (ex: Lion Dance Cafe in Oakland):\n')
        self.wait.until(EC.element_to_be_clickable((By.ID, "searchboxinput"))).send_keys(search_query)
        self.wait.until(EC.element_to_be_clickable((By.ID, "searchbox-searchbutton"))).click()
        self._wait_for_maps_to_redirect()

        # Multiple locations/ambiguous search
        if re.search(r'google.com/maps/search', self.browser.current_url):
            print("\nI found multiple potential locations, collecting top results...")
            results = self._get_search_results()
            ans = self._prompt_choice(results)
            if ans == 0:
                self.search_for_restaurant()
            elif ans > 0:
                self.browser.get(results[ans - 1]['href'])
                self._wait_for_maps_to_redirect()
                self.url = self.browser.current_url
                print(f"\nUsing the Google Maps page: {self.url}")
            else:
                raise ValueError("Answer must be 0 or a valid integer index from a search result.")
        elif re.search(r'google.com/maps/place', self.browser.current_url):
            self.url = self.browser.current_url
            print(f"\nUsing the Google Maps page: {self.url}")
        else:
            raise ValueError("URL must correspond to either a search or place.")

    def _get_search_results(self) -> OrderedDict[int, dict[str, Optional[str]]]:
        """
        Take search results and query the names and info.

        We search for HTML anchors with parents who are "articles" and take
        the top 5 results. This method of scraping is a little sus - might want to
        firm this up later.
        """
        # TODO: Maybe this can be better/more reliable?
        results = self.browser.find_elements(By.XPATH, "//a/parent::div[@role='article']/a")
        res_dict = OrderedDict()
        for idx, item in enumerate(results[:MAX_NUM_RESULTS]):
            res_dict[idx] = {}
            res_dict[idx]['name'] = item.get_attribute('aria-label')
            res_dict[idx]['href'] = item.get_attribute('href')
            res_dict[idx]['street_address'] = None
            res_dict[idx]['city'] = None
            res_dict[idx]['state'] = None
        for idx in tqdm(range(len(res_dict)), desc="Gathering search result data"):
            try:
                self.browser.get(res_dict[idx]['href'])
                self._wait_for_maps_to_redirect(silent=True)
                address_info = self._get_address(silent=True)
                res_dict[idx]['street_address'] = address_info['street_address']
                res_dict[idx]['city'] = address_info['city']
                res_dict[idx]['state'] = address_info['state']
            except:
                # If we can't find the address we should not present this as an option
                del res_dict[idx]
        if len(res_dict) < len(results):
            res_dict = OrderedDict(
                [(idx, value) for idx, (_, value) in enumerate(res_dict.items())]
            )
        return res_dict


    def _prompt_choice(self, res_dict: dict[int, dict[str, str]]) -> int:
        """Prompt the user to make a selection of search results."""
        if not res_dict:
            print("\nCould not find any acceptable search results, please "
                  "try a different search.")
            self.search_for_restaurant()
        print('\n0: Try searching again')
        for idx, info in res_dict.items():
            print(
                f'{idx+1}' + ':',
                info['name'] + ' at ' + info['street_address'] + ', '\
                + info['city'] + ', ' + info['state']
            )
        ans = input(f'\nSelect one of the above choices to proceed (0 - {len(res_dict)}):\n')
        return int(ans)

    def _wait_for_maps_to_redirect(self, silent: bool = False) -> None:
        """
        Wait for Google Maps to finish redirect

        This first waits until the URL redirects to a search or a place
        with valid lattitude and longitude coords (can take a few seconds). It
        then verifies the h1 (name) field and Address button are present if it's
        a place.
        """
        try:
            if not silent:
                print('\nWaiting for Google Maps page to redirect...')
            self.wait.until(
                EC.url_matches(rf'google.com/maps/(search|place.*{LAT_LONG_RE}).*/data=')
            )
            if re.search(r'google.com/maps/place', self.browser.current_url):
                # If place, check main h1 element is loaded (can't check address
                # or phone because these aren't guaranteed
                self.wait.until(
                    EC.presence_of_element_located((By.TAG_NAME, 'h1'))
                )
        except TimeoutException as e:
            print(
                "\nTimeoutException: URL did not load correctly within the given timeout."
                " URL must be of the form '...google.com/maps/search/.../data=...' or "
                "'...google.com/maps/place/...@<lat>,<long>,.../data=...' within "
                f"{self.timeout} seconds. Found '{self.browser.current_url}' instead. It's "
                "possible the timeout is too short and the Google Maps URL has not redirected "
                "or the specified URL is incompatible."
            )
            raise e

    def write_data_to_markdown(
            self,
            city_as_area: bool = False,
            street_in_filename: bool = False,
            manual_filename: Optional[str] = None,
            directory: Optional[str] = None
    ) -> Path:
        """
        Write relevant VILF data to markdown file

        :param city_as_area: Whether or not to use the city as the 'area' field
                             (False by default)
        :param street_in_filename: Whether or not to use the street address in the
                                   file name (useful for chains, False by default)
        :param manual_filename: Manual filename to override the smart autogenerator.
        :param directory: Directory to locate output file. If None uses current directory.
        :return: The output file path (after potential modifications)
        """
        path = self._make_markdown_file(
            include_street=street_in_filename,
            manual_filename=manual_filename,
            directory=directory
        )
        if city_as_area:
            area = self.city
        else:
            area = ""

        if self.phone_number is None:
            phone = ""
        else:
            phone = f"\"+1{self.phone_number}\""

        md = "---\n"
        md += f"name: {self.name}\n"
        md += "cuisine: \n"
        md += f"address: {self.street_address}\n"
        md += f"area: {area}\n"
        md += f"lat: {self.lat_long[0]}\n"
        md += f"lon: {self.lat_long[1]}\n"
        md += f"phone: {phone}\n"
        md += "menu: \n"
        md += "drinks: \n"
        md += "visited: \n"
        md += "taste: \n"
        md += "value: \n"
        md += "---\n\n"
        md += "<REVIEW>"

        with open(path, 'w', encoding='utf-8', errors='xmlcharrefreplace') as f:
            f.write(md)

        return path

    def _make_markdown_file(
        self,
        include_street: bool = False,
        manual_filename: Optional[str] = None,
        directory: Optional[str] = None
    ) -> Path:
        """
        Make a markdown file for output

        If manual_filename is not specified (recommended), a smart filename will
        be generated automatically.

        :param include_street: Whether or not to include the street address in the
                               filename
        :param manual_filename: Manual filename to override autogenerated one
        :param directory: Directory for output (ignored with manual_filename)
        :return: The Path object associated with the file
        """
        if manual_filename:
            return Path(manual_filename).with_suffix('.md')

        return self._make_filename(include_street=include_street, directory=directory)

    def _make_filename(
            self,
            include_street: bool = False,
            directory: Optional[str] = None
    ) -> Path:
        """
        Make a good filename that doesn't conflict with current files
        without requiring user input. Uses the restaurant name and possible
        street address. Build any directories needed that are not already present.

        :param include_street: Whether or not to include the street address in the
                               filename
        :param directory: Directory for output (doesn't need to exist yet)
        :return: The Path object associated with the file
        """
        if self.name:
            base_name = self.name
        else:
            raise ValueError("GoogleMapsScraper.name must not be None or an empty string.")
        if include_street:
            base_name += '-' + self.street_address

        # coerce any non-ascii letters to their closest ascii form
        base_name = unidecode(base_name)

        # make any non-alpha-numeric or dash items into dashes
        base_name = re.sub(r'[^\w\-]', '-', base_name)

        # remove any duplicate dashes
        base_name = re.sub(r'(\-{2,})', '-', base_name)

        # lowercase
        base_name = base_name.lower()

        # get directory sorted out
        if directory is None:
            directory = "./"
        if not directory.endswith('/'):
            directory += '/'

        # initial guess
        path = Path(directory + base_name).with_suffix('.md')

        # if initial guess already exists, loop trying different
        # integer appendages to the end until a new one is found
        appendage = 0
        while path.exists():
            path_stem = str(path.stem)
            path_stem = re.split(r"-\d+$", path_stem)[0]
            path_stem += "-" + str(appendage)
            path = path.parents[0] / Path(path_stem).with_suffix('.md')
            appendage += 1
        path.parents[0].mkdir(parents=True, exist_ok=True)

        return path

    def print_results(self) -> None:
        """Print all the output upon success"""
        print(f'\nName = {self.name}')
        print(f'Address = {self.street_address}')
        print(f'City = {self.city}')
        print(f'State = {self.state}')
        print(f'Zip code = {self.zip}')
        print(f'Phone: {self.phone_number}')
        print(f'Lat, long = {self.lat_long[0]:.6f}, {self.lat_long[1]:.6f}')

    def close_browser(self) -> None:
        self.browser.quit()

@click.command()
@click.option(
    '--search-query', '-s', default='',
    help="Google Maps search query to start interactive mode automatically. "
         "--url is ignored if --search-query is used."
)
@click.option(
    '--url', default='',
    help="Google Maps restaurant URL. Do not enclose URL in quotes in most terminals (e.g. zsh)"
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
@click.option('--directory', default='./places/',
              help="Directory for output file (only used if NOT using --manual-filename). It "
                   "defaults to using './places/'."
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
    """
    Scrape Google Maps and generate a markdown file (to be run from command line)

    Can run in interactive or manual mode depending on whether a url is supplied.
    :param search_query: String search to pass to Google Maps (without prompt)
    :param url: Google Maps restaurant URL
    :city_as_area: Whether to use the city for the area in the output markdown file
    :street_in_filename: Whether to use the street name in the output file
    :manual_filename: A manual filename that prevents an autogenerated name
    :directory: Directory specified for output file (doesn't have to exist yet)
    :timeout: Max time to wait for browser actions
    :headless: Whether to run without GUI (True) or with GUI (False)
    """
    search_query = search_query.strip()
    url = url.strip()
    manual_filename = manual_filename.strip()
    directory = directory.strip()
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
