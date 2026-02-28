# OSC Query Interface — Quick Reference

## Overview

The OSC Query server exposes TouchDesigner custom parameters as an OSC-addressable JSON API over HTTP and WebSocket. Any OSC Query-compatible client (QLab, Chataigne, Vezér, web browser, etc.) can discover, read, and write parameters with no manual OSC mapping.

---

## Architecture & Data Flow

```
┌──────────────┐  HTTP GET (JSON)   ┌───────────────────┐
│  OSC Query   │ ◄────────────────► │  TD WebServer DAT │
│   Client     │  WebSocket (JSON   │  (port 9000)      │
│ (QLab, etc.) │   or binary OSC)   │                   │
└──────┬───────┘                    └────────┬──────────┘
       │                                     │
       │  SET / VALUE_UPDATE                 │  reads/writes
       │  (bidirectional)                    │  custom pars
       │                                     ▼
       │                            ┌───────────────────┐
       └───────────────────────────►│  TD Containers    │
                                    │  (custom params)  │
                                    └───────────────────┘
```

### Who updates whom?

| Direction | Trigger | Transport | Protocol |
|---|---|---|---|
| **Client → TD** | Client sends `SET` command or binary OSC | WebSocket | JSON `SET` or raw OSC bytes |
| **TD → Client** | Parameter changes inside TD (expression, UI, script) | WebSocket | JSON `VALUE_UPDATE` broadcast |
| **Client → Client** | One client changes a value; server relays to all *other* clients | WebSocket | JSON `VALUE_UPDATE` broadcast |
| **Client discovers API** | Client requests parameter tree | HTTP GET | JSON (OSC Query spec) |

> Bidirectional sync requires the **Bidirectionalcommunication** toggle on the component to be enabled.

---

## HTTP Endpoints

| URL | Returns |
|---|---|
| `GET /` | Full OSC address tree as JSON |
| `GET /<path>` | Sub-tree / single node JSON |
| `GET /?HOST_INFO` | Server metadata (name, port, extensions) |
| `GET /ui` | Built-in web control UI |

---

## OSC Type Tags (JSON field `TYPE`)

These follow the OSC 1.0 spec type-tag characters:

| Type Tag | TD Parameter Style | Value Format |
|---|---|---|
| `f` | Float | single float `[0.5]` |
| `ff` | XY, UV, WH | two floats `[0.5, 1.0]` |
| `fff` | XYZ, UVW | three floats `[0.1, 0.2, 0.3]` |
| `ffff` | XYZW | four floats |
| `i` | Int | single int `[3]` |
| `ii`…`iiii` | Int (multi) | multiple ints |
| `s` | Str, File, Folder, Menu, CHOP/COMP/DAT/SOP/MAT/TOP refs | string `["hello"]` |
| `T` / `F` | Toggle (on/off) | no value payload; tag itself is the value |
| `r` | RGB, RGBA | RGBA packed as 4 bytes or `["#rrggbbaa"]` in JSON |
| `N` | Pulse, Momentary | Nil — no value; triggers on receive |

---

## JSON Node Structure (per parameter)

```json
{
  "DESCRIPTION": "Gain",
  "FULL_PATH": "/myComp/Gain",
  "TYPE": "f",
  "VALUE": [0.75],
  "RANGE": [{ "MIN": 0.0, "MAX": 1.0 }],
  "ACCESS": 3
}
```

| Field | Meaning |
|---|---|
| `DESCRIPTION` | Human-readable parameter name |
| `FULL_PATH` | OSC address used for get/set |
| `TYPE` | OSC type tag string (see table above) |
| `VALUE` | Current value(s) as array |
| `RANGE` | Min/Max per component, or `VALS` list for menus |
| `ACCESS` | `1` = read-only, `3` = read + write |

### ACCESS rules
- **3 (read/write):** parameter is in Constant mode and not marked read-only.
- **1 (read-only):** parameter has an active expression, export, or is flagged read-only.

