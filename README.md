# Vegans In Love with Food™

## Running locally on linux

### **1. Activate virtual python environment**

If using `conda`:

```bash
# Makes environment if it doesn't exist
conda env list | grep VILF || conda create --name VILF

# Activates the environment
conda activate VILF
```

If using `virtualenv`:

```bash
# Makes environment if it doesn't exist
[[ -f venv/bin/activate ]] || virtualenv venv

# Activates the environment
source venv/bin/activate
```

### **2. Install dependencies**

```bash
pip install -r requirements.txt
```

### **3. Build static files**

```bash
./vilf build
```

### **4. Serve static files locally**

```bash
python3 -m http.server 8080 --directory build
```

### **5. Visit website**

Open [`localhost:8080`](localhost:8080) (if you open `0.0.0.0:8080` then the map will not render).

## Helpful infra commands

### **1. Push static files to bucket**

```bash
# Requires roles/storage.objectAdmin on gs://vilf-org
gsutil -m rsync -R build gs://vilf-org
```

### **2. Invalidate Cloud CDN cache**

```bash
# Requires roles/owner on projects/vilf-com
gcloud compute url-maps invalidate-cdn-cache vilf-lb --path /
```

### **3. Track SSL propagation status**

```bash
openssl s_client -showcerts -servername scripts.org -connect $(dig +short A vilf.org):443 -verify 99 -verify_return_error
```

### **4. Manage infrastructure**

