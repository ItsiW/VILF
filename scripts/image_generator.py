from pathlib import Path

import matplotlib.pyplot as plt
from PIL import Image, ImageDraw, ImageFont


class ImageGenerator:
    def __init__(
        self, place, font_path="comic_sans.ttf", logo_font_path="emilyscandy.ttf"
    ):
        self.place = place
        self.font_path = font_path
        self.logo_font_path = logo_font_path
        self.image_path = Path(f"../raw/food/{place['slug']}.jpg")
        self.img = Image.open(self.image_path)
        self.img = self.crop(self.img)
        self.draw = ImageDraw.Draw(self.img)
        self.img_height = self.img.size[1]
        self.margin = self.img_height // 20

    def crop(self, img):
        width, height = img.size
        left = (width - height) / 2
        right = (width + height) / 2
        img = img.crop((left, 0, right, height))
        return img

    def plot_img(self):
        plt.figure(figsize=(5, 5))
        plt.imshow(self.img)
        plt.axis("off")
        plt.show()

    def find_optimal_font_size(self, text, width, margin):
        font_size = 1
        font = ImageFont.truetype(self.font_path, font_size)
        while self.draw.textbbox((0, 0), text, font=font)[2] < width - margin * 2:
            font_size += 1
            font = ImageFont.truetype(self.font_path, font_size)
        font_size -= 1
        return ImageFont.truetype(self.font_path, font_size)

    def add_text_with_thick_outline(
        self, position, text, font, text_color, outline_color, thickness
    ):
        x, y = position
        for offset in range(-thickness, thickness + 1):
            self.draw.text(
                (x + offset, y + offset), text, font=font, fill=outline_color
            )
            self.draw.text(
                (x + offset, y - offset), text, font=font, fill=outline_color
            )
            self.draw.text(
                (x - offset, y + offset), text, font=font, fill=outline_color
            )
            self.draw.text(
                (x - offset, y - offset), text, font=font, fill=outline_color
            )
        self.draw.text(position, text, font=font, fill=text_color)

    def add_logo(self):
        logo_text_small = "Vegans In Love with Food"
        logo_text_large = "V.I.L.F"

        logo_text_small_size = self.img_height // 15
        logo_text_large_size = self.img_height // 7

        logo_font_small = ImageFont.truetype(self.logo_font_path, logo_text_small_size)
        logo_font_large = ImageFont.truetype(self.logo_font_path, logo_text_large_size)

        box_color = "#750395"

        box_top_left = (
            0,
            self.img_height
            - logo_text_large_size
            - logo_text_small_size
            - self.margin / 4,
        )
        box_bottom_right = (
            logo_font_large.getbbox(logo_text_large)[2] + self.margin * 3 / 2,
            self.img_height,
        )
        self.draw.rectangle([box_top_left, box_bottom_right], fill=box_color)

        box_top_left = (0, self.img_height - logo_text_small_size - self.margin / 2)
        box_bottom_right = (
            logo_font_small.getbbox(logo_text_small)[2] + self.margin,
            self.img_height,
        )
        self.draw.rectangle([box_top_left, box_bottom_right], fill=box_color)

        self.draw.text(
            (self.margin / 2, self.img_height - logo_text_small_size - self.margin / 2),
            logo_text_small,
            font=logo_font_small,
            fill="white",
        )
        self.draw.text(
            (
                self.margin,
                self.img_height
                - logo_text_large_size
                - logo_text_small_size
                - self.margin / 2,
            ),
            logo_text_large,
            font=logo_font_large,
            fill="white",
        )

    def add_name_and_area(self):
        name = self.place["name"]
        area = self.place["area"]
        primary_color = ["#ef422b", "#efa72b", "#32af2d", "#2b9aef"][
            self.place["taste"]
        ]
        secondary_color = "black"

        font_name = self.find_optimal_font_size(name, self.img_height, self.margin)
        text_width, text_height = font_name.getbbox(name)[2:]
        outline_thickness = font_name.size // 13

        self.add_text_with_thick_outline(
            (self.margin, 0),
            name,
            font_name,
            secondary_color,
            primary_color,
            outline_thickness,
        )

        font_area = self.find_optimal_font_size(area, self.img_height / 2, self.margin)
        self.add_text_with_thick_outline(
            (self.img_height / 2, text_height),
            area,
            font_area,
            primary_color,
            secondary_color,
            outline_thickness,
        )

    def add_little_guy(self):
        guy_image = Image.open(f"{self.place['taste_label_short']}.png").convert("RGBA")
        guy_image = guy_image.crop(guy_image.getbbox())
        resize_proportion = (self.img_height // (3 / 2)) / guy_image.size[1]
        new_width, new_height = int(resize_proportion * guy_image.size[0]), int(
            resize_proportion * guy_image.size[1]
        )
        guy_image = guy_image.resize((new_width, new_height))
        self.img.paste(
            guy_image,
            (self.img_height - guy_image.size[0], self.img_height - guy_image.size[1]),
            guy_image,
        )

    def generate_image(self):
        self.add_logo()
        self.add_name_and_area()
        self.add_little_guy()
        return self.img

    def save_image(self, filepath):
        if self.img.mode == 'RGBA':
            self.img = self.img.convert('RGB')
        self.img.save(filepath)
