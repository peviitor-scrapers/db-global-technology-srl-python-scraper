# DB GLOBAL TECHNOLOGY SRL — scraper pentru peviitor.ro

Scraper Python (doar biblioteca standard) pentru posturile companiei **DB GLOBAL TECHNOLOGY SRL** (CUI **32193007**) de pe site-ul oficial de cariere Deutsche Bank (Workday). Trimite joburile către `https://api.peviitor.ro/v1/scraper/jobs/upload/`.

## Sursă și identitate

- Joburi: API-ul Workday oficial `https://db.wd3.myworkdayjobs.com/wday/cxs/db/DBWebsite/jobs`, filtrat după faceta `Country = Romania`. Se folosește doar endpoint-ul de căutare; **nu se descarcă descrierile joburilor**.
- URL-urile publicate sunt paginile reale ale angajatorului, de forma `https://db.wd3.myworkdayjobs.com/DBWebsite/job/...` (fără parametri de tracking).
- CUI/CIF și denumirea legală: verificate în registrele publice (listafirme.eu, termene.ro): `32193007` / `DB GLOBAL TECHNOLOGY SRL`. Înainte de upload în producție, reconfirmă pe [cuiscan.ro](https://cuiscan.ro) sau [cuifirma.ro](https://cuifirma.ro).
- Pagina de cariere: https://careers.db.com

## GDPR

Se colectează doar: titlu, link canonical, numele companiei, CIF, `location = ["București"]` (când sursa indică București) și data preluării. Nu se colectează descrieri, CV-uri, date personale ale candidaților sau câmpuri inventate.

## Structură

```text
.
├── README.md
├── scraper.py
├── requirements.txt
├── tests/test_scraper.py
├── .github/workflows/scrape.yml
└── data/                       # generat la rulare, gitignored
    ├── state.json
    └── uploaded_urls.txt
```

## Rulare

```bash
python3 scraper.py                 # DRY RUN: citește și afișează, fără upload
python3 scraper.py --upload --limit 5 --create-company   # test: creează firma și trimite 5 joburi
python3 scraper.py --upload        # rularea completă
```

Opțiuni:

| Opțiune | Efect |
|---------|-------|
| `--upload` | Trimite efectiv joburile (implicit: dry run) |
| `--limit N` | Limitează lotul uploaded (util pentru primele 5 joburi) |
| `--create-company` | Face upsert companiei în core (`PUT /v1/firme/company/add/`) |
| `--no-verify` | Sară verificarea după upload |
| `--page-size N`, `--page-delay S` | Reglează paginarea și pauza între pagini |

Starea rulei este salvată în `data/state.json`, iar URL-urile acceptate de API în `data/uploaded_urls.txt` (audit + deduplicare la rulări ulterioare).

## Verificare

```bash
curl "https://api.peviitor.ro/v1/firme/company/?cif=32193007"
curl "https://api.peviitor.ro/v1/search/?q=DB%20GLOBAL%20TECHNOLOGY&rows=50&page=1"
```

Scraperul rulează automat verificarea după upload (caută URL-urile în `response.docs[]`, cu 3 încercări la 5 secunde, pentru că indexarea Solr are un mic lag față de `commitWithin`). Un răspuns `200` de la upload nu este suficient singur.

## Teste

```bash
python3 -m unittest discover -s tests -v
```

## Repository

Repo-ul public este [`peviitor-scrapers/db-global-technology-srl-python-scraper`](https://github.com/peviitor-scrapers/db-global-technology-srl-python-scraper), conform convenției din organizație: `<nume-legal-companie>-<limbaj>-scraper`, câte un repo per companie. Documentația de referință este în [scraper-doc](scraper-doc/README.md) (copia locală e gitignored, nu face parte din repo).
