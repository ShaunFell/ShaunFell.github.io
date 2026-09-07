#!/usr/bin/env python3
"""
Keep _data/publications.yml in sync with INSPIRE-HEP and ORCID.

What it does, in order:
  1. Pulls every record for the author from INSPIRE-HEP (by INSPIRE BAI) and
     ORCID (by ORCID iD), and merges them on arXiv id / DOI.
  2. Compares against the existing YAML. New papers are added; for existing
     papers only "live" metadata is refreshed (citation counts, journal info
     once a preprint is published). Anything you edited by hand -- description,
     thumbnail, featured, hidden, code, title -- is left alone.
  3. For each new paper, downloads the arXiv PDF and renders its first page to
     a PNG thumbnail (the "cover"). Papers without an arXiv id get a generated
     placeholder card.
  4. Writes a short, accessible one-paragraph description using the Claude
     API. The key comes from the ANTHROPIC_API_KEY environment variable (GitHub
     Actions secret) or, locally, from the operating system's keyring (store it
     once with --set-key). If neither is available or the call fails, the first
     sentences of the abstract are used instead.
  5. Writes the YAML back, newest first, and prints a summary.

Usage:
  python scripts/update_publications.py            # normal run
  python scripts/update_publications.py --dry-run  # report only, write nothing
  python scripts/update_publications.py --regen-thumbnails
  python scripts/update_publications.py --regen-descriptions
  python scripts/update_publications.py --set-key      # store the API key in the OS keyring
  python scripts/update_publications.py --check-api    # verify the key works

Configuration lives in _config.yml under the `publications:` key.
"""
from __future__ import annotations

import argparse
import io
import os
import re
import sys
import textwrap
import time
from dataclasses import dataclass, field, asdict
from datetime import date
from pathlib import Path
from typing import Any

import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent


# How each description was produced, for the end-of-run summary.
DESCRIPTION_STATS = {"claude": 0, "fallback": 0, "last_error": None}

# Where the Claude API key is kept in the operating system's credential store
# (Secret Service / KWallet / GNOME Keyring on Linux, Keychain on macOS,
# Credential Locker on Windows). Never a file in the repository.
CONFIG: dict[str, Any] = {}
KEYRING_SERVICE = "anthropic"
KEYRING_USER = "shaundbfell.com-publications"


