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
python build.py
```

### **4. Serve static files locally**

```bash
python3 -m http.server 8080 --directory build
```

### **5. Visit website**

Open [`localhost:8080`](localhost:8080) (if you open `0.0.0.0:8080` then the map will not render).

## Links

1. [`Production IP: https://34.160.129.80:443`](https://34.160.129.80:443)
    * after DNS propagation, this will be [`vilf.org`](vilf.org)
2. [`Testing IP: http://34.160.113.123:80`](http://34.160.113.123:80)
    * This will be dactivated after DNS propagation in favor of HTTP forwarding automatically to HTTPS at [`vilf.org`](vilf.org)

## Helpful admin commands

These will only work if your account has the right permissions.

### **1. Push static files to bucket**

```bash
gsutil -m rsync -R build gs://climax-vilf-bucket
```

### **2. Invalidate Cloud CDN cache**

```bash
gcloud compute url-maps invalidate-cdn-cache vilf-lb --path / --project climax-vilf
```

You can invalidate any specific static file by passing the relative path to the `--path` argument.

### **3. Track SSL propagation status**

Using `gcloud`:

```bash
# CERTIFICATE
gcloud beta compute ssl-certificates describe vilf-ssl --global --format="get(name, managed.status, managed.domainStatus)" --project climax-vilf

# LOAD BALANCER
gcloud compute target-https-proxies describe vilf-lb-target-proxy --project=climax-vilf
gcloud compute target-http-proxies describe vilf-lb-target-proxy-3 --project=climax-vilf

# FORWARDING RULES
gcloud compute forwarding-rules describe vilf-lb-frontend-main --project=climax-vilf --global
gcloud compute forwarding-rules describe vilf-lb-frontend-http-2 --project=climax-vilf --global
```

Using `openssl`:

```bash
openssl s_client -showcerts -servername vilf.org -connect 34.160.129.80:443 -verify 99 -verify_return_error
```

## Tools for contributors 

### Automating the data collection and markdown file generation
#### Interactive mode (recommended)
Think of a good search query that will locate your restaurant (e.g. "Lion Dance Cafe"). Run the following from the terminal to see an interactive prompt:
```bash
python scrape_and_gen_md.py
#Enter Google Maps search terms (ex: Lion Dance Cafe in Oakland):
```
Enter the hint:
```bash
python scrape_and_gen_md.py
#Enter Google Maps search terms (ex: Lion Dance Cafe in Oakland):
Lion Dance Cafe
```
The scraper will be able to identify the restaurant automatically and generate a markdown file for you:
```bash
python scrape_and_gen_md.py
#Enter Google Maps search terms (ex: Lion Dance Cafe in Oakland):
Lion Dance Cafe 

#Waiting for Google Maps page to redirect...

#Using the Google Maps page: https://www.google.com/maps/place/Lion+Dance...
#Name = Lion Dance Café
#Address = 380 17th St
#City = Oakland
#State = CA
#Zip code = 94612
#Phone: None
#Lat, long = 37.806069, -122.276674

#Successfully wrote markdown to file lion-dance-cafe.md
```
The markdown will contain the fields pre-populated and the relevant values already filled in. The rest is up to 
you to fill in.
```bash
cat lion-dance-cafe.md
#---
#name: Lion Dance Café
#cuisine: 
#drinks: 
#visited: 
#address: 380 17th St
#area: 
#taste: 
#value: 
#lat: 37.8060692
#lon: -122.2766738
#menu: 
#phone: 
#---
#
#<REVIEW>
```
File name formatting happens automatically. It will safely remove bad characters,
use the restaurant name (and possibly street name, see below), and will append an integer
to the end of the filename in cases of conflict with a preexisting file. You can also flag to use the 
city name for the field `area` (though you may want to be more specific like "Downtown Oakland").
```bash
python scrape_and_gen_md.py --city-as-area --street-in-filename
#...
#Successfully wrote markdown to file lion-dance-cafe-380-17th-st.md
cat lion-dance-cafe-380-17th-st.md
#...
#address: 380 17th St
#area: Oakland
#taste:
#... 
```

Sometimes searches are ambiguous. In this case, the scraper will allow you to select one of the top results from a search or try a different search:
```bash
python scrape_and_gen_md.py                
#Enter Google Maps search terms (ex: Lion Dance Cafe in Oakland):
Bongo Java Nashville
#
#Waiting for Google Maps page to redirect...
#
#I found multiple potential locations, collecting top results...
#Gathering search result data: 100%|█████| 5/5 [00:23<00:00,  4.80s/it]
#
#0: Try searching again
#1: Bongo Java at 2007 Belmont Blvd, Nashville, TN
#2: Bongo Java East at 107 S 11th St, Nashville, TN
#3: Bongo Java at 364 Rep. John Lewis Way S, Nashville, TN
#4: Bongo Java Roasting Co. at 372 Herron Dr, Nashville, TN
#
#Select one of the above choices to proceed (0 - 4):
3
#
#Waiting for Google Maps page to redirect...
#
#Name = Bongo Java
#Address = 364 Rep. John Lewis Way S
#City = Nashville
#State = TN
#Zip code = 37203
#Phone: None
#Lat, long = 36.157151, -86.776074
#
#Successfully wrote markdown to file bongo-java.md
```

#### Manual URL mode
Alternatively, you can pass in a URL corresponding to a Google Maps restaurant manually. Careful
to track escaped characters (most terminals will automatically escape upon pasting).
```bash
python scrape_and_gen_md.py --url https://www.google.com/maps/place/Lion+Dance+Caf%C3%A9/@37.8060737,
-122.270113,17z/data\=\!3m1\!4b1\!4m5\!3m4\!1s0x808f817f59aa5fa9:0xc6930eb94f2d3188\!8m2\!3d37.8060489\
!4d-122.267932
#
#Waiting for Google Maps page to redirect...
#
#Name = Lion Dance Café
#Address = 380 17th St
#City = Oakland
#State = CA
#Zip code = 94612
#Phone: None
#Lat, long = 37.806074, -122.270113
#
#Successfully wrote markdown to file lion-dance-cafe-0.md
```
Notice the `-0` added to the filename to avoid a collision with the original file we produced.

#### Shortcuts and extras
1. `python scrape_and_gen_md.py --search-query 'lion dance cafe'` or `python scrape_and_gen_md.py -s 'lion dance cafe'` avoids the search prompt and jumps right to the action
2. `python scrape_and_gen_md.py --directory '/path/to/folder'` allows you to specify the directory for the markdown file (directory doesn't have to exist yet)
3. `python scrape_and_gen_md.py --manual-filename '/path/to/folder/filename.md'` allows you to manually specify the output file
4. `python --timeout 30.0` let's you set the timeout for the browser (default is 5.0)
5. `python scrape_and_gen_md.py --no-headless` let's you see the browser GUI as the searches are being made (kinda fun but not recommended unless debugging)
For more details run `python scrape_and_gen_md.py --help`.