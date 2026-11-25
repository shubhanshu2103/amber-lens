# Dataset sources

`labels.csv` is the row-level source of truth. Its `source_url` and `image_url`
columns identify the original page and, when available, a direct image URL.
Unlicensed source images are not included in this repository.

The CSV contains 42 rows: 37 source-plate photos (35 `yes`, 2 `partial`) and
5 unreadable blur test rows. The committed image set contains only the 8
Hugging Face photos marked MIT and their 3 MIT blur augmentations. No team
phone-photo rows were identified in the supplied CSV.

Every row has a `license` value. `unknown` means redistribution rights were
not established; those rows are URL/metadata references only, and their source
photos are not included in this repository.

| Source in `labels.csv` | Rows | Split | Use and image rights |
| --- | ---: | --- | --- |
| Hugging Face: `sergiudanstan/motor-nameplate` | 8 | tuning | MIT as recorded in the supplied CSV; photos included under `photos/tuning/`. |
| Hugging Face synthetic blur augmentation | 3 | tuning | MIT as recorded in the supplied CSV; blurred photos included under `photos/tuning/`. |
| Team synthetic blur augmentation | 2 | heldout | Derived from unlicensed HOS BV and iBid photos; not included in the repository. |
| 100Outlets listing | 1 | tuning | No redistribution licence recorded; URL/metadata only. |
| ABF Store listing | 1 | tuning | No redistribution licence recorded; URL/metadata only. |
| Axxa CNC listing | 1 | heldout | No redistribution licence recorded; URL/metadata only. |
| BidSpotter / Aaron Equipment | 1 | tuning | No redistribution licence recorded; URL/metadata only. |
| BidSpotter / New Mill Capital | 1 | tuning | No redistribution licence recorded; URL/metadata only. |
| BidSpotter listing | 1 | heldout | No redistribution licence recorded; URL/metadata only. |
| Bolha listing | 1 | tuning | No redistribution licence recorded; URL/metadata only. |
| Byggahus forum | 1 | heldout | No redistribution licence recorded; URL/metadata only. |
| CAE Online listing | 1 | tuning | No redistribution licence recorded; URL/metadata only. |
| CSDG equipment listing | 2 | tuning, heldout | No redistribution licence recorded; URL/metadata only. |
| Dawid Gwóźdź machinery listing | 1 | heldout | No redistribution licence recorded; URL/metadata only. |
| F-Uchiyama equipment listing | 1 | tuning | No redistribution licence recorded; URL/metadata only. |
| HOS BV listing | 3 | tuning, heldout | No redistribution licence recorded; URL/metadata only. |
| HOS BV product sheet (PDF page 2) | 1 | heldout | No redistribution licence recorded; URL/metadata only. |
| iBid Machinery listing | 1 | heldout | No redistribution licence recorded; URL/metadata only. |
| MT24 equipment listing | 2 | tuning, heldout | No redistribution licence recorded; URL/metadata only. |
| OLX seller listing | 2 | tuning | No redistribution licence recorded; URL/metadata only. |
| Platinum International | 1 | tuning | No redistribution licence recorded; URL/metadata only. |
| Ricardo listing | 1 | heldout | No redistribution licence recorded; URL/metadata only. |
| SB Industrial Supply | 1 | tuning | No redistribution licence recorded; URL/metadata only. |
| Shop.app / Bullseye Industrial Sales | 1 | tuning | No redistribution licence recorded; URL/metadata only. |
| W Power Products listing | 1 | tuning | No redistribution licence recorded; URL/metadata only. |
| Yahoo! Auctions Japan | 1 | heldout | No redistribution licence recorded; URL/metadata only. |
| Yahoo! Shopping Japan | 1 | tuning | No redistribution licence recorded; URL/metadata only. |

Direct image URLs are populated where they were verified. Some rows have only a
page URL; their `image_url` remains blank rather than using an unverified link.