---

## WebSocket JSON Commands

### Client → Server

| Command | Payload | Effect |
|---|---|---|
| `SET` | `{ "COMMAND":"SET", "ADDRESS":"/comp/Gain", "ARGS":[0.8] }` | Sets the parameter in TD; broadcasts `VALUE_UPDATE` to other clients |
| `LISTEN` | `{ "COMMAND":"LISTEN", "DATA":"/comp/Gain" }` | Subscribe to changes on one address |
| `LISTEN_ALL` | `{ "COMMAND":"LISTEN_ALL" }` | Subscribe to all addresses at once |
| `IGNORE` | `{ "COMMAND":"IGNORE", "DATA":"/comp/Gain" }` | Unsubscribe from one address |
| `PING` | `{ "COMMAND":"PING" }` | Keep-alive; server responds with `PONG` |

### Server → Client

| Command | Payload | Meaning |
|---|---|---|
| `VALUE_UPDATE` | `{ "COMMAND":"VALUE_UPDATE", "ADDRESS":"/comp/Gain", "ARGS":[0.8] }` | A parameter value changed (from TD or another client) |
| `CLIENT_COUNT` | `{ "COMMAND":"CLIENT_COUNT", "CLIENTS": 2 }` | Number of connected WebSocket clients changed |
| `PONG` | `{ "COMMAND":"PONG" }` | Reply to `PING` |

> On connect, clients are **auto-subscribed** to all addresses — no manual `LISTEN` needed.

---

## Binary OSC over WebSocket (legacy)

Clients can also send standard binary OSC messages over WebSocket. The server decodes them identically and broadcasts the change as a JSON `VALUE_UPDATE` to all other clients. This keeps mixed binary/JSON client environments in sync.

---

## Value Encoding Details

### Colors (RGB / RGBA)
| Direction | Format |
|---|---|
| JSON tree (`VALUE`) | Hex string `"#rrggbbaa"` |
| OSC binary (send/receive) | 4-byte RGBA struct (`0–255` per channel) |
| TD internal | Float `0.0–1.0` per channel |

The server auto-converts between these representations.

### Menus
- `VALUE` contains the **label** (display text), not the internal name.
- `RANGE` contains `{ "VALS": ["Label1", "Label2", …] }`.
- Incoming `SET` should send the **label** string; the server resolves it to the internal menu name.

### Toggle
- OSC type tag is `T` (true) or `F` (false) — no separate value payload.
- For bidirectional updates, sent as int: `1` = on, `0` = off.

### Pulse / Momentary
- Type `N` (Nil). No value. Receiving any message at the address triggers the pulse.
- Momentary pulses for 1 frame.

---

## HOST_INFO Response

```json
{
  "NAME": "MyServer",
  "OSC_PORT": 9000,
  "OSC_TRANSPORT": "UDP",
  "EXTENSIONS": {
    "VALUE": true,
    "LISTEN": true,
    "RANGE": true,
    "ACCESS": true,
    "PATH_REMOVED": false,
    "PATH_CHANGED": false,
    "PATH_ADDED": false,
    "PATH_RENAMED": false,
    "CLIPMODE": false,
    "CRITICAL": false,
    "HTML": false,
    "UNIT": false,
    "IGNORE": false,
    "TAGS": false
  }
}
```

`LISTEN` is `true` only when **Bidirectionalcommunication** is enabled on the component.

---

## QLab Integration Notes

- QLab's OSC Query browser connects via HTTP to discover the parameter tree.
- Use the reported `FULL_PATH` values as OSC addresses in QLab cues.
- Float/Int parameters map directly to QLab faders.
- Menu parameters expect the label string as the OSC argument.
- Pulse parameters fire on any message (send with no args or a dummy value).
- Colors are sent as RGBA packed bytes — QLab may need a custom cue for this.
- Ensure the TD server port (default 9000) is reachable from the QLab machine.
