---
title: "How to create reviews for V.I.L.F"
description: "Find out here how to become a reviewer for V.I.L.F!"
---

# How to create reviews for V.I.L.F

## You too, can be a VILF

Reviews and images are hard-coded into the code-base. Reviews are created with a single markdown file, and jpg images with the same slug can be added, with the thumbnail and review images being automatically resized.

1. Clone a copy of the repository with this command in your terminal: 

    ```git clone https://github.com/ItsiW/VILF.git```

    You will need a [GitHub](https://github.com) account and will need to [install git](https://git-scm.com/book/en/v2/Getting-Started-Installing-Git) on your computer.

2. In the `places/` directory, create a new markdown file \``your-restaurant.md`\` (but customize the name to your restaurant). Note that file names must only contain lower case letters, numbers,  and `-` dashes

3. Go to any other restaurant review file in `places/`, and copy-paste the contents into your new file.

4. Fill out each field specific to the new restaurant. Details can normally be found on google maps, with links to the menu normally found on the restaurant's website. Note that taste and value scores correspond with:
    
    0. Do Not Recommend
    1. Something Going For It
    2. Good
    3. Phenomenal

    Also fill out the written section.

5. To add an image, place it in the `raw/food/` directory. Make sure it is a jpg file, and change the name to \``your-restaurant.jpg`\`. Note that for the image to show up, the image filename must match the filename of your review.

6. run the following command in a terminal in the base folder for vilf: 

    `git add places/ raw/ && git commit -m "Add new restaurant" && git push`

That should work. If it fails to run on the cloud server, I will let you know and how to fix it.