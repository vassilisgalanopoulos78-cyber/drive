#!/usr/bin/env python3
"""Μετονομασία και μετατροπή σε Markdown (ή σε PDF) των σελίδων του Qualex που αποθηκεύει ο χρήστης.

Ο φυλλομετρητής αποθηκεύει κάθε άρθρο του Qualex ως .htm με φάκελο «_files» δίπλα,
με τυχαίο όνομα, με όλο το μενού, τα cookies και το όνομα του συνδεδεμένου λογαριασμού
στην κεφαλίδα. Το script κρατά μόνο τα στοιχεία του άρθρου (τίτλος, συγγραφέας,
πηγή, ημερομηνία, περίληψη, σχετική νομοθεσία και νομολογία) και το κείμενο του
τμήματος «Κείμενο», το γράφει σε Markdown, ή με --pdf σε PDF με το LibreOffice, και
του δίνει όνομα κατά τη μορφή των υπολοίπων άρθρων, «<Περιοδικό> <έτος> <Επώνυμο> -
<Τίτλος>.md» (οδηγία του χρήστη της 1.10.2026, «Ας είναι markdown ό,τι βολεύει»).

Το αρχείο γράφεται μόνο αν περιέχει τουλάχιστον το 90% των λέξεων πέντε και περισσότερων
γραμμάτων του κειμένου της σελίδας. Με --apply το .htm και ο φάκελος «_files» του
σβήνονται (στο G: του Google Drive πηγαίνουν στον κάδο, όπου μένουν τριάντα ημέρες).
Χωρίς --apply γίνεται μόνο έλεγχος. Οι φάκελοι υποθέσεων (cases-folders.txt) δεν
αγγίζονται, ούτε σελίδες που έχουν ήδη εγγραφή στο manifest.tsv, τις οποίες χειρίζεται
το web-to-pdf.py με επανασύνδεση της ταυτότητας. Κάθε ενέργεια γράφεται στο
qualex-se-md-log.tsv. Με --md-out ΑΡΧΕΙΟ μετατρέπει μία μόνο σελίδα, χωρίς να σβήσει
τίποτε (χρήσιμο όπου το Drive δεν είναι τοπικό και το αποτέλεσμα ανεβαίνει αλλιώς).

Χρήση:
  python qualex-se-md.py [ΡΙΖΑ ...] [--apply] [--pdf] [--cases cases-folders.txt]
                         [--manifest manifest.tsv] [--log qualex-se-md-log.tsv]
  python qualex-se-md.py ΣΕΛΙΔΑ.htm --md-out ΑΡΧΕΙΟ.md
Τρέχει στην ενημέρωση πριν από το drive-index.sh, ώστε οι σελίδες να ευρετηριάζονται
κατευθείαν στη νέα τους μορφή.
"""
import argparse
import datetime
import html
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
from html.parser import HTMLParser

DEFAULT_ROOT = r"G:\Το Drive μου\Claude Νομολογία Αρθρογραφία Σχέδια οδηγίες ευρετήρια"
SKIP_DIRS = {".tmp.driveupload", ".tmp.drivedownload", "_Ευρετήριο Claude", "Μνήμη Claude"}
MIN_COVERAGE = 0.90
KEEP_TAGS = {"p", "br", "strong", "b", "em", "i", "u", "sup", "sub", "ul", "ol", "li",
             "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "table", "thead", "tbody",
             "tr", "td", "th"}
DROP_CONTENT = {"script", "style", "noscript", "button", "svg", "iframe", "form"}


# Ανάγνωση της σελίδας

