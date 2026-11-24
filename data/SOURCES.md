# Sources

## Nameplate datasets

| Dataset | Link | License | What we used |
| --- | --- | --- | --- |
| motor-nameplate | https://huggingface.co/datasets/sergiudanstan/motor-nameplate (revision c0062cf8) | MIT on the dataset card; original photo provenance unknown | 43 photos kept (41 readable, 2 CANT_MATCH) out of 98 reviewed, see metadata/photo_review.csv |
| motor-nameplate-labels | https://huggingface.co/datasets/sergiudanstan/motor-nameplate-labels | MIT | downloaded for cross-check only; its labels are low quality (e.g. 011/012 both labelled M3558T), not used |
| nameplate_sample2 | https://huggingface.co/datasets/darjja/nameplate_sample2 | MIT | 10 photos kept (8 readable, 2 CANT_MATCH) out of 30; lasers, vehicles and lab gear rejected |
| STRAHLEN | https://zenodo.org/records/21862671 | CC BY 4.0 (tables); photos are not shipped and carry per-photo rights (mostly all-rights-reserved / unstated) | not used for photos. Tables only: 200 nameplates (exchanger, motor, pump, vessel) as as-written, atomic and harmonized attribute tables plus a unit conversion table. Pointer for Koushik (#6): useful as a reference for field names and unit normalisation in records |

## Our own photos

| Photo | Taken by | Where | Date |
| --- | --- | --- | --- |

## Datasheets

| File | Manufacturer | Model | Source URL | Retrieved |
| --- | --- | --- | --- | --- |
| baldor_EM3615T.pdf (local only) | Baldor-Reliance (ABB) | EM3615T | https://www.baldor.com/api/products/EM3615T/infopacket | 2026-11-24 |
| baldor_094914.pdf (local only) | Baldor-Reliance (ABB) | 094914 | https://www.baldor.com/api/products/094914/infopacket | 2026-11-24 |
| baldor_M3538.pdf (local only) | Baldor-Reliance (ABB) | M3538 | https://www.baldor.com/api/products/M3538/infopacket | 2026-11-24 |
| hoyer_ie2_catalogue.pdf (local only) | Hoyer | HMC2-160L-4 | https://shop.eu.oilon.com/wp-content/uploads/sites/3/2021/08/HOYER-IE2-industrial-motors-catalogue.pdf | 2026-11-24 |
| URL only, not downloaded | WEG | 00536ET3E184JM-W22, 00112EP3ER145TC-W22, 00118ET3E143T-W22 | weg.net product pages, see metadata/datasheet_index.csv | 2026-11-24 |
| URL only, not downloaded | ABB | M2BAX180MLA4 (3GBA182410-BDC) | https://www.electricautomationnetwork.com/PDF/PIM/ABB/EN_3GBA182410-BDC.pdf | 2026-11-24 |
| URL only, not downloaded | Lennox | ML14XC1 family | https://lennox-commercial-prod.dotcms.cloud/dA/87c1290aca/file/ehb_ml14xc1_1ph_2306.pdf | 2026-11-24 |

The repo is public, so PDFs stay out of git (`data/datasheets/*.pdf` is gitignored); URLs and extracted fields are committed in metadata/datasheet_index.csv.

## Synthetic, never evaluation data

- `delivery_documents/`: invented tickets, labels, PO and receiving form (see its SYNTHETIC_README.md).
- HF `constructelligence/data-centre-nameplates`: drawn plates, reference for field names only.

## Access and reading notes

All sources accessed 2026-11-24. Every value in labels.csv was read off the photo by claude-code-vision (`verified_by`); `human_checked` is empty until a person spot-checks it. Dataset OCR values were used only as hints and are quoted in `notes` where they differ.
