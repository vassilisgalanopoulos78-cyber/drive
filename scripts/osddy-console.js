// Λήψη όλων των αποφάσεων της τρέχουσας σελίδας αποτελεσμάτων του ΟΣΔΔΥ-ΔΔ.
//
// Επικολλάται ολόκληρο στην κονσόλα του Chrome (F12, καρτέλα Console), με τη
// σελίδα των αποτελεσμάτων ανοιχτή. Την πρώτη φορά ο Chrome ζητά να γραφτεί
// «allow pasting» πριν επιτρέψει την επικόλληση.
//
// Τρέχει μέσα στη σελίδα, οπότε χρησιμοποιεί τη δική σου συνεδρία. Δεν
// χρειάζεται cookie, δεν χρειάζεται curl, δεν φεύγει τίποτε από τον υπολογιστή
// σου. Τα αρχεία πέφτουν στον φάκελο «Λήψεις». Ο Chrome ρωτά μία φορά αν
// επιτρέπεις πολλαπλές λήψεις, απαντάς «Να επιτρέπεται».

(async () => {
  // Σε true κατεβαίνει το ανωνυμοποιημένο κείμενο, χωρίς ονόματα διαδίκων.
  const ANONYMO = false;
  // Παύση ανάμεσα στις λήψεις, σε χιλιοστά του δευτερολέπτου.
  const PAFSI = 1500;

  const VASI = 'https://www.adjustice.gr/osddyddweb/';

  const dieythynseis = [...new Set(
    (document.documentElement.outerHTML.match(/documentDownloader\?[^"'<>\s\\)]+/g) || [])
      .map(s => s.replace(/&amp;/g, '&'))
  )];

  if (!dieythynseis.length) {
    console.log('%cΔεν βρέθηκε καμία διεύθυνση λήψης σε αυτή τη σελίδα.',
      'color:#c00;font-size:14px');
    console.log('Η σελίδα μάλλον συνθέτει τους συνδέσμους όταν πατηθεί το κουμπί. '
      + 'Αποθήκευσε τη σελίδα (δεξί κλικ, Αποθήκευση ως) και στείλ\' την, '
      + 'ώστε να προσαρμοστεί το απόσπασμα.');
    return;
  }

  // Ίδιο έγγραφο δύο φορές στη σελίδα, κατεβαίνει μία.
  const anaDocid = new Map();
  for (const q of dieythynseis) {
    const docid = (q.match(/[?&]docid=(\d+)/) || [, q])[1];
    if (!anaDocid.has(docid)) anaDocid.set(docid, q);
  }
  const oura = [...anaDocid.entries()];

  console.log('%cΒρέθηκαν ' + oura.length + ' αποφάσεις. Ξεκινά η λήψη.',
    'color:#080;font-size:14px');

  let ok = 0, apotyxies = 0, synexomenes = 0;

  for (let i = 0; i < oura.length; i++) {
    const [docid, q0] = oura[i];
    let q = ANONYMO ? q0.replace('fanon=false', 'fanon=true') : q0;
    q = q.replace(/([?&]r=)\d+/, (m, p) => p + Math.floor(1000 + Math.random() * 9000));

    const fname = decodeURIComponent((q.match(/fname=([^&]+)/) || [, 'apofasi'])[1])
      .replace(/[\\/:*?"<>|]+/g, '_');
    const onoma = fname + '_d' + docid + '.odt';

    try {
      const apantisi = await fetch(VASI + q, { credentials: 'include' });
      const buf = await apantisi.arrayBuffer();
      const bytes = new Uint8Array(buf.slice(0, 2));

      // Το .odt είναι zip, άρα ξεκινά με PK. Ό,τι άλλο σημαίνει σελίδα
      // σύνδεσης, δηλαδή έληξε η συνεδρία.
      if (!apantisi.ok || bytes[0] !== 0x50 || bytes[1] !== 0x4B) {
        console.warn('ΔΕΝ ΕΙΝΑΙ ΑΠΟΦΑΣΗ: ' + onoma
          + ' (HTTP ' + apantisi.status + ', ' + buf.byteLength + ' bytes)');
        apotyxies++;
        if (++synexomenes >= 3) {
          console.log('%cΔιακοπή. Τρεις συνεχόμενες αποτυχίες, η συνεδρία μάλλον έληξε. '
            + 'Ξανασυνδέσου και ξανατρέξε το, όσα κατέβηκαν δεν ξανακατεβαίνουν.',
            'color:#c00;font-size:14px');
          break;
        }
        continue;
      }
      synexomenes = 0;

      const url = URL.createObjectURL(new Blob([buf],
        { type: 'application/vnd.oasis.opendocument.text' }));
      const a = document.createElement('a');
      a.href = url;
      a.download = onoma;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 15000);

      ok++;
      console.log((i + 1) + '/' + oura.length + '  ' + onoma
        + '  (' + buf.byteLength + ' bytes)');
    } catch (e) {
      console.error('ΣΦΑΛΜΑ ' + onoma, e);
      apotyxies++;
    }
    await new Promise(r => setTimeout(r, PAFSI));
  }

  console.log('%cΤέλος. Κατέβηκαν ' + ok + ', απέτυχαν ' + apotyxies + '.',
    'color:#080;font-size:14px');
  if (ok) {
    console.log('Αν υπάρχουν κι άλλες σελίδες αποτελεσμάτων, πήγαινε στην επόμενη '
      + 'και ξανατρέξε το ίδιο.');
  }
})();