class Sanitizer(HTMLParser):
    """Κρατά μόνο απλές ετικέτες χωρίς ιδιότητες, ώστε να μείνει το κείμενο με τη μορφή του."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []
        self.drop = 0

    def handle_starttag(self, tag, attrs):
        if tag in DROP_CONTENT:
            self.drop += 1
        elif not self.drop and tag in KEEP_TAGS:
            self.out.append("<br>" if tag == "br" else "<%s>" % tag)
        elif not self.drop and tag == "div":
            self.out.append("<br>")

    def handle_startendtag(self, tag, attrs):
        if not self.drop and tag == "br":
            self.out.append("<br>")

    def handle_endtag(self, tag):
        if tag in DROP_CONTENT:
            self.drop = max(0, self.drop - 1)
        elif not self.drop and tag in KEEP_TAGS and tag != "br":
            self.out.append("</%s>" % tag)

    def handle_data(self, data):
        if not self.drop:
            self.out.append(html.escape(data, quote=False))


def sanitize(fragment):
    s = Sanitizer()
    s.feed(fragment)
    s.close()
    out = "".join(s.out)
    out = re.sub(r"(?:\s*<br>\s*){3,}", "<br><br>", out)
    return out.strip()


def text_lines(page):
    t = re.sub(r"(?is)<(script|style|noscript)\b.*?</\1>", "", page)
    t = re.sub(r"(?i)<br\s*/?>|</(p|div|h\d|li|tr|td|section|nav|ul)>", "\n", t)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t))
    lines = (re.sub(r"[ \t\xa0\u200e]+", " ", l).strip() for l in t.split("\n"))
    return [l for l in lines if l]


def section_by_label(page, label_id):
    """Το περιεχόμενο του <section aria-labelledby=label_id>, με ισορροπία των ετικετών section."""
    m = re.search(r'<section\b[^>]*aria-labelledby="%s"[^>]*>' % re.escape(label_id), page)
    if not m:
        return None
    depth, pos = 1, m.end()
    for t in re.finditer(r"<(/?)section\b[^>]*>", page[pos:]):
        depth += -1 if t.group(1) else 1
        if depth == 0:
            return page[pos:pos + t.start()]
    return None


def value_after(lines, label, start=0, stop=None):
    for i in range(start, len(lines) if stop is None else stop):
        if lines[i] == label and i + 1 < len(lines):
            return lines[i + 1]
    return ""


def parse_qualex(page):
    head = page[:20000]
    if not re.search(r"<title>[^<]*\|\s*Qualex\s*</title>", head, re.I):
        return None
    lines = text_lines(page)
    try:
        start = next(i for i, l in enumerate(lines) if l.startswith("Πίσω στα αποτελέσματα"))
        end = lines.index("Κείμενο", start)
    except (StopIteration, ValueError):
        return None
    meta = {"title": lines[start + 1], "author": value_after(lines, "Συγγραφέας:", start, end),
            "year": value_after(lines, "Έτος:", start, end), "kind": value_after(lines, "Είδος:", start, end),
            "date": value_after(lines, "Ημ. Δημοσίευσης:", start, end),
            "words": value_after(lines, "Αρ. Λέξεων:", start, end)}
    # Η πηγή είναι οι γραμμές μεταξύ «Μέσο Δημοσίευσης:» και «Ημ. Δημοσίευσης:».
    src = []
    if "Μέσο Δημοσίευσης:" in lines[start:end]:
        i = lines.index("Μέσο Δημοσίευσης:", start, end) + 1
        while i < end and lines[i] != "Ημ. Δημοσίευσης:" and not lines[i].endswith(":"):
            src.append(lines[i])
            i += 1
    meta["medium"] = " ".join(s for s in src if s.upper() != "ΤΝΠ QUALEX")
    meta["source"] = src
    # Περίληψη.
    summ = []
    if "Περίληψη" in lines[start:end]:
        i = lines.index("Περίληψη", start, end) + 1
        while i < end and not lines[i].startswith("Εμφάνιση "):
            summ.append(lines[i])
            i += 1
    meta["summary"] = summ
    # Σχετική νομοθεσία και νομολογία: μετά τις επικεφαλίδες τους ως το «Κείμενο».
    rel = []
    heads = [k for k in range(start, end) if re.match(r"Σχετική (Νομοθεσία|Νομολογία) \(\d+\)$", lines[k])]
    if heads:
        rel = [l for l in lines[heads[-1] + 1:end] if not l.startswith("Εμφάνιση ")]
    meta["related_heads"] = [lines[k] for k in heads]
    meta["related"] = rel
    body = section_by_label(page, "ArticleContent")
    if not body:
        return None
    body = re.sub(r'(?is)<h2[^>]*id="ArticleContent"[^>]*>.*?</h2>', "", body)
    meta["body_html"] = sanitize(body)
    meta["body_text"] = " ".join(text_lines(body))
    return meta


# Όνομα αρχείου

def surname(author):
    name = author.split(",")[0].strip()
    parts = name.split()
    return parts[-1] if parts else ""


def short_title(title, limit=60):
    t = re.sub(r'[\\/:*?"<>|]', "-", title)
    t = re.sub(r"\s+", " ", t).strip(" .")
    if len(t) <= limit:
        return t
    cut = t[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(" -,.;:")


def pdf_name(meta):
    medium = meta["medium"]
    m = re.match(r"\s*([^,]+?)\s*,\s*([^,]*?)\s*(?:,|$)", medium)
    journal = m.group(1).strip() if m else ""
    year = ""
    if m:
        y = re.search(r"(19|20)\d\d", m.group(2))
        year = y.group(0) if y else ""
    year = year or meta["year"]
    journal = re.sub(r'[\\/:*?"<>|]', "-", journal)
    prefix = " ".join(x for x in (journal, year, surname(meta["author"])) if x)
    return "%s - %s.pdf" % (prefix, short_title(meta["title"])) if prefix else short_title(meta["title"]) + ".pdf"


# Παραγωγή PDF

def build_html(meta):
    e = lambda s: html.escape(s, quote=False)
    src = ", ".join(s.replace(" , ", ", ") for s in meta["source"])
    parts = ["<!DOCTYPE html><html lang='el'><head><meta charset='utf-8'><title>%s</title>" % e(meta["title"]),
             "<style>body{font-family:'Times New Roman',serif;font-size:12pt;line-height:1.4}"
             "h1{font-size:15pt}p.m{margin:0}</style></head><body>",
             "<h1>%s</h1>" % e(meta["title"])]
    for label, key in (("Συγγραφέας", "author"), ("Είδος", "kind"), ("Ημ. δημοσίευσης", "date"), ("Αρ. λέξεων", "words")):
        if meta.get(key):
            parts.append("<p class='m'><b>%s:</b> %s</p>" % (label, e(meta[key])))
        if key == "author" and src:
            parts.append("<p class='m'><b>Πηγή:</b> %s</p>" % e(src))
    if meta["summary"]:
        parts.append("<h2>Περίληψη</h2><p>%s</p>" % e(" ".join(meta["summary"])))
    if meta["related"]:
        parts.append("<h2>%s</h2>" % e(" και ".join(meta["related_heads"])))
        parts.extend("<p class='m'>%s</p>" % e(r) for r in meta["related"])
    parts.append("<h2>Κείμενο</h2>")
    parts.append(meta["body_html"])
    parts.append("</body></html>")
    return "\n".join(parts)


class MdWriter(HTMLParser):
    """Από το καθαρισμένο HTML σε Markdown: έντονα, πλάγια, παράγραφοι και πίνακες."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks, self.cur = [], []
        self.table = None
        self.row = None
        self.cell = None

    def _buf(self):
        return self.cell if self.cell is not None else self.cur

    def _flush(self):
        text = md_inline("".join(self.cur))
        if text:
            self.blocks.append(text)
        self.cur = []

    def handle_starttag(self, tag, attrs):
        if tag in ("strong", "b"):
            self._buf().append("\x01")
        elif tag in ("em", "i"):
            self._buf().append("\x02")
        elif tag == "br" or tag in ("p", "li", "blockquote") or tag.startswith("h"):
            if self.cell is not None:
                self.cell.append(" ")
            else:
                self._flush()
        elif tag == "table":
            self._flush()
            self.table = []
        elif tag == "tr" and self.table is not None:
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.cell = []

    def handle_endtag(self, tag):
        if tag in ("strong", "b"):
            self._buf().append("\x01")
        elif tag in ("em", "i"):
            self._buf().append("\x02")
        elif tag in ("p", "li", "blockquote") or (tag.startswith("h") and tag[1:].isdigit()):
            if self.cell is None:
                self._flush()
        elif tag in ("td", "th") and self.cell is not None:
            self.row.append(md_inline("".join(self.cell)).replace("|", "\\|"))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            if any(self.row):
                self.table.append(self.row)
            self.row = None
        elif tag == "table" and self.table is not None:
            self.blocks.extend(md_table(self.table))
            self.table = None

    def handle_data(self, data):
        self._buf().append(data)

    def result(self):
        self._flush()
        return self.blocks


