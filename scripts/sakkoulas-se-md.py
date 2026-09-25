#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Μετατροπή αποθηκευμένων σελίδων Sakkoulas Online σε καθαρά αρχεία Markdown.

Το πρόβλημα. Κάθε σελίδα που αποθηκεύεται από τον φυλλομετρητή δίνει ένα
αρχείο .htm και έναν ομώνυμο φάκελο _files με δεκάδες css, js και εικόνες.
Το ωφέλιμο κείμενο είναι πνιγμένο μέσα σε μενού, διαλόγους και σενάρια, το
όνομα του αρχείου είναι ακατάλληλο για ταυτοποίηση, και οι φάκελοι _files
γεμίζουν το Drive και το ευρετήριο με άχρηστα αρχεία.

Η λύση. Από κάθε σελίδα εξάγεται το δοχείο «reader-content», που περιέχει
το πραγματικό περιεχόμενο, μαζί με τα στοιχεία δημοσίευσης, και γράφεται
αρχείο Markdown με κεφαλίδα ταυτότητας. Έπειτα οι φάκελοι _files μπορούν να
αφαιρεθούν, αλλά αυτό γίνεται χωριστά και ρητά, ποτέ από εδώ.

    python3 sakkoulas-se-md.py <φάκελος> --out <φάκελος προορισμού>
    python3 sakkoulas-se-md.py <φάκελος>            (μόνο δοκιμή)

Χωρίς --out δεν γράφεται τίποτε, εμφανίζεται μόνο τι θα παραγόταν.

Η μετατροπή είναι επαναλήψιμη. Αν το αρχείο προορισμού υπάρχει ήδη με
ταυτόσημο περιεχόμενο, παραλείπεται, ώστε να μπορεί το script να τρέχει
κάθε νύχτα χωρίς να πολλαπλασιάζει τα ίδια κείμενα. Μόνο όταν υπάρχει
ομώνυμο αρχείο με διαφορετικό περιεχόμενο γράφεται χωριστό, με κατάληξη
«(1)», «(2)», και αναφέρεται.
"""

import argparse
import html
import os
import re
import sys
from html.parser import HTMLParser

PROTHEMA = "Sakkoulas-Online.gr - "

# Γραμμές του υποσέλιδου που μπαίνουν στο κείμενο και δεν ανήκουν σε αυτό.
SKOUPIDIA = (
    "Όροι χρήσης", "Πολιτική απορρήτου", "Χρήση Cookies",
    "Εκδόσεις Σάκκουλα", "Σύνδεση", "Εγγραφή", "Αναζήτηση",
    "« Προηγούμενο", "Επόμενο »", "Προηγούμενο »", "« Επόμενο",
)

AGNOOUNTAI = {"script", "style", "button", "select", "option", "svg", "noscript"}


class Anagnostis(HTMLParser):
    """Κρατά το υποδέντρο του div με class «reader-content»."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.mesa = False
        self.vathos = 0
        self.agnoo = 0
        self.kommatia = []
        # στοιχεία δημοσίευσης
        self.pedio = None
        self.etiketes = []
        self.times = []

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        klasi = d.get("class", "")
        if tag in AGNOOUNTAI:
            self.agnoo += 1
            return
        if not self.mesa and tag == "div" and "reader-content" in klasi:
            self.mesa = True
            self.vathos = 1
            return
        if self.mesa and tag == "div":
            self.vathos += 1
        if self.mesa and tag in ("p", "br", "div", "tr", "li", "h1", "h2", "h3"):
            self.kommatia.append("\n")
        if "publication-info-label" in klasi:
            self.pedio = "label"
        elif "publication-info-value" in klasi:
            self.pedio = "value"

    def handle_endtag(self, tag):
        if tag in AGNOOUNTAI:
            self.agnoo = max(0, self.agnoo - 1)
            return
        if self.mesa and tag == "div":
            self.vathos -= 1
            if self.vathos <= 0:
                self.mesa = False
        if self.pedio and tag in ("div", "span", "td"):
            self.pedio = None

    def handle_data(self, data):
        if self.agnoo:
            return
        if self.pedio == "label":
            self.etiketes.append(data.strip())
        elif self.pedio == "value":
            self.times.append(data.strip())
        if self.mesa:
            self.kommatia.append(data)