def resolve_api_key() -> tuple[str | None, str]:
    """Return (key, source). Order: ANTHROPIC_API_KEY env var (CI secrets) -> OS keyring."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return os.environ["ANTHROPIC_API_KEY"], "environment"
    try:
        import keyring
        from keyring.errors import KeyringError
    except ImportError:
        return None, "keyring package not installed"
    try:
        key = keyring.get_password(KEYRING_SERVICE, KEYRING_USER)
    except KeyringError as e:
        return None, f"no usable OS keyring ({e.__class__.__name__})"
    if key:
        return key, "OS keyring"
    return None, "no key in the OS keyring (run with --set-key)"


def resolve_workspace_id(cfg_value: str | None = None) -> str | None:
    """Optional workspace for organisation-level keys: ANTHROPIC_WORKSPACE_ID env var, else _config.yml."""
    return os.environ.get("ANTHROPIC_WORKSPACE_ID") or cfg_value or None


def store_api_key() -> int:
    """Prompt for the key without echo and store it in the OS keyring."""
    import getpass
    try:
        import keyring
    except ImportError:
        log("The keyring package is not installed: pip install -r scripts/requirements.txt")
        return 2
    key = getpass.getpass("Anthropic API key (input hidden): ").strip()
    if not key.startswith("sk-ant-"):
        log("That does not look like an Anthropic API key (expected it to start with sk-ant-). Nothing stored.")
        return 2
    keyring.set_password(KEYRING_SERVICE, KEYRING_USER, key)
    backend = keyring.get_keyring().__class__.__module__
    log(f"Stored in the OS keyring ({backend}) under service={KEYRING_SERVICE!r}, user={KEYRING_USER!r}.")
    return 0


def delete_api_key() -> int:
    import keyring
    from keyring.errors import PasswordDeleteError
    try:
        keyring.delete_password(KEYRING_SERVICE, KEYRING_USER)
        log("Removed the key from the OS keyring.")
    except PasswordDeleteError:
        log("No key was stored.")
    return 0
USER_AGENT = "shaundbfell.com publication updater (https://github.com/ShaunFell/ShaunFell.github.io)"
HTTP_TIMEOUT = 60

# Fields the script is allowed to overwrite on an existing entry. Everything
# else in the YAML is considered human-owned and is preserved verbatim.
LIVE_FIELDS = {"citations", "venue", "volume", "pages", "doi", "type", "inspire", "date", "year", "url", "abstract"}


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #
@dataclass
class Publication:
    id: str                      # stable key: arXiv id, else DOI, else inspire:<recid>
    title: str
    authors: list[str]
    year: int
    date: str                    # ISO date used for sorting
    type: str = "preprint"       # article | preprint | thesis | software | book
    venue: str | None = None
    volume: str | None = None
    pages: str | None = None
    doi: str | None = None
    arxiv: str | None = None
    inspire: int | None = None
    citations: int = 0
    url: str | None = None       # canonical "read it" link
    abstract: str | None = None
    description: str | None = None
    thumbnail: str | None = None
    code: str | None = None
    featured: bool = False
    hidden: bool = False

    def to_yaml_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Keep the YAML tidy: drop empty optional fields, but keep booleans.
        return {k: v for k, v in d.items() if v not in (None, "", []) or isinstance(v, bool)}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def log(msg: str) -> None:
    print(msg, flush=True)


def http_get(url: str, **kw) -> requests.Response:
    """GET with a polite UA and simple retry on transient failures."""
    headers = {"User-Agent": USER_AGENT, **kw.pop("headers", {})}
    last: Exception | None = None
    for attempt in range(4):
        try:
            r = requests.get(url, headers=headers, timeout=HTTP_TIMEOUT, **kw)
            if r.status_code in (429, 500, 502, 503, 504):
                raise requests.HTTPError(f"{r.status_code} from {url}")
            r.raise_for_status()
            return r
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"GET {url} failed after retries: {last}")


def clean_arxiv(value: str | None) -> str | None:
    """Normalise things like 'arXiv:2104.06488v1' -> '2104.06488'."""
    if not value:
        return None
    v = value.strip()
    v = re.sub(r"^(arxiv:|https?://arxiv\.org/(abs|pdf)/)", "", v, flags=re.I)
    v = re.sub(r"v\d+$", "", v)
    v = re.sub(r"\.pdf$", "", v)
    return v or None


def clean_doi(value: str | None) -> str | None:
    if not value:
        return None
    v = value.strip()
    v = re.sub(r"^https?://(dx\.)?doi\.org/", "", v, flags=re.I)
    v = re.sub(r"^doi:", "", v, flags=re.I)
    return v.lower() or None


def is_arxiv_doi(doi: str | None) -> bool:
    return bool(doi and doi.startswith("10.48550/arxiv."))


def latex_to_text(s: str) -> str:
    """Strip the most common LaTeX, MathML and HTML markup from titles/abstracts."""
    import html
    s = re.sub(r"<annotation[^>]*>.*?</annotation>", "", s, flags=re.S)  # MathML source copies
    s = re.sub(r"<[^>]+>", "", s)                                          # remaining tags
    s = html.unescape(s)
    s = s.replace(r"\mathbb Q", "Q").replace(r"\mathbb{Q}", "Q")
    s = re.sub(r"\$([^$]*)\$", r"\1", s)
    s = re.sub(r"\\(text|mathrm|mathbf|emph|textit)\{([^}]*)\}", r"\2", s)
    s = s.replace("\\", "")
    s = re.sub(r"\.(?=[A-Z])", ". ", s)  # "era.Gravitational" -> "era. Gravitational" (PDF extraction artefact)
    return re.sub(r"\s+", " ", s).strip()


def short_author(full_name: str) -> str:
    """'Fell, Shaun David Brocus' -> 'S. D. B. Fell'; 'Loeb, Abraham' -> 'A. Loeb'."""
    if "," in full_name:
        last, first = [p.strip() for p in full_name.split(",", 1)]
    else:
        parts = full_name.split()
        last, first = parts[-1], " ".join(parts[:-1])
    initials = " ".join(f"{p[0]}." for p in re.split(r"[\s.\-]+", first) if p)
    return f"{initials} {last}".strip()


def first_sentences(text: str, n: int = 2, max_chars: int = 320) -> str:
    """The first n sentences, dropping sentences (not words) until it fits."""
    sents = re.split(r"(?<=[.!?])\s+", text.strip())
    for k in range(n, 0, -1):
        out = " ".join(sents[:k]).strip()
        if len(out) <= max_chars:
            return out
    out = sents[0].strip() if sents else ""
    return out[: max_chars - 1].rsplit(" ", 1)[0] + "…" if len(out) > max_chars else out


# --------------------------------------------------------------------------- #
# Sources
# --------------------------------------------------------------------------- #
INSPIRE_FIELDS = ",".join([
    "titles", "arxiv_eprints", "dois", "publication_info", "authors.full_name",
    "abstracts.value", "abstracts.source", "earliest_date", "citation_count", "document_type", "control_number",
    "thesis_info",
])

JOURNAL_NAMES = {
    "Phys.Rev.D": "Physical Review D",
    "Phys.Rev.Lett.": "Physical Review Letters",
    "Class.Quant.Grav.": "Classical and Quantum Gravity",
    "Fortsch.Phys.": "Fortschritte der Physik",
    "J.Open Source Softw.": "Journal of Open Source Software",
    "JCAP": "Journal of Cosmology and Astroparticle Physics",
    "JHEP": "Journal of High Energy Physics",
    "Mon.Not.Roy.Astron.Soc.": "Monthly Notices of the Royal Astronomical Society",
    "Astrophys.J.": "The Astrophysical Journal",
    "Gen.Rel.Grav.": "General Relativity and Gravitation",
}


def pick_abstract(abstracts: list[dict[str, Any]]) -> str | None:
    """Prefer the arXiv abstract (plain text) over publisher versions (often MathML)."""
    if not abstracts:
        return None
    ranked = sorted(abstracts, key=lambda a: 0 if (a.get("source") or "").lower() == "arxiv" else 1)
    return latex_to_text(ranked[0].get("value", "")) or None


def parse_inspire_hit(m: dict[str, Any]) -> Publication:
    """Turn one INSPIRE literature record (the `metadata` dict) into a Publication."""
    title = latex_to_text(m["titles"][0]["title"])
    arxiv = clean_arxiv(next((e["value"] for e in m.get("arxiv_eprints", [])), None))
    dois = [clean_doi(d["value"]) for d in m.get("dois", [])]
    doi = next((d for d in dois if d and not is_arxiv_doi(d)), None)
    pinfo = (m.get("publication_info") or [{}])[0]
    earliest = m.get("earliest_date") or ""
    year = int(pinfo.get("year") or earliest[:4] or date.today().year)
    doctype = (m.get("document_type") or ["article"])[0]
    venue = pinfo.get("journal_title")
    ptype = "preprint"
    if doctype == "thesis":
        ptype = "thesis"
        inst = ((m.get("thesis_info") or {}).get("institutions") or [{}])[0].get("name") or ""
        inst = re.sub(r"\s*\(main\)$", "", inst)
        inst = re.sub(r"^U\.\s+", "University of ", inst)
        inst = {"University of Heidelberg": "Heidelberg University"}.get(inst, inst)
        venue = f"PhD thesis, {inst}" if inst else (venue or "PhD thesis")
    elif doctype == "book":
        ptype = "book"
    elif venue:
        ptype = "software" if "open source softw" in venue.lower() else "article"
    venue = JOURNAL_NAMES.get(venue, venue)
    pages = pinfo.get("artid") or pinfo.get("page_start")
    pub = Publication(
        id=arxiv or doi or f"inspire:{m['control_number']}",
        title=title,
        authors=[short_author(a["full_name"]) for a in m.get("authors", [])],
        year=year,
        date=earliest if len(earliest) == 10 else f"{year}-01-01",
        type=ptype,
        venue=venue,
        volume=pinfo.get("journal_volume"),
        pages=pages,
        doi=doi,
        arxiv=arxiv,
        inspire=m.get("control_number"),
        citations=int(m.get("citation_count") or 0),
        abstract=pick_abstract(m.get("abstracts") or []),
    )
    pub.url = (
        f"https://arxiv.org/abs/{arxiv}" if arxiv
        else f"https://doi.org/{doi}" if doi
        else f"https://inspirehep.net/literature/{pub.inspire}"
    )
    return pub


def fetch_inspire(bai: str) -> list[Publication]:
    url = f"https://inspirehep.net/api/literature?q=a%20{bai}&size=100&sort=mostrecent&fields={INSPIRE_FIELDS}"
    data = http_get(url).json()
    return [parse_inspire_hit(h["metadata"]) for h in data.get("hits", {}).get("hits", [])]


def fetch_orcid_ids(orcid: str) -> list[dict[str, str | None]]:
    """Return [{arxiv, doi, title, year}] for every work on the ORCID record."""
    url = f"https://pub.orcid.org/v3.0/{orcid}/works"
    data = http_get(url, headers={"Accept": "application/json"}).json()
    out = []
    for group in data.get("group", []):
        ws = group["work-summary"][0]
        ids = group.get("external-ids", {}).get("external-id", [])
        arxiv = doi = None
        for e in ids:
            t, v = e.get("external-id-type"), e.get("external-id-value", "")
            if t == "arxiv":
                arxiv = arxiv or clean_arxiv(v)
            elif t == "doi":
                d = clean_doi(v)
                if is_arxiv_doi(d):
                    arxiv = arxiv or clean_arxiv(d.split("arxiv.", 1)[1])
                else:
                    doi = doi or d
        out.append({
            "arxiv": arxiv, "doi": doi,
            "title": ws["title"]["title"]["value"],
            "year": ((ws.get("publication-date") or {}).get("year") or {}).get("value"),
            "type": ws.get("type"),
        })
    return out


def fetch_inspire_by_id(arxiv: str | None, doi: str | None) -> Publication | None:
    """Look a single work up on INSPIRE when ORCID knows about it but the author query missed it."""
    q = f"arxiv:{arxiv}" if arxiv else f"doi:{doi}" if doi else None
    if not q:
        return None
    data = http_get(f"https://inspirehep.net/api/literature?q={q}&size=1&fields={INSPIRE_FIELDS}").json()
    hits = data.get("hits", {}).get("hits", [])
    return parse_inspire_hit(hits[0]["metadata"]) if hits else None


def fetch_arxiv_metadata(arxiv: str) -> Publication | None:
    """Fallback metadata straight from arXiv for works INSPIRE does not index."""
    import xml.etree.ElementTree as ET
    ns = {"a": "http://www.w3.org/2005/Atom", "ar": "http://arxiv.org/schemas/atom"}
    r = http_get(f"https://export.arxiv.org/api/query?id_list={arxiv}")
    root = ET.fromstring(r.text)
    entry = root.find("a:entry", ns)
    if entry is None or entry.find("a:title", ns) is None:
        return None
    title = latex_to_text(entry.find("a:title", ns).text or "")
    published = (entry.find("a:published", ns).text or "")[:10]
    authors = [a.find("a:name", ns).text for a in entry.findall("a:author", ns)]
    doi_el = entry.find("ar:doi", ns)
    jref = entry.find("ar:journal_ref", ns)
    doi = clean_doi(doi_el.text) if doi_el is not None else None
    return Publication(
        id=arxiv, title=title,
        authors=[short_author(a) for a in authors],
        year=int(published[:4]), date=published,
        type="article" if doi else "preprint",
        venue=jref.text if jref is not None else None,
        doi=doi, arxiv=arxiv, url=f"https://arxiv.org/abs/{arxiv}",
        abstract=latex_to_text(entry.find("a:summary", ns).text or "") or None,
    )


def fetch_crossref_metadata(doi: str) -> Publication | None:
    r = http_get(f"https://api.crossref.org/works/{doi}", headers={"Accept": "application/json"})
    m = r.json().get("message", {})
    if not m.get("title"):
        return None
    parts = (m.get("published") or m.get("issued") or {}).get("date-parts", [[None]])[0]
    year = int(parts[0] or date.today().year)
    d = f"{year}-{(parts[1] if len(parts) > 1 else 1):02d}-{(parts[2] if len(parts) > 2 else 1):02d}"
    authors = [short_author(f"{a.get('family','')}, {a.get('given','')}") for a in m.get("author", [])]
    venue = (m.get("container-title") or [None])[0]
    abstract = re.sub(r"<[^>]+>", "", m.get("abstract", "")) or None
    return Publication(
        id=doi, title=latex_to_text(m["title"][0]), authors=authors, year=year, date=d,
        type="article" if venue else "preprint", venue=venue, volume=m.get("volume"),
        pages=m.get("page"), doi=doi, url=f"https://doi.org/{doi}", abstract=abstract,
    )


# --------------------------------------------------------------------------- #
# Thumbnails
# --------------------------------------------------------------------------- #
def render_first_page(pdf_bytes: bytes, out_path: Path, width: int = 480) -> None:
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(pdf_bytes)
    try:
        page = pdf[0]
        try:
            w, h = page.get_size()
            scale = width / w
            bitmap = page.render(scale=scale * 2)  # 2x for a crisp downscale
            img = bitmap.to_pil().convert("RGB")
        finally:
            page.close()
    finally:
        pdf.close()
    img.thumbnail((width, int(width * h / w * 1.01)))
    # Crop to a consistent portrait ratio so cards line up.
    target_h = int(width * 1.3)
    img = img.crop((0, 0, width, min(img.height, target_h)))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "PNG", optimize=True)


def _load_font(candidates: list[str], size: int):
    """Find a TrueType font on Linux/macOS/GitHub runners; fall back to Pillow's built-in."""
    from PIL import ImageFont
    import glob
    for name in candidates:
        for pattern in (name, f"/usr/share/fonts/**/{name}", f"/usr/local/share/fonts/**/{name}",
                        f"{Path.home()}/.fonts/**/{name}", f"/Library/Fonts/**/{name}"):
            for path in ([pattern] if "*" not in pattern else glob.glob(pattern, recursive=True)):
                try:
                    return ImageFont.truetype(path, size)
                except OSError:
                    continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # very old Pillow
        return ImageFont.load_default()