def md_inline(text):
    """Έντονα και πλάγια χωρίς κενά μέσα στους δείκτες, ενιαία κενά, διαφυγή αρχής γραμμής."""
    text = re.sub(r"\s+", " ", text)
    for mark, md in (("\x01", "**"), ("\x02", "*")):
        parts = text.split(mark)
        out = parts[0]
        for k in range(1, len(parts), 2):
            inner = parts[k]
            rest = parts[k + 1] if k + 1 < len(parts) else ""
            core = inner.strip()
            if core:
                lead = " " if inner[:1].isspace() else ""
                trail = " " if inner[-1:].isspace() else ""
                out += lead + md + core + md + trail + rest
            else:
                out += inner + rest
        text = out
    text = re.sub(r"\*\*\s*\*\*", " ", text)
    text = re.sub(r" {2,}", " ", text).strip()
    text = re.sub(r"^([-+*])(?=\s)", r"\\\1", text)
    text = re.sub(r"^([#>])", r"\\\1", text)
    return re.sub(r"^(\d+)\. ", r"\1\\. ", text)


def md_table(rows):
    if all(len(r) == 1 for r in rows):
        return [r[0] for r in rows if r[0]]
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    out = ["| " + " | ".join(rows[0]) + " |", "|" + " --- |" * width]
    out += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return ["\n".join(out)]