We use [OpenTofu](https://opentofu.org/) to deploy infrastructure as code primarily to GCP. Install the tool and running it in `./infra` for more details. This will read the configuration from `main.tf.json` to determine what to administer. This file is generated from the configuration in `default.nix`, which requires the [Nix package manager](https://nixos.org/) to interpret. Once installed and the development shell activated, run `vilf tofu` to manage further.

### **5. Nix development shell**

We use a Nix development shell to currently to manage infrastructure and autoformat code. It will likely accumulate more functionality too. After installing [Nix: the package manager](https://nixos.org/download/), you can enter the development shell by running `nix develop`. In this shell you can run `pre-commit` to run repository commit hooks (autoformatting, linting, etc.), as well as access repository tools through the `vilf` executable.

## Tools for contributors

### `spatula`: Automating the restaurant data collection and markdown file generation

#### Interactive mode (recommended)

Think of a good search query that will locate your restaurant (e.g. "Lion Dance Cafe"). Run the following from the terminal to see an interactive prompt:

```bash
./vilf spatula
# Enter Google Maps search terms (ex: Lion Dance Cafe in Oakland):
```

Enter the hint:

```bash
./vilf spatula
# Enter Google Maps search terms (ex: Lion Dance Cafe in Oakland):
Lion Dance Cafe
```

The scraper will be able to identify the restaurant automatically and generate a markdown file for you:

```bash
./vilf spatula
# Enter Google Maps search terms (ex: Lion Dance Cafe in Oakland):
Lion Dance Cafe

# Waiting for Google Maps page to redirect...

# Using the Google Maps page: https://www.google.com/maps/place/Lion+Dance...
# Name = Lion Dance Café
# Address = 380 17th St
# City = Oakland
# State = CA
# Zip code = 94612
# Phone: None
# Lat, lon = 37.806069, -122.276674

# Successfully wrote markdown to file places/lion-dance-cafe.md
```

The markdown will contain the fields pre-populated and the relevant values already filled in. The rest is up to
you to fill in.

```bash
cat lion-dance-cafe.md
# ---
# name: Lion Dance Café
# cuisine:
# address: 380 17th St
# area:
# lat: 37.8060489
# lon: -122.267932
# phone:
# menu:
# drinks:
# visited:
# taste:
# value:
# ---

# <REVIEW>
```

File name formatting happens automatically. It will safely remove bad characters,
use the restaurant name (and possibly street name, see below), and will append an integer
to the end of the filename in cases of conflict with a preexisting file. You can also flag to use the
city name for the field `area` (though you may want to be more specific like "Downtown Oakland").

```bash
./vilf spatula --city-as-area --street-in-filename
# ...
# Successfully wrote markdown to file lion-dance-cafe-380-17th-st.md
cat lion-dance-cafe-380-17th-st.md
# ...
# address: 380 17th St
# area: Oakland
# lat: 37.8060489
# ...
```

Sometimes searches are ambiguous. In this case, the scraper will allow you to select one of the top results from a search or try a different search:

```bash
./vilf spatula
# Enter Google Maps search terms (ex: Lion Dance Cafe in Oakland):
Bongo Java Nashville

# Waiting for Google Maps page to redirect...

# I found multiple potential locations, collecting top results...
# Gathering search result data: 100%|█████| 5/5 [00:23<00:00,  4.63s/it]

# 0: Try searching again
# 1: Bongo Java at 2007 Belmont Blvd, Nashville, TN
# 2: Bongo Java East at 107 S 11th St, Nashville, TN
# 3: Bongo Java at 364 Rep. John Lewis Way S, Nashville, TN
# 4: Bongo Java Roasting Co. at 372 Herron Dr, Nashville, TN

# Select one of the above choices to proceed (0 - 4):
3

# Waiting for Google Maps page to redirect...

# Using the Google Maps page: https://www.google.com/maps/place/Bongo+Java...

# Name = Bongo Java
# Address = 364 Rep. John Lewis Way S
# City = Nashville
# State = TN
# Zip code = 37203
# Phone: None
# Lat, lon = 36.157151, -86.776074

# Successfully wrote markdown to file places/bongo-java.md
```

#### Manual URL mode

Alternatively, you can pass in a URL corresponding to a Google Maps restaurant manually. Be careful
to escape characters correctly (most terminals will automatically escape upon pasting).

Ex:

```bash
./vilf spatula --url https://www.google.com/maps/place/Lion+Dance+Caf%C3%A9/@37.8060737,
-122.270113,17z/data\=\!3m1\!4b1\!4m5\!3m4\!1s0x808f817f59aa5fa9:0xc6930eb94f2d3188\!8m2\!3d37.8060489\
!4d-122.267932

# Waiting for Google Maps page to redirect...

# Name = Lion Dance Café
# Address = 380 17th St
# City = Oakland
# State = CA
# Zip code = 94612
# Phone: None
# Lat, lon = 37.806074, -122.270113

# Successfully wrote markdown to file places/lion-dance-cafe-0.md
```

Notice the `-0` added to the filename to avoid a collision with the original file we produced.

#### Shortcuts and extras

1. `./vilf spatula --ask-first` prompts the user before writing metadata to markdown.
2. `./vilf spatula --search-query 'lion dance cafe'` or `./vilf spatula -s 'lion dance cafe'` avoids the search prompt and jumps right to the action
3. `./vilf spatula --directory '/path/to/folder'` allows you to specify the directory for the markdown file (directory doesn't have to exist yet)
4. `./vilf spatula --manual-filename '/path/to/folder/filename.md'` allows you to manually specify the output file
5. `./vilf spatula --timeout 30.0` let's you set the timeout for the browser (default is 10.0)
6. `./vilf spatula --no-headless` let's you see the browser GUI as the searches are being made (kinda fun but not recommended unless debugging)
7. For more details run `./vilf spatula --help`.

### Checking new file additions against Google Maps

Before committing new markdown files, `spatula` can be leveraged to check new files against
Google Maps scraping. Simply run the following from the repo home directory:

```bash
./vilf check $(git diff --staged --name-only places/)
```

If everything looks as expected, you will see

```bash
./vilf check $(git diff --staged --name-only places/)

# Testing files:
# ✔ places/lion-dance-cafe.md
# ✔ places/maya-halal-taqueria.md

# All files look good.
```

If anything is wrong, the metadata will be displayed:

```bash
./vilf check $(git diff --staged --name-only places/)

# Testing files:
# ✘ places/lion-dance-cafe.md
# ✔ places/maya-halal-taqueria.md

# The following files may need inspection:

# places/lion-dance-cafe.md
# Current address: 382 17th St | Determined address: 380 17th St
# Current latitude: 34.8060489 | Determined latitude: 37.8060489
# Current longitude: -120.267932 | Determined longitude: -122.267932
```