def katharo(s):
    s = html.unescape(s)
    s = s.replace(" ", " ")
    s = re.sub(r"[ \t]+", " ", s)
    grammes = [g.strip() for g in s.split("\n")]
    out = []
    for g in grammes:
        if not g:
            continue
        if any(sk in g for sk in SKOUPIDIA):
            continue
        if re.fullmatch(r"[\[\]\*\-–—·\.\s]{0,6}", g):
            continue
        # Ο αριθμός σελίδας του περιοδικού κολλάει στην αρχή του τίτλου,
        # λ.χ. «27Ορκωμοσία». Χωρίζεται, ώστε να μένει καθαρός ο τίτλος.
        m = re.match(r"^(\d{1,4})([Α-ΩΆΈΉΊΌΎΏ][^\W\d_].*)$", g)
        if m:
            out.append("[σ. %s]" % m.group(1))
            g = m.group(2)
        out.append(g)
    return out


def onoma_arxeiou(titlos):
    """Όνομα αρχείου από τον τίτλο της σελίδας.

    Η σειρά των αντικαταστάσεων έχει σημασία. Η άνω στιγμή απαγορεύεται στα
    ονόματα των Windows και αφαιρείται, ώστε το «σε: ΔιΔικ 6/2022» να δίνει
    «σε ΔιΔικ 6-2022» και όχι «σε_ ΔιΔικ 6-2022». Ο κανόνας πρέπει να μένει
    σταθερός, διότι από αυτόν κρίνεται αν ένα κείμενο έχει ήδη μετατραπεί.
    """
    s = titlos
    if s.startswith(PROTHEMA):
        s = s[len(PROTHEMA):]
    s = s.replace(".htm", "").strip()
    s = s.replace("/", "-").replace(":", "")
    s = s.replace("σε_", "σε ").replace("σχόλιο_", "σχόλιο ")
    s = re.sub(r'[\\*?"<>|]+', "_", s)
    s = re.sub(r"\s+", " ", s).strip(" .")
    return (s[:150] or "χωρίς τίτλο") + ".md"