PAGE_RE = re.compile(r"Σελ\.\s?(\d+)(\s*)(.*)", re.S)
SENTENCE_END = tuple(".;:!?»)…\"'")


def page_markers(blocks):
    """Οι ενδείξεις «Σελ. N» του Qualex αρχίζουν νέα γραμμή και κόβουν πρόταση ή και λέξη.
    Γίνονται δείκτες <!-- σελ. N -->, με επανένωση της πρότασης και της λέξης."""
    out, found = [], False
    vocab = {}
    for w in re.findall(r"[^\W\d_]+", " ".join(blocks).lower()):
        vocab[w] = vocab.get(w, 0) + 1

    def fragment(w):
        w = re.sub(r"[^\w]", "", w.lower())
        return bool(w) and vocab.get(w, 0) <= 1
    def cut_greek(w):
        """Ελληνική λέξη που δεν στέκει μόνη: πολυσύλλαβη χωρίς τόνο ή μονοσύλλαβη με τόνο."""
        w = re.sub(r"[^\w]", "", w)
        if not w or not re.fullmatch(r"[α-ωάέήίόύώϊϋΐΰς]+", w) or not fragment(w):
            return False
        syll = len(re.findall(r"[αεηιουωάέήίόύώϊϋΐΰ]+", w))
        accent = bool(re.search(r"[άέήίόύώΐΰ]", w))
        return (syll >= 2 and not accent) or (syll == 1 and accent and w not in ("ή", "πώς", "πού"))
    for b in blocks:
        m = PAGE_RE.match(b)
        if not m or not out:
            out.append(b)
            continue
        found = True
        num, space, rest = m.groups()
        mark = "<!-- σελ. %s -->" % num
        prev = out[-1]
        if prev.rstrip().endswith(SENTENCE_END):
            out.append((mark + " " + rest).strip())
        elif rest[:1].islower() and (not space or cut_greek(prev.split()[-1])
                                     or (fragment(prev.split()[-1]) and fragment(rest.split()[0]))):
            # Λέξη κομμένη στην αλλαγή σελίδας, χωρίς κενό μετά τον αριθμό ή με δύο κομμάτια
            # που δεν απαντούν αλλού στο κείμενο («συμπε» / «ριλαμβανομένων»).
            word, _, tail = rest.partition(" ")
            out[-1] = prev + word + " " + mark + (" " + tail if tail else "")
        else:
            out[-1] = prev.rstrip() + " " + mark + (" " + rest if rest else "")
    return out, found


