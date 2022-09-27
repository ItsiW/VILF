---
title: "How to create reviews for V.I.L.F"
description: "Find out here how to become a reviewer for V.I.L.F!"
---

# How to create reviews for V.I.L.F

## You too, can be a VILF

Reviews and images are hard-coded into the code-base. Reviews are created with a single markdown file, and jpg images with the same slug can be added, with the thumbnail and review images being automatically resized.

If you haven't made a PR (pull request) before, this may seem very complicated. But once you have it going, this will become second nature.

1. Clone a copy of the repository with this command in your terminal: 

    ```git clone https://github.com/ItsiW/VILF.git```

    You will need a [GitHub](https://github.com) account and will need to [install git](https://git-scm.com/book/en/v2/Getting-Started-Installing-Git) on your computer.

2. Create a new git branch with your name and restaurant

    `git checkout -b your-name/your-restaurant`

3. In the `places/` directory, create a new markdown file \``your-restaurant.md`\` (but customize the name to your restaurant). Note that file names must only contain lower case letters, numbers,  and `-` dashes

4. Go to any other restaurant review file in `places/`, and copy-paste the contents into your new file.

5. Fill out each field specific to the new restaurant. Details can normally be found on google maps, with links to the menu normally found on the restaurant's website. Note that taste and value scores correspond with:
    
    0. Do Not Recommend
    1. Something Going For It
    2. Good
    3. Phenomenal

    Also fill out the written section.

6. To add an image, place it in the `raw/food/` directory. Make sure it is a jpg file, and change the name to \``your-restaurant.jpg`\`. Note that for the image to show up, the image filename must match the filename of your review.

7. run the following command in a terminal in the base folder for vilf: 

    `git add places/ raw/ && git commit -m "Add new restaurant" && git push`

   follow the instructions it gives you to add your local branch as a remote branch on github

8. Go to the [list of branches on github](https://github.com/ItsiW/VILF/branches), find your branch (with name `your-name/your-restaurant`), and on the left, open a new pull request, follow the instructions to create it. This is essentially a request to enter your changes into the codebase.

9. Someone will review your work to make sure it doesn't break anything. Then it will be approved. At that point, you will be pointed to merge your branch into the main `develop` branch, which will deploy it into the website.