def analyse(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        h = fh.read()

    m = re.search(r"<title[^>]*>(.*?)</title>", h, re.S | re.I)
    titlos = html.unescape(re.sub(r"\s+", " ", m.group(1))).strip() if m else ""
    titlos = titlos.replace(" ", " ")

    p = Anagnostis()
    try:
        p.feed(h)
    except Exception as exc:                      # σπασμένο HTML, δεν σταματάμε
        return {"path": path, "sfalma": str(exc)}

    grammes = katharo("".join(p.kommatia))
    dimosiefsi = dict(zip(p.etiketes, p.times))

    return {
        "path": path,
        "titlos": titlos,
        "grammes": grammes,
        "dimosiefsi": dimosiefsi,
        "sfalma": "",
    }


def se_markdown(rec):
    t = rec["titlos"]
    if t.startswith(PROTHEMA):
        t = t[len(PROTHEMA):]
    d = rec["dimosiefsi"]
    kef = ["# " + t, ""]
    stoixeia = []
    for k in ("Περιοδικό", "Αριθ. τεύχους", "Έτος", "Σελίδες"):
        if d.get(k):
            stoixeia.append("%s %s" % (k, d[k]))
    if stoixeia:
        kef.append("Δημοσίευση, " + ", ".join(stoixeia) + ".")
        kef.append("")
    kef.append("Πηγή, αποθηκευμένη σελίδα Sakkoulas Online, αρχείο %s."
               % os.path.basename(rec["path"]))
    kef.append("")
    kef.append("---")
    kef.append("")
    return "\n".join(kef + rec["grammes"]) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("folders", nargs="+", help="φάκελοι με αρχεία .htm")
    ap.add_argument("--out", help="φάκελος προορισμού, αλλιώς μόνο δοκιμή")
    ap.add_argument("--elaxisto", type=int, default=3,
                    help="ελάχιστες γραμμές για να θεωρηθεί έγκυρο (προεπιλογή 3)")
    ap.add_argument("--katalogos",
                    help="αρχείο TSV με την αντιστοίχιση πηγής και αποτελέσματος")
    args = ap.parse_args(argv)

    arxeia = []
    for f in args.folders:
        for root, _d, files in os.walk(f):
            if root.endswith("_files"):
                continue
            for fn in sorted(files):
                if fn.lower().endswith((".htm", ".html")):
                    arxeia.append(os.path.join(root, fn))

    ok = ftoxa = sfalmata = ypirxan = paralliles = 0
    if args.out:
        os.makedirs(args.out, exist_ok=True)
    grammes_katalogou = []

    for path in arxeia:
        rec = analyse(path)
        if rec.get("sfalma"):
            sys.stderr.write("ΣΦΑΛΜΑ %s: %s\n" % (os.path.basename(path), rec["sfalma"]))
            sfalmata += 1
            continue
        if len(rec["grammes"]) < args.elaxisto:
            sys.stderr.write("ΦΤΩΧΟ %s: %d γραμμές, δεν βρέθηκε περιεχόμενο\n"
                             % (os.path.basename(path), len(rec["grammes"])))
            ftoxa += 1
            continue
        onoma = onoma_arxeiou(rec["titlos"] or os.path.basename(path))
        keimeno = se_markdown(rec)
        if args.out:
            stoxos = os.path.join(args.out, onoma)
            katastasi = "νέο"
            # Επαναλήψιμη μετατροπή. Ταυτόσημο αρχείο παραλείπεται, ομώνυμο με
            # διαφορετικό περιεχόμενο γράφεται χωριστά και αναφέρεται.
            while os.path.exists(stoxos):
                try:
                    with open(stoxos, encoding="utf-8") as fh:
                        palio = fh.read()
                except OSError:
                    palio = None
                if palio == keimeno:
                    katastasi = "ήδη υπάρχει"
                    break
                riza, ext = os.path.splitext(onoma)
                n = 1
                while True:
                    ypopsifio = os.path.join(args.out, "%s (%d)%s" % (riza, n, ext))
                    if ypopsifio == stoxos:
                        n += 1
                        continue
                    stoxos = ypopsifio
                    break
                katastasi = "ομώνυμο με άλλο περιεχόμενο"
            if katastasi == "ήδη υπάρχει":
                ypirxan += 1
            else:
                if katastasi == "ομώνυμο με άλλο περιεχόμενο":
                    sys.stderr.write("ΟΜΩΝΥΜΟ %s, γράφτηκε ως %s\n"
                                     % (onoma, os.path.basename(stoxos)))
                    paralliles += 1
                with open(stoxos, "w", encoding="utf-8") as fh:
                    fh.write(keimeno)
                ok += 1
            grammes_katalogou.append("%s\t%s\t%d\t%s"
                                     % (path, os.path.basename(stoxos),
                                        len(keimeno.encode("utf-8")), katastasi))
        else:
            sys.stdout.write("%s  (%d γραμμές)\n" % (onoma, len(rec["grammes"])))
            ok += 1

    if args.katalogos and grammes_katalogou:
        with open(args.katalogos, "w", encoding="utf-8") as fh:
            fh.write("pigi\tapotelesma\tbytes\tkatastasi\n")
            fh.write("\n".join(grammes_katalogou) + "\n")

    sys.stderr.write("\nΑρχεία: %d, μετατράπηκαν: %d, υπήρχαν ήδη: %d, "
                     "ομώνυμα με άλλο περιεχόμενο: %d, χωρίς περιεχόμενο: %d, σφάλματα: %d\n"
                     % (len(arxeia), ok, ypirxan, paralliles, ftoxa, sfalmata))
    if not args.out:
        sys.stderr.write("Δοκιμή μόνο. Με --out <φάκελος> γράφονται τα αρχεία.\n")
    else:
        sys.stderr.write(
            "\nΟι φάκελοι _files δεν χρειάζονται πλέον, αλλά δεν διαγράφονται από εδώ.\n"
            "Ελέγχονται και αφαιρούνται χωριστά, αφού επιβεβαιωθεί το αποτέλεσμα.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
