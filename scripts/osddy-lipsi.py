#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Λήψη αποφάσεων από τον ΟΣΔΔΥ-ΔΔ, με τη συνεδρία του χρήστη.

Η εφαρμογή δεν προσφέρει μαζική λήψη. Κάθε απόφαση κατεβαίνει από

    /osddyddweb/documentDownloader?lobid=...&docid=...&doctype=2&docver=1
                                  &fname=A2941-2026&r=...&clob=true&fanon=false

όπου lobid και docid είναι εσωτερικά αναγνωριστικά του εγγράφου, που δεν
προκύπτουν από τον αριθμό της απόφασης. Πρέπει λοιπόν πρώτα να συλλεχθούν
από τη σελίδα των αποτελεσμάτων, με το απόσπασμα της κονσόλας που
περιγράφει το osddy-katevasma.md, και να δοθούν εδώ ως κατάλογος.

Το cookie της συνεδρίας δεν γράφεται ποτέ μέσα στο script ούτε στη γραμμή
εντολών, αλλά σε χωριστό αρχείο που μένει εκτός αποθετηρίου.

    python3 osddy-lipsi.py --katalogos links.tsv --cookie cookie.txt --out lipseis

Το `--anonymo` ζητεί το ανωνυμοποιημένο κείμενο, αλλάζοντας το fanon σε true.
Το `--dokimi` δείχνει τι θα γινόταν χωρίς να κατεβάσει τίποτε.
"""

import argparse
import os
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36")

VASI = "https://www.adjustice.gr/osddyddweb/"

RE_FNAME = re.compile(r"[?&]fname=([^&]+)")
RE_DOCID = re.compile(r"[?&]docid=(\d+)")
RE_R = re.compile(r"([?&]r=)\d+")


def katharo_onoma(s):
    """Όνομα αρχείου ασφαλές για Windows."""
    s = urllib.parse.unquote(s)
    return re.sub(r'[\\/:*?"<>|]+', "_", s).strip() or "χωρίς όνομα"


def onoma_apo_url(url):
    m = RE_FNAME.search(url)
    if m:
        return katharo_onoma(m.group(1))
    m = RE_DOCID.search(url)
    return "docid-%s" % m.group(1) if m else "χωρίς όνομα"


def diavase_katalogo(path):
    """Κάθε γραμμή, μια διεύθυνση, προαιρετικά με όνομα μετά από στηλοθέτη."""
    entries = []
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            url = parts[0].strip()
            if url.startswith("documentDownloader") or url.startswith("/"):
                url = urllib.parse.urljoin(VASI, url.lstrip("/"))
            if not url.lower().startswith("http"):
                continue
            onoma = katharo_onoma(parts[1]) if len(parts) > 1 and parts[1].strip() \
                else onoma_apo_url(url)
            entries.append((url, onoma))
    # Ίδιο docid δύο φορές στη σελίδα, κατεβαίνει μία.
    seen, moni = set(), []
    for url, onoma in entries:
        m = RE_DOCID.search(url)
        kleidi = m.group(1) if m else url
        if kleidi in seen:
            continue
        seen.add(kleidi)
        moni.append((url, onoma))
    return moni


def diavase_cookie(path):
    with open(path, encoding="utf-8") as fh:
        raw = fh.read().strip()
    # Δέχεται και ολόκληρη τη γραμμή «Cookie: ...» ή το -b '...' του cURL.
    raw = re.sub(r"^\s*(-b|--cookie)\s+", "", raw)
    raw = re.sub(r"^\s*Cookie:\s*", "", raw, flags=re.IGNORECASE)
    return raw.strip().strip("'\"")


def eite_odt(data):
    """Το .odt είναι zip, άρα ξεκινά με PK. Το HTML σημαίνει χαμένη συνεδρία."""
    return data[:2] == b"PK"


def katevase(url, cookie, prosp=3):
    aitima = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "el,en;q=0.9",
        "Referer": VASI,
        "Cookie": cookie,
    })
    teleftaio = None
    for prospatheia in range(prosp):
        try:
            with urllib.request.urlopen(aitima, timeout=60) as apantisi:
                return apantisi.read(), apantisi.headers.get("Content-Type", "")
        except urllib.error.HTTPError as exc:
            teleftaio = exc
            if exc.code in (401, 403):
                raise RuntimeError(
                    "Η συνεδρία δεν γίνεται δεκτή (HTTP %d). Χρειάζεται νέο cookie."
                    % exc.code)
            if exc.code == 404:
                raise RuntimeError("Το έγγραφο δεν βρέθηκε (HTTP 404).")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            teleftaio = exc
        time.sleep(2 ** prospatheia)
    raise RuntimeError("Απέτυχε μετά από %d προσπάθειες: %s" % (prosp, teleftaio))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--katalogos", required=True,
                    help="αρχείο με τις διευθύνσεις, μία ανά γραμμή")
    ap.add_argument("--cookie", required=True,
                    help="αρχείο με το cookie της συνεδρίας, εκτός αποθετηρίου")
    ap.add_argument("--out", required=True, help="φάκελος προορισμού")
    ap.add_argument("--pafsi", type=float, default=2.0,
                    help="δευτερόλεπτα ανάμεσα στις λήψεις (προεπιλογή 2)")
    ap.add_argument("--anonymo", action="store_true",
                    help="ζητά το ανωνυμοποιημένο κείμενο (fanon=true)")
    ap.add_argument("--dokimi", action="store_true",
                    help="δείχνει τι θα γινόταν, χωρίς λήψη")
    args = ap.parse_args(argv)

    try:
        entries = diavase_katalogo(args.katalogos)
    except OSError as exc:
        sys.stderr.write("Δεν διαβάζεται ο κατάλογος: %s\n" % exc)
        return 2
    if not entries:
        sys.stderr.write("Ο κατάλογος είναι κενός. Δες το osddy-katevasma.md.\n")
        return 2

    # Το cookie διαβάζεται μία φορά, ώστε να αποτύχει αμέσως αν λείπει.
    cookie = ""
    if not args.dokimi:
        try:
            cookie = diavase_cookie(args.cookie)
        except OSError as exc:
            sys.stderr.write(
                "Δεν διαβάζεται το αρχείο του cookie: %s\n"
                "Αντίγραψε από τον Chrome το -b του «Copy as cURL» σε αυτό το "
                "αρχείο, χωρίς να το βάλεις σε αποθετήριο.\n" % exc)
            return 2
        if "JSESSIONID" not in cookie:
            sys.stderr.write(
                "Προσοχή, το cookie δεν περιέχει JSESSIONID. Μάλλον λάθος αρχείο.\n")

    os.makedirs(args.out, exist_ok=True)
    apotyxies = os.path.join(args.out, "_apotyxies.txt")

    nea = eidi = apet = 0
    for i, (url, onoma) in enumerate(entries, 1):
        stoxos = os.path.join(args.out, onoma + ".odt")
        if os.path.exists(stoxos) and os.path.getsize(stoxos) > 0:
            eidi += 1
            continue
        if args.anonymo:
            url = url.replace("fanon=false", "fanon=true")
        # Το r είναι αντι-κρυφομνήμη, ανανεώνεται σε κάθε αίτημα.
        url = RE_R.sub(lambda m: m.group(1) + str(random.randint(1000, 9999)), url)

        if args.dokimi:
            sys.stdout.write("%d/%d  %s\n" % (i, len(entries), stoxos))
            continue

        try:
            data, ctype = katevase(url, cookie)
        except RuntimeError as exc:
            msg = "%s\t%s\n" % (onoma, exc)
            with open(apotyxies, "a", encoding="utf-8") as fh:
                fh.write(msg)
            sys.stderr.write("ΑΠΕΤΥΧΕ %s" % msg)
            apet += 1
            if "συνεδρία" in str(exc):
                sys.stderr.write(
                    "\nΔιακοπή. Ανανέωσε το cookie και ξανατρέξε, "
                    "όσα κατέβηκαν δεν ξανακατεβαίνουν.\n")
                break
            time.sleep(args.pafsi)
            continue

        if not eite_odt(data):
            # Σχεδόν πάντα σελίδα σύνδεσης, δηλαδή έληξε η συνεδρία.
            with open(apotyxies, "a", encoding="utf-8") as fh:
                fh.write("%s\tδεν είναι .odt (%s, %d bytes)\n"
                         % (onoma, ctype, len(data)))
            sys.stderr.write(
                "\nΤο %s δεν είναι .odt αλλά %s. Η συνεδρία μάλλον έληξε. Διακοπή, "
                "ώστε να μη γεμίσει ο φάκελος με σελίδες σύνδεσης.\n" % (onoma, ctype))
            apet += 1
            break

        with open(stoxos, "wb") as fh:
            fh.write(data)
        nea += 1
        sys.stdout.write("%d/%d  %s  (%d bytes)\n" % (i, len(entries), onoma, len(data)))
        time.sleep(args.pafsi)

    sys.stderr.write("\nΝέα: %d, υπήρχαν ήδη: %d, απέτυχαν: %d, σύνολο καταλόγου: %d\n"
                     % (nea, eidi, apet, len(entries)))
    if apet:
        sys.stderr.write("Οι αποτυχίες στο %s\n" % apotyxies)
    if not args.dokimi and nea:
        sys.stderr.write(
            "\nΕπόμενο βήμα, η ταυτότητα και η τακτοποίηση:\n"
            "  python3 osddy-taftotita.py %s --tsv katalogos-apofaseon.tsv\n" % args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