def render_placeholder(pub: Publication, out_path: Path, width: int = 480) -> None:
    """A simple typographic card for works without a PDF (e.g. a thesis)."""
    from PIL import Image, ImageDraw, ImageFont
    h = int(width * 1.3)
    img = Image.new("RGB", (width, h), (23, 24, 28))
    d = ImageDraw.Draw(img)
    font = _load_font(["DejaVuSerif-Bold.ttf", "LiberationSerif-Bold.ttf", "FreeSerifBold.ttf"], 34)
    small = _load_font(["DejaVuSans.ttf", "LiberationSans-Regular.ttf", "FreeSans.ttf"], 19)
    d.rectangle((0, 0, width, 14), fill=(240, 139, 82))
    y = 64
    for line in textwrap.wrap(pub.title, width=24)[:9]:
        d.text((36, y), line, font=font, fill=(233, 231, 225))
        y += 44
    d.text((36, h - 90), ", ".join(pub.authors)[:60], font=small, fill=(166, 170, 179))
    d.text((36, h - 60), f"{pub.venue or pub.type.title()} · {pub.year}"[:60], font=small, fill=(166, 170, 179))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "PNG", optimize=True)


def make_thumbnail(pub: Publication, thumb_dir: Path) -> str | None:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", pub.id)
    out = thumb_dir / f"{safe}.png"
    try:
        if pub.arxiv:
            log(f"    downloading arXiv PDF for {pub.arxiv}")
            pdf = http_get(f"https://arxiv.org/pdf/{pub.arxiv}").content
            render_first_page(pdf, out)
        else:
            log("    no arXiv id; generating placeholder card")
            render_placeholder(pub, out)
        return "/" + out.relative_to(ROOT).as_posix()
    except Exception as e:  # noqa: BLE001
        log(f"    thumbnail failed: {e}")
        return None


