#!/usr/bin/env bash
# Αφαίρεση των φακέλων «_files» των αποθηκευμένων σελίδων, αφού η μετατροπή σε
# Markdown έχει ελεγχθεί.
#
# Τι είναι οι φάκελοι _files. Όταν ο φυλλομετρητής αποθηκεύει μια σελίδα,
# γράφει το αρχείο .htm και δίπλα του ομώνυμο φάκελο «_files» με δεκάδες css,
# js, γραμματοσειρές και εικόνες. Κανένα από αυτά δεν έχει νομικό περιεχόμενο,
# όλα όμως βαραίνουν το Drive και γεμίζουν το ευρετήριο με άχρηστες εγγραφές.
#
# Γιατί χωριστά από τη μετατροπή. Η μετατροπή είναι αναστρέψιμη, η διαγραφή
# όχι. Αν η μετατροπή αστοχήσει σε κάποια σελίδα και ο φάκελος έχει ήδη φύγει,
# το υλικό χάνεται. Γι' αυτό πρώτα ελέγχεται ο κατάλογος της μετατροπής, και
# μόνο έπειτα εκτελείται αυτό.
#
# Χρήση:
#     bash sakkoulas-katharisma-files.sh              (μόνο κατάλογος)
#     bash sakkoulas-katharisma-files.sh --ektelesi    (αφαίρεση)
#
# Χωρίς --ektelesi δεν αγγίζεται κανένα αρχείο. Αφαιρείται φάκελος _files μόνο
# όταν το ομώνυμο .htm έχει δώσει αρχείο Markdown που υπάρχει και δεν είναι
# κενό. Το ίδιο το .htm δεν διαγράφεται ποτέ από εδώ, μένει ως πρωτότυπο.

set -eu

DRIVE="${CLAUDE_DRIVE:-/g/Το Drive μου/Claude Νομολογία Αρθρογραφία Σχέδια οδηγίες ευρετήρια}"
PROORISMOS="${CLAUDE_SAKKOULAS_OUT:-$DRIVE/Sakkoulas σε Markdown}"
KATALOGOS="${CLAUDE_SAKKOULAS_LOG:-$PROORISMOS/_κατάλογος μετατροπής.tsv}"
EKTELESI="${1:-}"

if [ ! -f "$KATALOGOS" ]; then
  echo "Δεν βρέθηκε ο κατάλογος μετατροπής: $KATALOGOS" >&2
  echo "Εκτελέστε πρώτα το sakkoulas-oles.sh." >&2
  exit 2
fi

python3 - "$KATALOGOS" "$PROORISMOS" "$EKTELESI" <<'PY'
import os
import shutil
import sys

katalogos, proorismos, ektelesi = sys.argv[1], sys.argv[2], sys.argv[3]
ektelo = (ektelesi == "--ektelesi")

etoima = []
akatallila = []

with open(katalogos, encoding="utf-8") as fh:
    next(fh, None)
    for grammi in fh:
        meri = grammi.rstrip("\n").split("\t")
        if len(meri) < 4:
            continue
        pigi, apotelesma, bytes_, katastasi = meri[0], meri[1], meri[2], meri[3]
        md = os.path.join(proorismos, apotelesma)
        riza, _ext = os.path.splitext(pigi)
        fakelos = riza + "_files"
        if not os.path.isdir(fakelos):
            continue
        if os.path.isfile(md) and os.path.getsize(md) > 200:
            etoima.append((fakelos, apotelesma))
        else:
            akatallila.append((fakelos, apotelesma, katastasi))

synolo = 0
for fakelos, _apot in etoima:
    for root, _d, files in os.walk(fakelos):
        for fn in files:
            try:
                synolo += os.path.getsize(os.path.join(root, fn))
            except OSError:
                pass

print("Φάκελοι _files με ελεγμένο Markdown: %d" % len(etoima))
print("Χώρος που ελευθερώνεται: %.1f MB" % (synolo / 1048576.0))
if akatallila:
    print()
    print("ΔΕΝ αφαιρούνται, διότι λείπει ή είναι φτωχό το Markdown: %d" % len(akatallila))
    for fakelos, apot, kat in akatallila[:20]:
        print("  %s  (%s, %s)" % (os.path.basename(fakelos), apot, kat))

if not ektelo:
    print()
    print("Κατάλογος μόνο. Με --ektelesi αφαιρούνται οι φάκελοι.")
    raise SystemExit(0)

svista = 0
for fakelos, _apot in etoima:
    try:
        shutil.rmtree(fakelos)
        svista += 1
    except OSError as exc:
        print("ΣΦΑΛΜΑ %s: %s" % (fakelos, exc), file=sys.stderr)

print()
print("Αφαιρέθηκαν %d φάκελοι _files." % svista)
print("Τα αρχεία .htm δεν πειράχθηκαν.")
PY
