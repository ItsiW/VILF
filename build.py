#!/bin/python3

import yaml
import glob
from markdown2 import markdown
from jinja2 import Template
from pathlib import Path

build_dir = Path(".") / "build"
build_dir.mkdir(exist_ok=True)

with open("html/template.html") as f:
    template = Template(f.read())

geo_data = []

for place_md in glob.glob("places/*.md"):
    slug = place_md[7:-3]
    print(slug)
    with open(place_md) as f:
        _, frontmatter, md = f.read().split("---", 2)
    meta = yaml.load(frontmatter, Loader=yaml.Loader)
    html = markdown(md.strip())
    rendered = template.render(
        **meta,
        # title=f"{meta['name']} | {meta['area']} | The Good Taste Guide",
        content=html,
    )
    out_dir = build_dir / "places" / slug
    out_dir.mkdir(exist_ok=True, parents=True)
    with open(out_dir / "index.html", "w") as o:
        o.write(rendered)