def build_md(meta, stamp):
    src = ", ".join(s.replace(" , ", ", ") for s in meta["source"])
    lines = ["# " + md_inline(meta["title"]), ""]
    for label, key in (("Συγγραφέας", "author"), ("Πηγή", None), ("Είδος", "kind"),
                       ("Ημ. δημοσίευσης", "date"), ("Αρ. λέξεων", "words")):
        value = src if key is None else meta.get(key, "")
        if value:
            lines += ["**%s:** %s" % (label, md_inline(value)), ""]
    w = MdWriter()
    w.feed(meta["body_html"])
    w.close()
    blocks, found = page_markers(w.result())
    first = re.search(r"σελ\.\s*(\d+)", src)
    if found:
        pages = ("Οι αλλαγές σελίδας του περιοδικού σημειώνονται με δείκτες «σελ. N» (σχόλια HTML), "
                 "στο σημείο όπου τις δίνει η σελίδα, και ελέγχονται στο έντυπο πριν από παράθεση.")
        if first:
            blocks.insert(0, "<!-- σελ. %s -->" % first.group(1))
    else:
        pages = ("Η σελίδα δεν δίνει τη σελιδαρίθμηση του περιοδικού μέσα στο κείμενο, οπότε πριν από "
                 "παράθεση σε δικόγραφο ή γνωμοδότηση η σελίδα ελέγχεται στο έντυπο.")
    lines += ["*Μετατροπή από αποθηκευμένη σελίδα της ΤΝΠ Qualex στις %s με το qualex-se-md.py. %s*"
              % (stamp[:10], pages), ""]
    if meta["summary"]:
        lines += ["## Περίληψη", "", md_inline(" ".join(meta["summary"])), ""]
    if meta["related"]:
        lines += ["## " + " και ".join(meta["related_heads"]), ""]
        for r in meta["related"]:
            lines += [md_inline(r), ""]
    lines += ["## Κείμενο", ""]
    for b in blocks:
        lines += [b, ""]
    return "\n".join(lines).rstrip() + "\n"


def md_name(meta):
    return pdf_name(meta)[:-4] + ".md"


def find_converters():
    """Πρώτα το LibreOffice, όπως στο web-to-pdf.py, και εφεδρικά Chromium (μεταβλητή CHROME)."""
    soffice = next((c for c in (os.environ.get("SOFFICE"), shutil.which("soffice"), shutil.which("libreoffice"),
                                r"C:\Program Files\LibreOffice\program\soffice.exe",
                                r"C:\Program Files (x86)\LibreOffice\program\soffice.exe")
                    if c and os.path.exists(c)), None)
    chrome = next((c for c in (os.environ.get("CHROME"), "/opt/pw-browsers/chromium",
                               shutil.which("chromium"), shutil.which("google-chrome"))
                   if c and os.path.exists(c)), None)
    if not soffice and not chrome:
        sys.exit("Δεν βρέθηκε το LibreOffice (soffice). Ορίστε τη μεταβλητή SOFFICE.")
    return soffice, chrome


