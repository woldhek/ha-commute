# Commute for Home Assistant

*[Nederlands hieronder](#nederlands)*

Commute follows a person on the way between home and work and tells Home Assistant:

- whether a commute is under way, and which way (to work or home);
- roughly how far along it is, in percent;
- how they travel right now: walking, cycling, train, public transport (metro, tram and bus together) or car;
- when they will probably arrive;
- **what that guess is based on**: the speed between the last two places, the phone's activity sensor, and the NS
  train and its delay when you use [NS Reisadvies](https://github.com/Meppies/ha-ns-reisadvies).

It is made for the [Tessera](https://github.com/MaxGramser/tessera-plugins) screen plugin
[Commute](https://github.com/woldhek/tessera-plugin-commute), but its entities work on any dashboard and in
automations ("Anton is almost home").

Everything is worked out inside Home Assistant. No place leaves your home.

## How it decides

- **The commute home** starts when the person leaves the work zone, and ends in the home zone.
- **The commute to work** starts at home. Leaving home on a work day is first *maybe a commute*. It becomes one once
  the person is clearly heading for work: 15% of the way closer, and at least 300 m. A trip that never gets closer
  within 45 minutes, or that goes back home, is not a commute.
- Someone who went somewhere else first (school, the gym) and then heads for work on a work day is commuting after all
  once they are a quarter of the way closer.
- A commute ends early when the person stands still outside both zones for 40 minutes, or goes back a quarter of the
  way.
- **The way of travelling** comes from, in this order: the NS train tracker near the person (train); the activity
  sensor (walking, cycling); the speed (under 7 km/h walking, under 25 cycling, under 60 public transport or car,
  above that train or car). A new guess needs two places in a row, unless the activity sensor or the NS tracker says
  so. Standing still keeps the last guess (waiting for a train is still the train trip).
- **The arrival** comes from how long this commute usually takes (the last ten) and how far along it is now.

An iPhone sends its place every few hundred metres or minutes, so the percentage moves in steps, most of all on a
train. The activity sensor makes the guesses much surer.

## Set up

1. In HACS, open the menu, choose **Custom repositories**, add `https://github.com/woldhek/ha-commute` as an
   **Integration**, and download **Commute**. Restart Home Assistant.
2. Make a zone for each person's work, if there is none yet: **Settings → Areas, labels & zones → Zones**.
3. Make sure each person has the **Home Assistant Companion app** on their phone, with location on ("Always").
   On an iPhone, turn on the **Activity** sensor in the app's sensors if you want surer guesses.
4. **Settings → Devices & services → Add integration → Commute.** Fill in, for one person: a name, the person, the
   home zone, the work zone, the work days, and what a vehicle on the road usually is (public transport or a car).
5. Optional: the phone's activity sensor, and from NS Reisadvies the route sensor to work, the route sensor home, and
   a route's train tracker.
6. Repeat step 4 for every person.

## What it makes, per person

| Entity | What |
|---|---|
| `sensor.<name>_commute` | How they travel now (`walking`, `cycling`, `train`, `transit`, `car`, `unknown`), or `none` when no commute is under way. Its attributes hold everything, for the Tessera screen. |
| `binary_sensor.<name>_commuting` | On while a commute is under way. |
| `sensor.<name>_progress` | Percent of the way. |
| `sensor.<name>_arrival` | Expected arrival. |
| `sensor.<name>_direction` | `to_work`, `to_home` or `none`. |
| `sensor.<name>_train_delay` | Minutes of delay of the NS train under way, when you use NS Reisadvies. |

The attributes of `sensor.<name>_commute`: `commute_phase` (`home`, `maybe`, `to_work`, `work`, `to_home`, `away`),
`direction`, `progress`, `eta_at`, `started_at`, `speed` (km/h), `activity`, `ns_distance` (km), `train`, `delay`,
`ns_status`, `place_at`, `basis` (what the guess is based on: `speed`, `activity`, `ns_tracker`, `ns_trip`,
`vehicle_default`, `kept`), `leg_modes`, `leg_from` (percent where each leg began), `leg_times`, `trail` (up to 32
points, each three numbers: metres east and north of home, and the way of travelling as an index of `walking`,
`cycling`, `train`, `transit`, `car`, `unknown`) and `work_offset` (metres east and north of home).

## Example automation

```yaml
triggers:
  - trigger: numeric_state
    entity_id: sensor.anton_progress
    above: 90
conditions:
  - condition: state
    entity_id: sensor.anton_direction
    state: to_home
actions:
  - action: notify.notify
    data:
      message: "Anton is almost home."
```

---

## Nederlands

Commute volgt een persoon op weg tussen thuis en werk en vertelt Home Assistant:

- of er een woon-werkreis bezig is, en welke kant op (naar werk of naar huis);
- ongeveer hoe ver die is, in procenten;
- hoe iemand nu reist: lopen, fietsen, trein, openbaar vervoer (metro, tram en bus samen) of auto;
- wanneer die waarschijnlijk aankomt;
- **waarop die schatting rust**: de snelheid tussen de laatste twee plekken, de activiteitssensor van de telefoon, en
  de NS-trein met zijn vertraging als je [NS Reisadvies](https://github.com/Meppies/ha-ns-reisadvies) gebruikt.

Gemaakt voor de [Tessera](https://github.com/MaxGramser/tessera-plugins)-plugin
[Commute](https://github.com/woldhek/tessera-plugin-commute), maar de entiteiten werken op elk dashboard en in
automations. Alles wordt binnen Home Assistant uitgerekend; geen plek gaat de deur uit.

### Hoe het beslist

- **De reis naar huis** begint bij het verlaten van de werkzone en eindigt in de thuiszone.
- **De reis naar werk** begint thuis. Thuis vertrekken op een werkdag is eerst *misschien een woon-werkreis*. Het wordt
  er een zodra de persoon duidelijk richting werk gaat: 15% van de afstand dichterbij, en minstens 300 m. Een reis die
  in 45 minuten niet dichterbij komt, of terug naar huis gaat, telt niet.
- Wie eerst ergens anders heen ging (school, sportschool) en daarna op een werkdag naar werk gaat, is alsnog onderweg
  zodra die een kwart van de afstand dichterbij is.
- Een reis eindigt eerder als de persoon 40 minuten stilstaat buiten beide zones, of een kwart van de afstand terug
  gaat.
- **Het vervoersmiddel** komt, in deze volgorde, van: de NS-treintracker bij de persoon (trein); de activiteitssensor
  (lopen, fietsen); de snelheid (onder 7 km/u lopen, onder 25 fietsen, onder 60 openbaar vervoer of auto, daarboven
  trein of auto). Een nieuwe gok vraagt twee plekken achter elkaar, tenzij de activiteitssensor of de NS-tracker het
  zegt. Stilstaan houdt de laatste gok vast (wachten op de trein hoort bij de treinreis).
- **De aankomst** komt uit hoe lang deze reis meestal duurt (de laatste tien) en hoe ver die nu is.

Een iPhone stuurt zijn plek om de paar honderd meter of minuten; het percentage loopt dus in stappen, vooral in de
trein. Met de activiteitssensor wordt de gok veel zekerder.

### Instellen

1. Open in HACS het menu, kies **Custom repositories**, voeg `https://github.com/woldhek/ha-commute` toe als
   **Integration** en download **Commute**. Herstart Home Assistant.
2. Maak voor ieders werk een zone als die er nog niet is: **Instellingen → Ruimtes, labels en zones → Zones**.
3. Zorg dat iedereen de **Home Assistant Companion-app** op de telefoon heeft, met locatie op "Altijd". Zet op een
   iPhone de sensor **Activiteit** aan in de sensoren van de app voor een zekerdere gok.
4. **Instellingen → Apparaten en diensten → Integratie toevoegen → Commute.** Vul voor één persoon in: een naam, de
   persoon, de thuiszone, de werkzone, de werkdagen, en wat een voertuig op de weg meestal is (openbaar vervoer of een
   auto).
5. Optioneel: de activiteitssensor van de telefoon, en uit NS Reisadvies de routesensor naar werk, de routesensor naar
   huis en de treintracker van een route.
6. Herhaal stap 4 voor iedere persoon.

De entiteiten en attributen staan in de Engelse tabel hierboven.
