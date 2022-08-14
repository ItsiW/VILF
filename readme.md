# Vegans In Love with Food™

## Links

1. [`Production IP: https://34.160.129.80:443`](https://34.160.129.80:443)
    * after DNS propagation, this will be [`vilf.org`](vilf.org)
2. [`Testing IP: http://34.160.113.123:80`](http://34.160.113.123:80)
    * This will be dactivated after DNS propagation in favor of HTTP forwarding automatically to HTTPS at [`vilf.org`](vilf.org)

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
gcloud beta compute ssl-certificates describe vilf-ssl --global --format="get(name, managed.status, managed.domainStatus)" --project climax-vilf
```

Using `openssl`:

```bash
openssl s_client -showcerts -servername vilf.org -connect 34.160.129.80:443 -verify 99 -verify_return_error
```