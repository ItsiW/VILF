# Vegans In Love with Food™

## Running locally

Dependencies are managed with [uv](https://docs.astral.sh/uv/). Run everything from the repo root.

### **1. Install dependencies**

```bash
uv sync
```

This creates `.venv/` with the Python version from `.python-version` (downloaded if needed) and the packages pinned in `uv.lock`. Add `--group instagram` if you want to run the Instagram poster.

### **2. Build static files**

```bash
./vilf build
```

or for automatically running modified files during development
```bash
ls | entr ./vilf build
```

### **3. Serve static files locally**

```bash
python3 -m http.server 8080 --directory build
```

### **4. Visit website**

Open [`localhost:8080`](localhost:8080) (if you open `0.0.0.0:8080` then the map will not render).

### **5. Run the tests**

```bash
uv run pytest
```

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

### Setup

`spatula`, `check` and `audit` call the Google Places API. Put your key in a `.env` at the repo root (gitignored) or export it; no browser is needed:

```bash
echo 'GOOGLE_PLACES_API_KEY=...' > .env
```

### `spatula`: create a new review file

```bash
./vilf spatula
# Search Google Places (name and city, or a Google Maps URL): Lion Dance Cafe Oakland
```

Type a name and city, or paste a Google Maps URL. An unambiguous search goes straight through; otherwise up to five results are listed and you pick one (or `0` to search again):

```bash
# 0: Search again
# 1: Bongo Java at 2007 Belmont Blvd, Nashville
# 2: Bongo Java East at 107 S 11th St, Nashville
# Pick one [0-2]: 2
```

- `./vilf spatula -s 'Lion Dance Cafe Oakland'` skips the search prompt.
- `./vilf spatula --place-id ChIJ...` skips the search entirely.
- Phone and website are fetched too by default (one Enterprise-tier call per new review); `--no-details` skips that.

It then asks for `cuisine`, `area` (defaults to the city, but use a neighborhood), `drinks`, `taste`, `value` and `visited` (defaults to today), writes `places/<slug>.md` with a `<REVIEW>` placeholder and prints what is still to do. Normally that is just "write the review and bold a dish":

```bash
./vilf spatula -s 'Lion Dance Cafe Oakland'

# Name = Lion Dance Cafe
# Address = 380 17th St
# City = Oakland
# State = CA
# Zip code = 94612
# Phone = +15105550199
# Website = https://example.com/lion-dance
# Status = OPERATIONAL
# Lat, lon = 37.806100, -122.268300
# Maps = https://maps.google.com/?cid=...
# cuisine: Chinese
# area (neighborhood, required) [Oakland]: Downtown Oakland
# drinks (serves alcohol) [y/n]: n
# taste: 0=DNR 1=SGFI 2=Good 3=Phenomenal
# taste: 3
# value: 0=Bad 1=Fine 2=Good 3=Phenomenal
# value: 2
# visited [2026-09-09]:

# To do before this file builds:
# - write the review (body is still the <REVIEW> placeholder) and bold at least one dish with **...**

# Wrote places/lion-dance-cafe.md
```

Extras:

- `--no-prompt` writes the blank skeleton (empty `cuisine`, `area`, `drinks`, ...) for you to fill in by hand.
- `--photo path-or-url` copies (or downloads) the food photo to `raw/food/<slug>.jpg`, converting to JPEG if needed, and warns if it is wider than 16:9 (the build rejects that).
- A place already in the output directory (same `place_id`, or within 30 m) aborts with the existing filename; `--force` writes anyway and also overwrites an existing photo. Only the output directory is scanned.
- Filenames are slugs of the name (`Lion Dance Café` -> `lion-dance-cafe`) with `-0`, `-1`, ... appended on collision. `--street-in-filename` adds the street (useful for chains), `--manual-filename path.md` sets it by hand, `--directory` changes the output directory (default `./places/`).
- `--city-as-area` prefills `area` with the city; `--ask-first` confirms before writing.
- `./vilf spatula --help` lists everything.

### `check`: verify files against Google

Before committing new markdown files, compare them with what Google Places has:

```bash
./vilf check $(git diff --staged --name-only places/)
```

Files with a `place_id` are looked up directly; older files without one are matched by a text search on the name and address (the output says so). Name and address must match exactly, coordinates within 1e-4 degrees. Add `--contact` to also compare the phone number and show a website the file lacks. The command exits 1 on any mismatch or error, so it can gate a commit.

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

### `audit`: find closed restaurants

```bash
./vilf audit
```

Checks the Google business status of every place file that has a `place_id` (one Pro-tier call each; files without a `place_id` are only counted) and lists the ones that are permanently closed, temporarily closed, or have an unknown status. Informational: it always exits 0.

### Keeping the data fresh

All of these need `GOOGLE_PLACES_API_KEY` in `.env` (see Setup). Every run of `audit` and `check --fix` appends a line to `AUDIT_LOG.md`, and `audit` prints when the last audit happened, so that file is the answer to "is it time to re-check everything?".

```bash
./vilf enrich                          # link reviews that lack a place_id (nearest Google match within 150 m); fills city
./vilf check --contact --fix places/*.md   # pull Google's phone, website, coordinates and street into files with a place_id
./vilf audit --delete                  # remove reviews Google marks permanently closed (and their raw/food photo)
```

`check --fix` never changes a restaurant's name and keeps unit or suite details you recorded; `audit --delete` only deletes permanently closed places and reports temporary closures. Two reviews are deliberately unlinked and will always show up as "without a place_id": `fiji-airways` (a joke entry) and `boba-binge` (the branch reviewed no longer exists on Maps).

