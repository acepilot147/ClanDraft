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
| JAWS | JawsAtor | ALT ACCOUNT (id 32476656, past: hottjaws1993, C9_Jaws, GT_Jaws) per a_cemaster; main is id 41671 (past: hottjaws1992) |
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
| rinarcy | blackpunisher64 | ALT ACCOUNT (id 46045, past: CrumpetsRock); main is id 165312572 - per a_cemaster, M8 raid |
| aspirrant | calebdownsrocks7, aspirant | calebdownsrocks7: ALT ACCOUNT (id 8701426, past: zgta); main id 936673945 has NO rename history, so this is a second account, not a rename - per a_cemaster, M8 raid. aspirant: misread of aspirrant (rr read as r) on one 2024-02-02 board; the literal account `aspirant` (id 1002461) is a bystander - per a_cemaster 2026-10-25 |
| PatrickAIt | PatrickAlt | scoreboard font renders capital I as l; Roblox-verified spelling; confirmed by a_cemaster 2026-10-23 (VAK audit boards) |
| rushaIot | rushalot, RushAiot | scoreboard font renders capital I as l; Roblox-verified spelling; confirmed by a_cemaster 2026-10-23 (VAK audit boards) |
| VolitiIe | Volitile, Volitiie | scoreboard font renders capital I as l; Roblox-verified spelling; confirmed by a_cemaster 2026-10-23 (VAK audit boards) |
| darkbIaze | darkblaze | scoreboard font renders capital I as l; Roblox-verified spelling; confirmed by a_cemaster 2026-10-23 (VAK audit boards) |
| PiIoteer | Piloteer | scoreboard font renders capital I as l; Roblox-verified spelling; confirmed by a_cemaster 2026-10-23 (VAK audit boards) |
| BRUTALlSE | BRUTALISE | scoreboard font renders capital I as l; Roblox-verified spelling; confirmed by a_cemaster 2026-10-23 (VAK audit boards) |
| pIatinum_xe | platinum_xe | scoreboard font renders capital I as l; Roblox-verified spelling; confirmed by a_cemaster 2026-10-23 (VAK audit boards) |
| Iostvoicee | lostvoicee | scoreboard font renders capital I as l; Roblox-verified spelling; confirmed by a_cemaster 2026-10-23 (VAK audit boards) |
| VintagAlc | VINTAGAIC | same player per a_cemaster 2026-10-23; sheet spelling does not resolve on Roblox - replace with the verified name once the crawl finds it |
| VaIitron | Valitron, Vaiitron | scoreboard font renders capital I as l; Roblox-verified spelling (id 497136917). The literal account `Valitron` (id 61205504, no rename or clan history) is a different, unrelated account - scoreboard "Valitron" means this capital-I clanner. Confirmed by a_cemaster 2026-10-23 |
| BlGMOP | B1GMOP, bigmop | look-alike accounts: BlGMOP is Roblox id 592923641 (B1GMOP is in clan groups (Legiones Imperialisᅠᅠ (Primarch) | Angry Marinesᅠ (Lord Solar) |); the literal account `bigmop` (id 290504150, created 2017-04-21, no groups) is a bystander - scoreboard/sheet "bigmop" means BlGMOP. Decided 2026-10-24 by roblox_groups.py |
| DEADl1y | Deadlly | look-alike accounts: DEADl1y is Roblox id 1212029326 (DEADl1y has 5 groups); the literal account `Deadlly` (id 47655931, created 2013-08-26, no groups) is a bystander - scoreboard/sheet "Deadlly" means DEADl1y. Decided 2026-10-24 by roblox_groups.py |
| fireschooIbus1 | fireschoolbus1 | look-alike accounts: fireschooIbus1 is Roblox id 2455807053 (fireschooIbus1 is in clan groups (The Frost Battle Imperium (Screening) | [CW] Grand Army ); the literal account `fireschoolbus1` (id 275136708, created 2017-03-30, no groups) is a bystander - scoreboard/sheet "fireschoolbus1" means fireschooIbus1. Decided 2026-10-24 by roblox_groups.py |
| drawabIe | Drawable, marstxrs | look-alike accounts: drawabIe is Roblox id 248694226 (marstxrs is in clan groups (The Legions of the Republic (Unwaved) | The Vaktovian Empire (); the literal account `Drawable` (id 48120254, created 2013-09-05, no groups) is a bystander - scoreboard/sheet "Drawable" means drawabIe. Decided 2026-10-24 by roblox_groups.py |
| yyichris | yylchris | look-alike accounts: yyichris is Roblox id 3312058793 (yyIchris is in clan groups (Nighthawk Reaper Battalion (| L | Novice) | The Nighthawk Impe); the literal account `yylchris` (id 9199129958, created 2025-08-14, no groups) is a bystander - scoreboard/sheet "yylchris" means yyichris. Decided 2026-10-24 by roblox_groups.py |
| Iisalqc | Lisalqc | look-alike accounts: Iisalqc is Roblox id 119839579 (Iisalqc is in clan groups ([VCL] Vaktovian Competitive League (Imperial Engineer) | Imperi); the literal account `Lisalqc` (id 7283577574, created 2024-08-31, no groups) is a bystander - scoreboard/sheet "Lisalqc" means Iisalqc. Decided 2026-10-24 by roblox_groups.py |
| DeimosXVIl | DeimosXVII | look-alike accounts: DeimosXVIl is Roblox id 338309536 (DeimosXVIl is in clan groups (The Clone Army of the Republic TCAR. (E-1 | Cadet) | The Gal); the literal account `DeimosXVII` (id 2410444570, created 2021-03-03, no groups) is a bystander - scoreboard/sheet "DeimosXVII" means DeimosXVIl. Decided 2026-10-24 by roblox_groups.py |
| J1HNY | jihny | look-alike accounts: J1HNY is Roblox id 381201425 (J1HNY is in clan groups (R0KA | 13th Special Missions Brigade (SMU | 특임대) | 25th Paracomma); the literal account `jihny` (id 236673524, created 2017-02-11, no groups) is a bystander - scoreboard/sheet "jihny" means J1HNY. Decided 2026-10-24 by roblox_groups.py |
| D1FFED | DiffeD | look-alike accounts: D1FFED is Roblox id 146358019 (D1FFED is in clan groups (The Vaktovian Empire (Legionary Private First Class) | Universal); the literal account `DiffeD` (id 127024335, created 2016-05-15, no groups) is a bystander - scoreboard/sheet "DiffeD" means D1FFED. Decided 2026-10-24 by roblox_groups.py |
| ConsteIIium | Constellium, SenorMexico | look-alike accounts: ConsteIIium is Roblox id 21488134 (ConsteIIium is in clan groups (Clanning Hall of Fame (Senior Hall of Fame) | Clan Veterans); the literal account `Constellium` (id 309103059, created 2017-05-26, no groups) is a bystander - scoreboard/sheet "Constellium" means ConsteIIium. Decided 2026-10-24 by roblox_groups.py |
| KlYOM1 | artoriaaz, kiyom1 | look-alike accounts: KlYOM1 is Roblox id 216784666 (artoriaaz is in clan groups (Sol Imperialis (Saint) | Solar Militarum (Commissar) | Snow C); the literal account `kiyom1` (id 1076451112, created 2019-05-12, no groups) is a bystander - scoreboard/sheet "kiyom1" means KlYOM1. Decided 2026-10-24 by roblox_groups.py |
| st_eIIar | st_ellar | look-alike accounts: st_eIIar is Roblox id 829956428 (st_eIIar is in clan groups (Orion Imperium ([PVT] Private) | [x]Tracker Special Operations); the literal account `st_ellar` (id 1020379647, created 2019-03-29, no groups) is a bystander - scoreboard/sheet "st_ellar" means st_eIIar. Decided 2026-10-24 by roblox_groups.py |
| duaIy2 | dualy2, pdualy | look-alike accounts: duaIy2 is Roblox id 14067253 (pdualy is in clan groups (Astraeus Concord (Tarvos) | Ex - Vultarians (Retired NCO) | Reig); the literal account `dualy2` (id 1320804876, created 2019-11-16, no groups) is a bystander - scoreboard/sheet "dualy2" means duaIy2. Decided 2026-10-24 by roblox_groups.py |
| NyxaIorian | Nyxalorian, Nyxathen | look-alike accounts: NyxaIorian is Roblox id 1201977368 (Nyxathen is in clan groups (The Spetzware (Cadet) | The Robloxian Army Elites (Tactician) ); the literal account `Nyxalorian` (id 7090185280, created 2024-07-20, no groups) is a bystander - scoreboard/sheet "Nyxalorian" means NyxaIorian. Decided 2026-10-24 by roblox_groups.py |
| STlNTT | stintsu, Stintt | look-alike accounts: STlNTT is Roblox id 3365309097 (stinths is in clan groups ([x]Tracker Special Operations Command (Operator) | The Havoc Un); the literal account `Stintt` (id 60123868, created 2014-04-30, no groups) is a bystander - scoreboard/sheet "Stintt" means STlNTT. Decided 2026-10-24 by roblox_groups.py |
| Desor1ent | Desorient, StrayCoffeeXL | look-alike accounts: Desor1ent is Roblox id 1619214995 (StrayCoffeeXL is in clan groups (Sіth Imperium (Conscript) | Ex - Vultarians (Retired NCO)); the literal account `Desorient` (id 1513590, created 2008-11-18, no groups) is a bystander - scoreboard/sheet "Desorient" means Desor1ent. Decided 2026-10-24 by roblox_groups.py |
| eviIsera | evilsera | look-alike accounts: eviIsera is Roblox id 1053317682 (eviIsera is in clan groups (Orion Imperium ([A1] Ascension 1) | WARCREST (X | RETIRED) | E); the literal account `evilsera` (id 28484197, created 2012-06-12, no groups) is a bystander - scoreboard/sheet "evilsera" means eviIsera. Decided 2026-10-24 by roblox_groups.py |
| SmiIodonus | smilodonus, Smilodonustheking123 | look-alike accounts: SmiIodonus is Roblox id 981929067 (Smilodonustheking123 is in clan groups (Raider Dawn ([RCT] Recruit) | |BA| -British Army- ); the literal account `smilodonus` (id 278085122, created 2017-04-03, no groups) is a bystander - scoreboard/sheet "smilodonus" means SmiIodonus. Decided 2026-10-24 by roblox_groups.py |
| peng_u1 | Peng_ul | look-alike accounts: peng_u1 is Roblox id 1046305751 (peng_u1 is in clan groups (kiwi guard (kiwi trialist) | Ordana Raiding Corporation (Discip); the literal account `Peng_ul` (id 3908883590, created 2022-09-20, no groups) is a bystander - scoreboard/sheet "Peng_ul" means peng_u1. Decided 2026-10-24 by roblox_groups.py |
| Gloryfication | GIoryfication, gIoryfication, Gloryfixation | look-alike accounts: Gloryfication is Roblox id 1123156762 (Gloryfication is in clan groups (The Locust Swarm (Juvies) | Russian Army | [русская армия); the literal account `GIoryfication` (id 5437288075, created 2024-01-10, no groups) is a bystander - scoreboard/sheet "GIoryfication" means Gloryfication. Decided 2026-10-24 by roblox_groups.py |
| nulIhunter | NULLHUNTER, nullhunter, olympiaans | look-alike accounts: nulIhunter is Roblox id 452277285 (olympiaans is in clan groups (Astraeus Concord (Plutos) | Empire of the British Isles (Pri); the literal account `NULLHUNTER` (id 7350479, created 2010-04-02, no groups) is a bystander - scoreboard/sheet "NULLHUNTER" means nulIhunter. Decided 2026-10-24 by roblox_groups.py |
| GhostIy427 | Ghostly427, ghostly427, ghostlywhiff | look-alike accounts: GhostIy427 is Roblox id 373297155 (ghostlywhiff is in clan groups (327th Hawkbat Battalion (Hawkbat Members) | Insurgent Comm); the literal account `ghostly427` (id 424070992, created 2017-10-27, no groups) is a bystander - scoreboard/sheet "ghostly427" means GhostIy427. Decided 2026-10-24 by roblox_groups.py |
| NEWHABIBl | NewHabibi, NEWLIAM1 | look-alike accounts: NEWHABIBl is Roblox id 189501935 (NEWLIAM1 is in clan groups (Norwegian Armed Forces [Forsvaret] (「E-0」Apprentice) | The Rob); the literal account `NewHabibi` (id 166113742, created 2016-09-28, no groups) is a bystander - scoreboard/sheet "NewHabibi" means NEWHABIBl. Decided 2026-10-24 by roblox_groups.py |
| cadetb1ack | CadetBlack | look-alike accounts: cadetb1ack is Roblox id 2814630040 (cadetb1ack is in clan groups (Eye of the Guard (Director of Operations) | Surge Guard (Vet); the literal account `CadetBlack` (id 363938608, created 2017-08-10, no groups) is a bystander - scoreboard/sheet "CadetBlack" means cadetb1ack. Decided 2026-10-24 by roblox_groups.py |
| eviImlke | Evilmlke, omwmike | look-alike accounts: eviImlke is Roblox id 338565649 (omwmike is in clan groups (Senpai Union (Senpai) | 501st Legion . (Triton Company) | |GAR|); the literal account `Evilmlke` (id 987806198, created 2019-03-02, no groups) is a bystander - scoreboard/sheet "Evilmlke" means eviImlke. Decided 2026-10-24 by roblox_groups.py |
| x1Iovex | xiIovex | look-alike accounts: x1Iovex is Roblox id 53239539 (x1Iovex is in clan groups (Vultarian Military Reserve (Awaiting Funds) | Vultarian Dreadtr); the literal account `xiIovex` (id 3288772369, created 2022-02-05, no groups) is a bystander - scoreboard/sheet "xiIovex" means x1Iovex. Decided 2026-10-24 by roblox_groups.py |
| zinkyzoogIe | HVAX, zinkyzoogle | look-alike accounts: zinkyzoogIe is Roblox id 64860534 (YeahImAllTheWayDown is in clan groups (Wayward Outpost Community (Eleskan National Guard))); the literal account `zinkyzoogle` (id 5201952622, created 2023-11-05, no groups) is a bystander - scoreboard/sheet "zinkyzoogle" means zinkyzoogIe. Decided 2026-10-24 by roblox_groups.py |
| 4lu1s | 4luis, o7_luis | look-alike accounts: 4lu1s is Roblox id 328259888 (o7_luis is in clan groups (VEXARIA | MEDICAL CORPS (Member) | Nighthawk Imperial Peacekeep); the literal account `4luis` (id 52522603, created 2013-12-12, no groups) is a bystander - scoreboard/sheet "4luis" means 4lu1s. Decided 2026-10-24 by roblox_groups.py |
| CaIazar | calaxvu, Calazar | look-alike accounts: CaIazar is Roblox id 14089817 (calaxvu is in clan groups (Astraeus Concord (Plutos) | |GAR| Grand Army of the Republic | ); the literal account `Calazar` (id 47136235, created 2013-08-15, no groups) is a bystander - scoreboard/sheet "Calazar" means CaIazar. Decided 2026-10-24 by roblox_groups.py |
| speII2026 | spell2026 | look-alike accounts: speII2026 is Roblox id 103475031 (speII2026 is in clan groups (Fortnite Raiding Group (Elite) | Astora Regime (Knight) | Uni); the literal account `spell2026` (id 1033437466, created 2019-04-08, no groups) is a bystander - scoreboard/sheet "spell2026" means speII2026. Decided 2026-10-24 by roblox_groups.py |
| russeIIrogue | RussellRogue, ZUJXRG | look-alike accounts: russeIIrogue is Roblox id 494190693 (ZUJXRG has 11 groups); the literal account `RussellRogue` (id 4543214099, created 2023-04-19, no groups) is a bystander - scoreboard/sheet "RussellRogue" means russeIIrogue. Decided 2026-10-24 by roblox_groups.py |
| v1turk | viturk | look-alike accounts: v1turk is Roblox id 941053722 (v1turk is in clan groups (Horizon Military Corporation (Member) | NapoIeonic Wars (⚔️ Memb); the literal account `viturk` (id 1804395946, created 2020-08-04, no groups) is a bystander - scoreboard/sheet "viturk" means v1turk. Decided 2026-10-24 by roblox_groups.py |
| ria1z | Rialz | look-alike accounts: ria1z is Roblox id 2521065781 (ria1z is in clan groups (Prime Legion ([M-I] Champion) | Snow Core ({III} Sentinel) | Lone); the literal account `Rialz` (id 17846908, created 2011-07-03, no groups) is a bystander - scoreboard/sheet "Rialz" means ria1z. Decided 2026-10-24 by roblox_groups.py |
| Iucraz | lucraz, Takayuhki | look-alike accounts: Iucraz is Roblox id 104873329 (SpookySocks8 is in clan groups (The Clone Army of the Republic TCAR. (E-1 | Cadet) | Yutan); the literal account `lucraz` (id 116973936, created 2016-03-26, no groups) is a bystander - scoreboard/sheet "lucraz" means Iucraz. Decided 2026-10-24 by roblox_groups.py |
| PROZI1NHO | EtheraIorian, Proziinho | look-alike accounts: PROZI1NHO is Roblox id 3616920825 (EtheraIorian is in clan groups (Orion Imperium ([A1] Ascension 1) | Clanning Hall of Fame ); the literal account `Proziinho` (id 965163004, created 2019-02-11, no groups) is a bystander - scoreboard/sheet "Proziinho" means PROZI1NHO. Decided 2026-10-24 by roblox_groups.py |
| v1zekk | lostv1ze, vizekk | look-alike accounts: v1zekk is Roblox id 1996964027 (lostv1ze is in clan groups (Astraeus Concord (Plutos) | R0KA | 13th Special Missions Briga); the literal account `vizekk` (id 1699087335, created 2020-06-16, no groups) is a bystander - scoreboard/sheet "vizekk" means v1zekk. Decided 2026-10-24 by roblox_groups.py |
| eviIcola | evilcola, Evilcola, RektItCola | look-alike accounts: eviIcola is Roblox id 9186292 (eviIcola is in clan groups (Devils of Royales ([+] Legends) | Federation of Ball Hockey (F); the literal account `Evilcola` (id 6578500, created 2010-02-15, no groups) is a bystander - scoreboard/sheet "Evilcola" means eviIcola. Decided 2026-10-24 by roblox_groups.py |
| beta1nee | BETAAAAAAAH, betainee | look-alike accounts: beta1nee is Roblox id 1140818247 (BETAAAAAAAH is in clan groups (Clone Wars: Unbound (Waved) | The Legions of the Republic (); the literal account `betainee` (id 2468424879, created 2021-03-28, no groups) is a bystander - scoreboard/sheet "betainee" means beta1nee. Decided 2026-10-24 by roblox_groups.py |
| omwhugo | GaiI_Lewis, Gail_Lewis, GAII_LEWIS | look-alike accounts: GaiI_Lewis is Roblox id 128364200 (omwhugo is in clan groups (Horizon Operations Command (Admiral) | The Legions of the Repub); the literal account `Gail_Lewis` (id 5257318194, created 2023-11-23, no groups) is a bystander - scoreboard/sheet "Gail_Lewis" means GaiI_Lewis. Decided 2026-10-24 by roblox_groups.py. Canonical is omwhugo: the CombinedLists name and the account's current username (GaiI_Lewis is one of its past names) - per a_cemaster 2026-10-24 |
| sightIine | sightline | look-alike accounts: sightIine is Roblox id 293248374 (sightIine is in clan groups (The Locust Swarm (Juvies) | [SOCOM] Warfare Sector (Warfare S); the literal account `sightline` (id 36062946, created 2012-12-25, no groups) is a bystander - scoreboard/sheet "sightline" means sightIine. Decided 2026-10-24 by roblox_groups.py |
| D1_mog | di_mog | look-alike accounts: D1_mog is Roblox id 530909186 (D1_mog is in clan groups (Winslow Accord ᅠ (Conscript) | Vultarian Military Reserve (Await); the literal account `di_mog` (id 3014759937, created 2021-10-28, no groups) is a bystander - scoreboard/sheet "di_mog" means D1_mog. Decided 2026-10-24 by roblox_groups.py |
| CATTUCClNO | cattuccino, Dubiov | look-alike accounts: CATTUCClNO is Roblox id 475474719 (Dubiov is in clan groups (Snow Core | Black Berets (Conscript) | Snow Core | Community Dep); the literal account `cattuccino` (id 186029013, created 2016-11-25, no groups) is a bystander - scoreboard/sheet "cattuccino" means CATTUCClNO. Decided 2026-10-24 by roblox_groups.py |
| evoIight | Evolight, Xxjake_zx | look-alike accounts: evoIight is Roblox id 880665181 (Ceryxis is in clan groups (Imperium of Praetoria (》Praetorian Citizen) | CAT | Pride Batta); the literal account `Evolight` (id 15230869, created 2011-03-08, no groups) is a bystander - scoreboard/sheet "Evolight" means evoIight. Decided 2026-10-24 by roblox_groups.py |
| nulIion | King19265, NullioN | look-alike accounts: nulIion is Roblox id 1257924172 (King19265 is in clan groups (Snow Core | Justice Department (Associate) | [CW] Grand Army ); the literal account `NullioN` (id 37296971, created 2013-01-23, no groups) is a bystander - scoreboard/sheet "NullioN" means nulIion. Decided 2026-10-24 by roblox_groups.py |
| Eterna1Reaper | EternalReaper | look-alike accounts: Eterna1Reaper is Roblox id 116851447 (Eterna1Reaper is in clan groups (TME || Mandalorian Supercommandos (Warmaster) | The Manda); the literal account `EternalReaper` (id 28844582, created 2012-06-21, no groups) is a bystander - scoreboard/sheet "EternalReaper" means Eterna1Reaper. Decided 2026-10-24 by roblox_groups.py |
| steaaIs | steaals | look-alike accounts: steaaIs is Roblox id 71806078 (steaaIs is in clan groups (Maersk Guard (Overseers) | |GAR| Grand Army of the Republic | (); the literal account `steaals` (id 742377919, created 2018-08-31, no groups) is a bystander - scoreboard/sheet "steaals" means steaaIs. Decided 2026-10-24 by roblox_groups.py |
| evilnura | nvrra7, eviInura, nvrrato, NURRATO7 | ALT ACCOUNT (id 441618687, now `nvrra7`; past: eviInura, Nv_Nurra, nuraclap, nura7g, nvrrato, NURRATO7, 141_nurra); main is id 1836059707 (past: evilnura, Blemishyne; now Netanyahuuuuuuuuuuuu). Same VAK sides; evilnura's last board 2026-09-07, nvrra7's first 2026-09-08; eviInura also sat on boards 2024-2025 while evilnura was active - per a_cemaster 2026-10-24 |
| Stowvw | stowww | ALT ACCOUNT (id 344049426, no rename history); main is id 276018305 (past: RubenTNT200, xylnul). "stowww or stow related is stowvw" - per a_cemaster 2026-10-24 |
| cahpuh | Cohpuh, cohpuh | misread of cahpuh (a / o): 12 Sol Ordana boards Feb-Aug 2026 interleaved with cahpuh's own, never on the same board, same top-tier numbers. The literal account `Cohpuh` (id 3157430628, no rename history) is a bystander, not the player. cahpuh is id 5260392233 (past: capp_r) - per a_cemaster 2026-10-24 |

## Confirmed same-player merges (via Roblox rename history)

These handles were reconciled into one identity using each account's Roblox rename history in `RobloxNames.csv`.
Every alias below resolves to the same Roblox account as its canonical name, and its `CombinedLists.csv` rows were renamed accordingly.
Where a merge left two rows in the same year, the higher OVR was kept.

| Canonical (in CSV) | Absorbed handle(s) | Note |
|--------------------|--------------------|------|
| J_tson | G2_Jetson | |
| Saltigrade | SpetnazCaptain | |
| unforspace | Unfortunat_ly | |
| luminated | enzyum | |
| evj | Oredias | |
| kreayc | kreayshawn10 | |
| deadlyful | DeadIyXI | |
| sentXI | sentmeister | |
| monkahpoppin | TORMENT_X | |
| Octasion | KanyesFreshStart | |
| RICESREVENGE | HowToEatRice | |
| LimitingFactors | Destroyer18111 | |
| Swaagness | Swaagify | |
| cartiftf | cartihasadurag, 101Carti | |
| Emmetbrickowski832 | Nexstrious | |
| DREAMSKELLYMERC | mentalmonkeydream, DREAMSKELLYKIRK | KIRK is a separate alt account (id 4602813471); same person - shared APFSDS/SKELLYMERC naming themes |
| evolclap | drSonata, evol7g | |
| whouki | Ukiyiue | |
| SCALESREVENGE | ziuosa | |
| vastrano30 | vas_ts | |
| sevillano8 | SevMagnius | |
| SPENCERSREVENGE | saekouh | |
| m_lenia | MoriZakura | |
| load8d | thugshaker_loaded | |
| EatSleepOrdana | imperiummydrek | |
| f_reakmaster | Spartandownload | |
| CrylixBIoom | w3Icometobloxburg | |
| lolxdroflhahah | DoctorKhel | |
| SaiyanOnyx | onyxrealm | |
| Bobonasir | G2_Bobo | |
| vursaceeee | shugharts, stavcks | |
| PHANTOM9THMAN | Hav00k | same Roblox account (id 644527783) |
| ghostlywhiff | omwghostly | same Roblox account (id 373297155) |
| wantedxv | w4nxted | same Roblox account (id 82635853) |
| sparhelpers | s2anu | same Roblox account (id 1235813674) |
| ju_nll | yurk_xe | same Roblox account (id 78706775) |
| Da_mas | SnowAtor | raid handle; confirmed by hand (Da_mas account itself came back notfound in the Roblox lookup) |
| pdualy | dualyy | raid handle; rename history carries DUALYYY, duaIy2, omwdualy |
| qirvv | lightpunisher64 | current name (renamed after the July 2026 fetch) |
| w_plop | johnsummitfan9 | current name; first CombinedLists appearance is the M8 raid |
| evanvictorjames | lidewully, evyjei | lidewully is the current name again (was evyjei in July 2026); both in past names too |
| zeustage | zeustide | current name |
| moooshiimoooshii | eviImooshippuzthe4 | current name - capital-I obfuscation, reads "evil..." on the scoreboard |
| Tenshi | tenshl, YukiYuna_IsAHero, t_enshimaster | one account (id 61000567, current: YukiYuna_IsAHero); the literal name "Tenshi" on Roblox (id 192259) is an UNRELATED account - the RobloxNames.csv "Tenshi" row points at the wrong person |
| Jesxaiah | Jexgraal, GayInfantry, g_jex | serial renamer - one account, now g_jex; history carries jesxaiah, Jexgraal |
| RICESREVENGE | ricexdx3 | current name; same account as the HowToEatRice merge above |
| Craidd | GreetingsWarmaster | current name; history carries SenorCraidd, FaZeCRAIDD, Craidgod, craidxdx3 |
| Flamedxx | notflamedd | current name; history carries fIamedxx (capital-I), opfIamed, SireFlamed, FL4MEED |
| SaraiReaper | YuliReaper | current name (id in RobloxNames; history carries SaraiReaper, sarai_x2v2, khavence) |
| mxrced | mycallended | current name; history carries MERCSRETURN, 222MXRC, mercsanity |
| yxng_wes | eviIwesly | current name (capital-I; scoreboards render "evilwesly"); history carries Yxng_Wes, wesIogic, WarehouseDocksOrdana |
| luaIogic | lualogic | capital-I account (history: vndz, MNSD_Hack); scoreboards render "lualogic" - the literal lowercase account is unrelated (no history). Confirmed by a_cemaster, M14 |
| Isxaiah | lsxaiah, getbackqq | lsxaiah was the M-raid transcription of the same board handle (its 2024-2026 Raid rows renamed to Isxaiah); getbackqq is the account's current name (id 92230565, history carries Isxaiah). Confirmed by a_cemaster 2026-10-23 |

## Do NOT merge (distinct players with confusable names)

- `Ran502` (=RanMagic) ≠ `Rune502` (=Commando_Jesus) ≠ `Commando_Lemon` - three different people.
- `xbsightsss` ≠ `XBSIGHTS` - two different players; keep separate.
- `EnterScreenName` is a real player, not a placeholder - keep as-is.
- `xeffns` = `prayalott` - excluded from the SOL Summer 2024 import because prayalott self-submitted their own score (avoid self-bias / double-count).
- `Deadl1y` ≠ `deadlyful` - distinct accounts (Deadl1y has no rename history; both appeared in the same Ordana raid set on different teams/games).
- `8kr6` ≠ `s9ense` - the `8kr6NoAuraNoob` in s9ense's rename history is a mock-name, not an alt.
- `G2_RCM` vs `G2_RCMI` (in n3g_ative/reswrn's rename history) - unresolved, likely different people; kept separate.
- `EvilWesly` (literal, id in RobloxNames "evilwesly" row) ≠ `eviIwesly` (capital-I, =yxng_wes) - the literal account has no clanning history; scoreboard "evilwesly" means the capital-I clanner.
