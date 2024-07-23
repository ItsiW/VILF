import json
from time import sleep
from random import random
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from pathlib import Path

class InstagramBot:
    def __init__(self, credentials_file):
        self.username, self.password = self.load_credentials(credentials_file)
        self.driver = self.launch_instagram()

    def load_credentials(self, filepath):
        with open(filepath, 'r') as file:
            credentials = json.load(file)
            return credentials['username'], credentials['password']

    def slow_type(self, element, string):
        self.click(element)
        for char in string:
            sleep(0.2 * random())
            element.send_keys(char)

    def click(self, element):
        sleep(3 + random())
        element.click()

    def close_popup(self, close_button_text):
        try:
            close_button = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.XPATH, f"//*[text()='{close_button_text}']"))
            )
            self.click(close_button)
        except Exception as e:
            print(e)

    def launch_instagram(self):
        chrome_options = Options()
        chrome_options.add_argument("--disable-notifications")
        mobile_emulation = {"deviceName": "Nexus 5"}
        chrome_options.add_experimental_option("mobileEmulation", mobile_emulation)
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        driver.get("https://www.instagram.com/")
        return driver

    def login(self):
        login_button_1 = WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//*[text()='Log in']"))
        )
        self.click(login_button_1)
        username_element = WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.NAME, "username"))
        )
        self.slow_type(username_element, self.username)
        self.slow_type(self.driver.find_element(By.NAME, "password"), self.password)
        self.click(self.driver.find_element(By.XPATH, "//*[text()='Log in']"))
        
        self.close_popup("Dismiss")
        self.close_popup("Not now")
        self.close_popup("Cancel")

    def upload_post(self, place):
        # Navigate to the home page and initiate the new post process
        home_buttons = WebDriverWait(self.driver, 5).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, '[aria-label="Home"]'))
        )
        self.click(home_buttons[0])
        self.click(home_buttons[1])
        self.click(home_buttons[0])
        
        # Initiate new post
        new_post_button = WebDriverWait(self.driver, 5).until(
            EC.presence_of_element_located((By.XPATH, "//*[text()='Post']"))
        )
        self.click(new_post_button)
        sleep(5 + 2 * random())

        # Upload image
        image_file_location = Path(f"raw/food/{place['slug']}.jpg").absolute().as_posix()
        file_input = self.driver.find_elements(By.CSS_SELECTOR, 'input[type="file"]')[1]
        file_input.send_keys(image_file_location)

        # Proceed to the next page in the post creation flow
        next_button = WebDriverWait(self.driver, 5).until(
            EC.presence_of_element_located((By.XPATH, "//*[text()='Next']"))
        )
        self.click(next_button)

        # Enter main text (caption)
        text = f"""{place['name']} in {place['area']}: {place['taste_label']}!
        
{place['blurb'][:1000 + int(10 * random())]}

See the full review here
{"https://vilf.org" + place['url']}

#vegan #sanfrancisco #bayarea #sfbayarea #foodies #veganfood #{place['cuisine'].replace(" ", "")}FoodSanFrancisco #{place['area'].replace(" ", "").replace("-", "")}"""
        
        text_input = WebDriverWait(self.driver, 5).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "[aria-label='Write a caption…']"))
        )
        self.slow_type(text_input, text)
        self.click(self.driver.find_element(By.XPATH, f"//*[text()='New post']"))

        # Add location based on first option that comes up
        self.click(self.driver.find_element(By.XPATH, "//*[text()='Add Location']"))
        location_input = WebDriverWait(self.driver, 5).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='text']"))
        )
        self.slow_type(location_input, f"{place['name']} Restaurant")
        first_option = WebDriverWait(self.driver, 5).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "[dir='auto']"))
        )
        self.click(first_option)

        # Share the post
        share_button = WebDriverWait(self.driver, 5).until(
            EC.presence_of_element_located((By.XPATH, "//*[text()='Share']"))
        )
        self.click(share_button)

        # Optionally, navigate back to home to continue other actions or verify the post
        home_button = WebDriverWait(self.driver, 5).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, '[aria-label="Home"]'))
        )[1]
        self.click(home_button)

    def close_driver(self):
        self.driver.close()