def to_pdf(html_text, converters, workdir):
    soffice, chrome = converters
    src = os.path.join(workdir, "page.html")
    with open(src, "w", encoding="utf-8") as f:
        f.write(html_text)
    pdf = os.path.join(workdir, "page.pdf")
    if soffice:
        profile = "file:///" + os.path.join(workdir, "lo-profile").replace("\\", "/").lstrip("/")
        subprocess.run([soffice, "-env:UserInstallation=" + profile, "--headless",
                        "--convert-to", "pdf", "--outdir", workdir, src],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=300)
    if not os.path.exists(pdf) and chrome:
        subprocess.run([chrome, "--headless", "--no-sandbox", "--disable-gpu", "--no-pdf-header-footer",
                        "--print-to-pdf=" + pdf, pathlib.Path(src).resolve().as_uri()],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=300)
    if not os.path.exists(pdf):
        raise RuntimeError("δεν γράφτηκε PDF")
    return pdf


def pdf_text(pdf):
    exe = shutil.which("pdftotext")
    if exe:
        return subprocess.run([exe, "-enc", "UTF-8", pdf, "-"], capture_output=True, check=True).stdout.decode("utf-8", "replace")
    try:
        import pypdfium2 as pdfium
        doc = pdfium.PdfDocument(pdf)
        return "\n".join(doc[i].get_textpage().get_text_range() for i in range(len(doc)))
    except ImportError:
        import fitz
        return "\n".join(p.get_text() for p in fitz.open(pdf))


def words5(text):
    return re.findall(r"[^\W\d_]{5,}", text.lower())


def coverage(meta, text):
    # Μέτρο είναι το αρχικό κείμενο της σελίδας και όχι το καθαρισμένο, ώστε να φαίνεται και ό,τι χάθηκε στον καθαρισμό.
    expected = words5(meta["body_text"])
    got = set(words5(text.replace("\u00ad", "")))
    if not expected:
        return 0.0
    return sum(1 for w in expected if w in got) / len(expected)


# Σάρωση

