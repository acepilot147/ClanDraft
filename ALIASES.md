# Player aliases

Reconciliation map for player handles that appear differently across the source sheets in `Sources/`.
The **canonical** name is the form used in `CombinedLists.csv` (usually the handle that already
carries rows). When importing a new source sheet, map its handle to the canonical name so a player's
rows stay under one identity.

This file is hand-curated and holds judgment calls - which handle wins, and which confusable names
are deliberately kept apart. It is not the full list of handles a player has ever used: Roblox's own
rename history for every name in `CombinedLists.csv` is fetched by `check-roblox-names.js` and stored
in `RobloxNames.csv`. Use that file to *find* candidate aliases; record the decision here once you
have confirmed one. A rename history is evidence, not proof of identity - accounts get sold, and two
players can pass the same handle back and forth.

Two recurring gotchas:
- **Capital `I` for lowercase `l`** obfuscation is common in the sheets: e.g. `eviImatty`=evilmatty,
  `eviIsworn`=evilsworn, `dreaddfuI`=dreaddful, `corrporaI`=corporal, `PiIoteer`=Piloteer.
- Several near-identical names are **different people** - see "Do NOT merge" below.

## Canonical  ←  aliases / alternate handles

| Canonical (in CSV) | Aliases seen in sheets | Notes |
|--------------------|------------------------|-------|
| J_tson | Jehtson | |
| Br_ce | eb9_bryce | |
| sybr | sybriwnl | (`syhr` was an interim wrong guess) |
| Ran502 | RanMagic | NOT Rune502, NOT Commando_Lemon |
| JAWS | JawsAtor | |
| kiritobriz | briizc | |
| Commando_Lemon | s2n_lemon, UndefinedLemon | quit ~mid-2019; NOT Commando_Jesus |
| Memeserii | isoundlikemongraal | |
| C_talyst | RemEnhanced | |
| Out_Gunner | Out_gunner | case only |
| realotsxi | RealotsIX, RealotsXI | flagged cheater elsewhere |
| pastlight | p4stlight, Brute | |
| butchrr | NRG_butchrr | |
| Sofapoppin | Sofahpoppin | |
| Warspell | warspell | case only |
| Commando_Jesus | Rune502, CommandoJesus | NOT Ran502 |
| tokyosurfer | surfer, surfaaa | |
| vAbcelon | Vincent, Vincent_4 | |
| ImperfectJayboss | nolimitjb | |
| P_ams | Pamsbeamedu, Pams | |
| s2n_phino | phinozilla | |
| Drreaamzz | InYourDrx4mz | |
| RangerRoysReturn | TealMagician2 | |
| dreaddfuI | dreaddful | |
| no_logic | no_iogic | |
| FeatherRedemption | FeatherRemeption | 2020 row was misspelled |
| lorddicys | lordd90 | Khritus raid screenshot handle |
| shaquillee | shaq966 | Khritus raid screenshot handle |
| evis2026 | uhvisrayshn | Khritus raid screenshot handle |
| khritus | Skuullzz | Khritus playing under an alt in his own raid screenshot |
| c4spian | c_spian | Khritus raid screenshot handle |

## Do NOT merge (distinct players with confusable names)

- `Ran502` (=RanMagic) ≠ `Rune502` (=Commando_Jesus) ≠ `Commando_Lemon` - three different people.
- `xbsightsss` ≠ `XBSIGHTS` - two different players; keep separate.
- `EnterScreenName` is a real player, not a placeholder - keep as-is.
- `xeffns` = `prayalott` - excluded from the SOL Summer 2024 import because prayalott self-submitted their own score (avoid self-bias / double-count).
