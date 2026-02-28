# Folketingets Afstemninger - Dashboard

En simpel statisk webside der viser afstemningsdata fra Folketinget siden valget 1. november 2022.

## Kom i gang

### 1. Hent data fra Folketingets API

```bash
python3 fetch_data.py
```

Scriptet henter alle afstemninger siden valget, inkl. individuelle stemmer fordelt på partier.
Data gemmes som JSON i `data/` mappen.

**Bemærk:** Scriptet laver mange API-kald (ét per afstemning). Det kan tage 15-30 minutter afhængigt af antal afstemninger. Der er en built-in pause på 0.5 sekunder mellem kald for at respektere API'ets rate limits.

### 2. Åbn dashboardet

Åbn `index.html` i en browser. Du kan bruge en simpel HTTP-server:

```bash
python3 -m http.server 8000
```

Åbn derefter http://localhost:8000 i din browser.

## Funktioner

- Oversigt over alle afstemninger med emne, dato og resultat
- Visuel stemmebar (for/imod/fraværende) for hver afstemning
- Klik på en afstemning for at se fordelingen per parti
- Filtrer på parti, resultat, type og tidsperiode
- Diagram: For-stemmer per parti (%)
- Diagram: Afstemninger over tid (vedtaget/forkastet per måned)

## Datakilde

- **API:** [Folketingets Åbne Data (ODA)](https://oda.ft.dk/api/)
- **Dokumentation:** [ft.dk/dokumenter/aabne-data](https://www.ft.dk/da/dokumenter/aabne-data)

## Filstruktur

```
├── index.html          # Dashboardet (statisk HTML + JS + CSS)
├── fetch_data.py       # Python-script til at hente data fra API'et
├── data/
│   └── afstemninger.json   # Processerede afstemningsdata (JSON)
└── README.md
```

## Teknologi

- Statisk HTML + vanilla JavaScript + CSS
- [Chart.js](https://www.chartjs.org/) til grafer (loaded via CDN)
- Python 3 til datahentning (ingen eksterne afhængigheder)