def load_cases(path, root):
    out = []
    if path and os.path.exists(path):
        for line in open(path, encoding="utf-8-sig"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("/g/"):
                line = "G:" + line[2:]
            p = line if os.path.isabs(line) else os.path.join(root, line)
            out.append(os.path.normcase(os.path.normpath(p)))
    return out


def to_g(path):
    p = os.path.abspath(path).replace("\\", "/")
    return "/" + p[0].lower() + p[2:] if re.match(r"[A-Za-z]:", p) else p


def load_manifest(path):
    if not path or not os.path.exists(path):
        return set()
    with open(path, encoding="utf-8", errors="replace") as f:
        return {cols[2] for cols in (l.rstrip("\n").split("\t") for l in f) if len(cols) > 2}


def walk(root):
    stack = [root]
    while stack:
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    if e.is_dir(follow_symlinks=False):
                        if e.name not in SKIP_DIRS and not e.name.endswith("_files"):
                            stack.append(e.path)
                    elif e.name.lower().endswith((".htm", ".html")):
                        yield e.path
        except OSError:
            pass


def unique(path):
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    n = 2
    while os.path.exists("%s (%d)%s" % (base, n, ext)):
        n += 1
    return "%s (%d)%s" % (base, n, ext)


def convert(meta, path, a, converters, stamp):
    """Γράφει το αρχείο σε προσωρινό φάκελο και επιστρέφει (κάλυψη, προσωρινό αρχείο, φάκελο)."""
    wd = tempfile.mkdtemp()
    if a.pdf:
        out = to_pdf(build_html(meta), converters, wd)
        text = pdf_text(out)
    else:
        out = os.path.join(wd, "page.md")
        text = build_md(meta, stamp)
        with open(out, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    return coverage(meta, text), out, wd


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("roots", nargs="*")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--pdf", action="store_true", help="PDF αντί για Markdown")
    ap.add_argument("--md-out", help="μία σελίδα σε αυτό το αρχείο Markdown, χωρίς διαγραφή")
    ap.add_argument("--cases")
    ap.add_argument("--manifest")
    ap.add_argument("--log", default="qualex-se-md-log.tsv")
    a = ap.parse_args()
    stamp = datetime.datetime.now().isoformat(timespec="seconds")
    if a.md_out:
        if len(a.roots) != 1 or a.pdf:
            sys.exit("Με --md-out δίνεται μία σελίδα .htm και όχι --pdf.")
        with open(a.roots[0], encoding="utf-8", errors="replace") as f:
            meta = parse_qualex(f.read())
        if meta is None:
            sys.exit("Δεν είναι σελίδα άρθρου του Qualex.")
        cov, out, wd = convert(meta, a.roots[0], a, None, stamp)
        shutil.copyfile(out, a.md_out)
        shutil.rmtree(wd, ignore_errors=True)
        print("%s %.1f%% -> %s (προτεινόμενο όνομα: %s)" % ("ΟΚ" if cov >= MIN_COVERAGE else "ΧΑΜΗΛΗ ΚΑΛΥΨΗ",
                                                            cov * 100, a.md_out, md_name(meta)))
        sys.exit(0 if cov >= MIN_COVERAGE else 1)
    roots = a.roots or [DEFAULT_ROOT]
    converters = find_converters() if a.pdf else None
    manifest = load_manifest(a.manifest)
    log = open(a.log, "a", encoding="utf-8")
    done = skipped = failed = 0
    for root in roots:
        cases = load_cases(a.cases, root)
        for path in walk(root):
            np_ = os.path.normcase(os.path.normpath(path))
            if any(np_.startswith(c + os.sep) for c in cases):
                continue
            with open(path, encoding="utf-8", errors="replace") as f:
                page = f.read()
            meta = parse_qualex(page)
            if meta is None:
                continue
            stamp = datetime.datetime.now().isoformat(timespec="seconds")
            if to_g(path) in manifest:
                print("ήδη στο manifest, για το web-to-pdf.py:", path)
                log.write("\t".join((stamp, path, "", "", "στο manifest")) + "\n")
                skipped += 1
                continue
            name = pdf_name(meta) if a.pdf else md_name(meta)
            target = unique(os.path.join(os.path.dirname(path), name))
            try:
                cov, out, wd = convert(meta, path, a, converters, stamp)
            except Exception as ex:
                print("αποτυχία:", path, ex)
                log.write("\t".join((stamp, path, target, "", "αποτυχία " + str(ex))) + "\n")
                failed += 1
                continue
            ok = cov >= MIN_COVERAGE
            print("%s %.1f%% %s -> %s" % ("ΟΚ" if ok else "ΧΑΜΗΛΗ ΚΑΛΥΨΗ", cov * 100,
                                          os.path.basename(path), os.path.basename(target)))
            status = "έλεγχος"
            if ok and a.apply:
                shutil.copyfile(out, target)
                files = os.path.splitext(path)[0] + "_files"
                os.remove(path)
                if os.path.isdir(files):
                    shutil.rmtree(files)
                status = "μετατράπηκε"
                done += 1
            elif not ok:
                status = "χαμηλή κάλυψη"
                failed += 1
            shutil.rmtree(wd, ignore_errors=True)
            log.write("\t".join((stamp, path, target, "%.3f" % cov, status)) + "\n")
    log.close()
    print("μετατράπηκαν %d, παραλείφθηκαν %d, αποτυχίες %d%s" % (done, skipped, failed, "" if a.apply else " (χωρίς --apply)"))


if __name__ == "__main__":
    main()