# --------------------------------------------------------------------------- #
# Descriptions
# --------------------------------------------------------------------------- #
DESCRIPTION_SYSTEM = """You write one-paragraph summaries of physics papers for the personal website of one of the authors.
Audience: curious non-specialists and physicists outside the subfield. Voice: confident, warm, plain English, first person plural is fine ("we show").
Rules: 2 sentences, at most 55 words total. Lead with why the result matters, then what was done. No hype words (groundbreaking, novel, revolutionary), no jargon that a physics undergraduate would not know, no equations, no citations, no quotation marks. Output only the paragraph."""


def _claude_request(client, prompt: str, use_fallbacks: bool):
    kwargs = dict(
        model="claude-opus-5",
        max_tokens=1024,
        output_config={"effort": "medium"},
        system=DESCRIPTION_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    if use_fallbacks:
        # Server-side refusal fallback: if the model declines, the API re-runs the
        # request on a fallback model inside the same call.
        return client.beta.messages.create(
            betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs
        )
    return client.messages.create(**kwargs)


def describe_with_claude(pub: Publication) -> str | None:
    try:
        import anthropic
    except ImportError:
        DESCRIPTION_STATS["last_error"] = "anthropic package not installed (run with .venv/bin/python, or pip install -r scripts/requirements.txt)"
        log("    anthropic package not installed; run with .venv/bin/python or pip install -r scripts/requirements.txt. Using abstract fallback")
        return None
    key, source = resolve_api_key()
    profile_exists = os.environ.get("ANTHROPIC_AUTH_TOKEN") or (Path.home() / ".config" / "anthropic").exists()
    if not key and not profile_exists:
        DESCRIPTION_STATS["last_error"] = f"no credentials: {source}"
        log(f"    no Claude credentials ({source}); using abstract fallback")
        return None
    try:
        # Pass the key explicitly rather than exporting it, so child processes never inherit it.
        # Keys created at organisation level (not inside a workspace) must name a workspace per request.
        headers = {}
        ws = resolve_workspace_id(CONFIG.get("workspace_id"))
        if ws:
            headers["anthropic-workspace-id"] = ws
        client = anthropic.Anthropic(api_key=key, default_headers=headers) if key else anthropic.Anthropic(default_headers=headers)
    except Exception as e:  # noqa: BLE001
        DESCRIPTION_STATS["last_error"] = f"client init failed: {e}"
        log(f"    could not initialise the Claude client ({e}); using abstract fallback")
        return None
    prompt = (
        f"Title: {pub.title}\n"
        f"Authors: {', '.join(pub.authors)}\n"
        f"Venue: {pub.venue or 'preprint'} ({pub.year})\n"
        f"Abstract:\n{pub.abstract or '(no abstract available; infer from the title)'}\n"
    )
    try:
        try:
            resp = _claude_request(client, prompt, use_fallbacks=True)
        except (anthropic.BadRequestError, TypeError) as e:
            # The fallback beta is optional; if this API version rejects it, retry without.
            log(f"    fallback beta not accepted ({str(e)[:80]}); retrying without it")
            resp = _claude_request(client, prompt, use_fallbacks=False)
        if resp.stop_reason == "refusal":
            DESCRIPTION_STATS["last_error"] = "model declined the request"
            log("    model declined to summarise; using abstract fallback")
            return None
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        text = re.sub(r"\s+", " ", text).strip().strip('"')
        if text:
            DESCRIPTION_STATS["claude"] += 1
            return text
        DESCRIPTION_STATS["last_error"] = "empty response"
        return None
    except anthropic.AuthenticationError as e:
        DESCRIPTION_STATS["last_error"] = f"authentication failed (is the key valid?): {e.message}"
        log(f"    Claude API authentication failed: {e.message}; using abstract fallback")
    except anthropic.RateLimitError as e:
        DESCRIPTION_STATS["last_error"] = f"rate limited: {e.message}"
        log(f"    Claude API rate limit: {e.message}; using abstract fallback")
    except anthropic.APIStatusError as e:
        msg = e.message
        if "workspace" in msg.lower():
            msg += " -> either create the key inside a workspace in the Anthropic Console, or set ANTHROPIC_WORKSPACE_ID / publications.anthropic_workspace_id in _config.yml"
        DESCRIPTION_STATS["last_error"] = f"HTTP {e.status_code}: {msg}"
        log(f"    Claude API error {e.status_code}: {e.message}; using abstract fallback")
    except anthropic.APIConnectionError as e:
        DESCRIPTION_STATS["last_error"] = f"connection error: {e}"
        log(f"    Claude API connection error: {e}; using abstract fallback")
    except Exception as e:  # noqa: BLE001
        DESCRIPTION_STATS["last_error"] = f"{e.__class__.__name__}: {e}"
        log(f"    unexpected error from Claude API: {e}; using abstract fallback")
    return None


def describe(pub: Publication) -> str:
    text = describe_with_claude(pub)
    if text:
        return text
    DESCRIPTION_STATS["fallback"] += 1
    if pub.abstract:
        return first_sentences(pub.abstract)
    return f"{pub.title} ({pub.venue or pub.type}, {pub.year})."


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def load_config() -> dict[str, Any]:
    cfg = yaml.safe_load((ROOT / "_config.yml").read_text())
    pubcfg = cfg.get("publications", {})
    CONFIG.update({
        "bai": pubcfg.get("inspire_bai"),
        "orcid": pubcfg.get("orcid"),
        "data_file": ROOT / pubcfg.get("data_file", "_data/publications.yml"),
        "thumb_dir": ROOT / pubcfg.get("thumbnail_dir", "assets/img/publications"),
        "featured_count": int(pubcfg.get("featured_count", 4)),
        "workspace_id": pubcfg.get("anthropic_workspace_id") or None,
    })
    return CONFIG


def load_existing(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text()) or []
    return {str(d["id"]): d for d in data}


def merge_sources(bai: str | None, orcid: str | None) -> dict[str, Publication]:
    found: dict[str, Publication] = {}
    by_arxiv: dict[str, str] = {}
    by_doi: dict[str, str] = {}

    def add(p: Publication) -> None:
        # De-duplicate on arXiv id and DOI, preferring the richer INSPIRE record.
        key = None
        if p.arxiv and p.arxiv in by_arxiv:
            key = by_arxiv[p.arxiv]
        elif p.doi and p.doi in by_doi:
            key = by_doi[p.doi]
        if key:
            existing = found[key]
            for f in ("doi", "venue", "volume", "pages", "abstract"):
                if getattr(existing, f) is None and getattr(p, f) is not None:
                    setattr(existing, f, getattr(p, f))
            return
        found[p.id] = p
        if p.arxiv:
            by_arxiv[p.arxiv] = p.id
        if p.doi:
            by_doi[p.doi] = p.id

    if bai:
        log(f"Querying INSPIRE-HEP for author {bai} …")
        inspire = fetch_inspire(bai)
        log(f"  {len(inspire)} records")
        for p in inspire:
            add(p)

    if orcid:
        log(f"Querying ORCID {orcid} …")
        works = fetch_orcid_ids(orcid)
        log(f"  {len(works)} works")
        for w in works:
            if (w["arxiv"] and w["arxiv"] in by_arxiv) or (w["doi"] and w["doi"] in by_doi):
                continue
            log(f"  ORCID-only work: {w['title']!r} (arxiv={w['arxiv']}, doi={w['doi']})")
            p = None
            try:
                p = fetch_inspire_by_id(w["arxiv"], w["doi"])
            except Exception as e:  # noqa: BLE001
                log(f"    INSPIRE lookup failed: {e}")
            if p is None and w["arxiv"]:
                try:
                    p = fetch_arxiv_metadata(w["arxiv"])
                except Exception as e:  # noqa: BLE001
                    log(f"    arXiv lookup failed: {e}")
            if p is None and w["doi"]:
                try:
                    p = fetch_crossref_metadata(w["doi"])
                except Exception as e:  # noqa: BLE001
                    log(f"    Crossref lookup failed: {e}")
            if p is not None:
                add(p)
            else:
                log("    could not resolve metadata; skipping")
    return found


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="report what would change without writing")
    ap.add_argument("--regen-thumbnails", action="store_true", help="re-render every thumbnail")
    ap.add_argument("--regen-descriptions", action="store_true", help="re-generate every description")
    ap.add_argument("--no-thumbnails", action="store_true")
    ap.add_argument("--no-descriptions", action="store_true")
    ap.add_argument("--check-api", action="store_true", help="make one small Claude API call and report the result, then exit")
    ap.add_argument("--forget", metavar="ID", action="append", default=[],
                    help="drop this entry (arXiv id / DOI) and its thumbnail before syncing, so it is re-discovered as new; for testing")
    ap.add_argument("--set-key", action="store_true", help="store the Anthropic API key in the OS keyring (prompts, no echo)")
    ap.add_argument("--delete-key", action="store_true", help="remove the Anthropic API key from the OS keyring")
    args = ap.parse_args(argv)

    if args.set_key:
        return store_api_key()
    if args.delete_key:
        return delete_api_key()

    if args.check_api:
        load_config()
        probe = Publication(id="probe", title="Positive energy warp drive from hidden geometric structures",
                            authors=["S. D. B. Fell", "L. Heisenberg"], year=2021, date="2021-04-13",
                            venue="Classical and Quantum Gravity", type="article",
                            abstract="A geometrical interpretation of the Eulerian energy of warp drive spacetimes is found, allowing superluminal solitonic spacetimes with positive semi-definite energy.")
        _, source = resolve_api_key()
        log(f"Credential source: {source}")
        ws = resolve_workspace_id(CONFIG.get("workspace_id"))
        log(f"Workspace header: {ws or 'not set (correct for a workspace-scoped key)'}")
        text = describe_with_claude(probe)
        if text:
            log("Claude API OK. Sample description:")
            log(f"  {text}")
            return 0
        log(f"Claude API NOT working: {DESCRIPTION_STATS['last_error']}")
        return 1

    cfg = load_config()
    if not (cfg["bai"] or cfg["orcid"]):
        log("No inspire_bai or orcid configured in _config.yml under `publications:`")
        return 2

    existing = load_existing(cfg["data_file"])
    for fid in args.forget:
        if fid in existing:
            thumb = existing[fid].get("thumbnail")
            if thumb and not args.dry_run:
                (ROOT / str(thumb).lstrip("/")).unlink(missing_ok=True)
            del existing[fid]
            log(f"Forgetting {fid} so it is treated as new (test mode)")
        else:
            log(f"--forget {fid}: no such entry; ignoring")
    remote = merge_sources(cfg["bai"], cfg["orcid"])

    added, updated, unchanged = [], [], []
    merged: list[dict[str, Any]] = []

    for key, pub in remote.items():
        if key in existing:
            old = existing[key]
            new = dict(old)
            changed = []
            fresh = pub.to_yaml_dict()
            for f in LIVE_FIELDS:
                if f in fresh and fresh[f] != old.get(f):
                    # Do not downgrade an article to a preprint if INSPIRE lags.
                    if f == "type" and old.get("type") in ("article", "software") and fresh[f] == "preprint":
                        continue
                    new[f] = fresh[f]
                    changed.append(f)
            if not old.get("abstract") and pub.abstract:
                new["abstract"] = pub.abstract
            thumb_missing = bool(old.get("thumbnail")) and not (ROOT / str(old["thumbnail"]).lstrip("/")).exists()
            if not old.get("thumbnail") or thumb_missing or args.regen_thumbnails:
                if not args.no_thumbnails and not args.dry_run:
                    log(f"  thumbnail for existing entry: {pub.title[:60]}")
                    t = make_thumbnail(pub, cfg["thumb_dir"])
                    if t:
                        new["thumbnail"] = t
                        changed.append("thumbnail")
            if not old.get("description") or args.regen_descriptions:
                if not args.no_descriptions and not args.dry_run:
                    log(f"  description for existing entry: {pub.title[:60]}")
                    new["description"] = describe(pub)
                    changed.append("description")
            merged.append(new)
            (updated if changed else unchanged).append((pub.title, changed))
        else:
            log(f"NEW: {pub.title}  [{pub.id}]")
            if not args.dry_run:
                if not args.no_thumbnails:
                    pub.thumbnail = make_thumbnail(pub, cfg["thumb_dir"])
                if not args.no_descriptions:
                    pub.description = describe(pub)
            merged.append(pub.to_yaml_dict())
            added.append(pub.title)

    # Keep entries that exist locally but vanished remotely (e.g. manually added).
    remote_keys = set(remote)
    for key, old in existing.items():
        if key not in remote_keys:
            log(f"Keeping local-only entry: {old.get('title')}")
            merged.append(old)

    # Newest first; break ties on title for a stable diff.
    merged.sort(key=lambda d: (str(d.get("date", "")), d.get("title", "")), reverse=True)

    # Auto-feature the newest N if nothing is featured yet.
    if not any(d.get("featured") for d in merged):
        for d in merged[: cfg["featured_count"]]:
            d["featured"] = True

    log("")
    log(f"Summary: {len(added)} new, {len([u for u in updated if u[1]])} updated, {len(unchanged)} unchanged")
    for t in added:
        log(f"  + {t}")
    for t, ch in updated:
        if ch:
            log(f"  ~ {t}  ({', '.join(sorted(set(ch)))})")

    if DESCRIPTION_STATS["claude"] or DESCRIPTION_STATS["fallback"]:
        log(f"Descriptions: {DESCRIPTION_STATS['claude']} written by Claude, {DESCRIPTION_STATS['fallback']} taken from abstracts"
            + (f" (reason: {DESCRIPTION_STATS['last_error']})" if DESCRIPTION_STATS["fallback"] else ""))
        if DESCRIPTION_STATS["fallback"] and os.environ.get("GITHUB_ACTIONS"):
            log(f"::warning::{DESCRIPTION_STATS['fallback']} description(s) fell back to the abstract: {DESCRIPTION_STATS['last_error']}")

    if args.dry_run:
        log("Dry run: nothing written.")
        return 0

    header = (
        "# Publications. This file is maintained by scripts/update_publications.py\n"
        "# (run weekly by GitHub Actions). You may edit it by hand: `description`,\n"
        "# `thumbnail`, `featured`, `hidden`, `code` and `title` are never overwritten\n"
        "# by the script. Citation counts and journal details are refreshed automatically.\n"
        f"# Last updated: {date.today().isoformat()}\n"
    )
    body = yaml.safe_dump(merged, sort_keys=False, allow_unicode=True, width=100)
    cfg["data_file"].parent.mkdir(parents=True, exist_ok=True)
    cfg["data_file"].write_text(header + body)
    log(f"Wrote {cfg['data_file'].relative_to(ROOT)}")
    # Expose a flag for the workflow.
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as fh:
            fh.write(f"added={len(added)}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
