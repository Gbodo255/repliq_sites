# Vendored animation players

Shipped into a replica only when the source site uses them (see
`app/modules/interaction_analyzer/players.py`). Kept here so replicas work
offline and the build never depends on a CDN at replication time.

| File | Package | Version | License | Source |
|---|---|---|---|---|
| `lottie.min.js` | lottie-web | 5.12.2 | MIT | https://cdnjs.cloudflare.com/ajax/libs/lottie-web/5.12.2/lottie.min.js |
| `rive.js`, `rive.wasm` | @rive-app/canvas | 2.21.6 | MIT | https://cdn.jsdelivr.net/npm/@rive-app/canvas@2.21.6/ |
