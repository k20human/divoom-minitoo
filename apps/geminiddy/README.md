# Geminiddy MiniToo Package

Geminiddy turns a Divoom MiniToo into a small status display with three preloaded
custom faces:

- `chilling`
- `working`
- `alerting`

Target platforms are macOS and Linux (working) and Windows (experimental). Runtime switching is a small Bluetooth JSON command,
so it is fast once the three faces have been installed.

## Requirements

- **Python 3.8+**
- **Pillow** (`pip install Pillow`)
- **pyserial** (Windows only: `pip install pyserial`)

## Install

Pair the MiniToo in your OS Bluetooth settings first. Disconnect the official Divoom
phone app while installing or switching states.

### macOS and Linux

Run:

```bash
cd /path/to/apps/geminiddy
./install.sh --email <DIVOOM_LOGIN>
```

The installer:

1. Tries to find the paired MiniToo Bluetooth MAC address automatically.
2. Checks that the OS can open a Bluetooth connection to the MiniToo.
3. Prompts for the Divoom password locally.
4. Logs in only to discover custom face IDs and persist frame styles.
5. Writes `~/.geminiddy/config`.
6. Uploads the bundled GIFs into the three MiniToo custom faces.

### Windows

1. Ensure the device is paired and assigned a COM port (e.g., COM3).
2. Install dependencies: `pip install Pillow pyserial`.
3. Run the installer (requires a bash shell like Git Bash):
   ```bash
   ./install.sh --email <DIVOOM_LOGIN> --mac COM3
   ```

The installer:

1. Tries to find the paired MiniToo Bluetooth MAC address automatically.
2. Checks that macOS can open a Bluetooth connection to the MiniToo.
3. Prompts for the Divoom password locally.
4. Logs in only to discover custom face IDs and persist frame styles.
5. Writes `~/.geminiddy/config`.
6. Uploads the bundled GIFs into the three MiniToo custom faces.

Bluetooth discovery is cached in `~/.geminiddy/detected` before Divoom login. If
you mistype the Divoom password, the retry can reuse the already discovered
Bluetooth MAC and DeviceId.

Bundled GIFs are uploaded with preserved proportions and their original GIF
timing. Square `160x160` artwork is center-cropped into the MiniToo's `160x128`
custom-face canvas instead of being vertically squashed. The MiniToo custom-face
payload supports one frame delay per uploaded face; when a GIF contains mixed
frame durations, the installer duplicates frames to preserve the original timing
as closely as the device format allows. This can make uploads larger and slower.
Frames are encoded as high-quality JPEG (`GEMINIDDY_JPEG_QUALITY=95`) with
4:4:4 color sampling and nearest-neighbor resizing to reduce pixel-art
artifacts. Uploading all three faces usually takes about 1-2 minutes.

If the MiniToo plays the uploaded animation faster than expected, slow the
encoded custom-face timing without changing the GIF:

```bash
GEMINIDDY_SPEED_SCALE=1.5 ./install.sh --email <DIVOOM_LOGIN>
```

You can also pin a specific per-frame delay per state:

```bash
GEMINIDDY_SPEED_WORKING=300 GEMINIDDY_SPEED_CHILLING=450 GEMINIDDY_SPEED_ALERTING=350 ./install.sh --email <DIVOOM_LOGIN>
```

To use a smaller upload:

```bash
GEMINIDDY_JPEG_QUALITY=85 ./install.sh --email <DIVOOM_LOGIN>
```

If auto-detection cannot find the device, pass the Bluetooth MAC explicitly:

```bash
./install.sh --mac <MINITOO_BLUETOOTH_MAC> --email <DIVOOM_LOGIN>
```

Credential handling:

- The password is entered through a hidden terminal prompt.
- The password is never written to disk.
- The Divoom token is kept in memory only.
- The config stores only Bluetooth MAC, DeviceId, ClockIds, and StyleIds.
- The detection cache stores only Bluetooth MAC and DeviceId.

## Switch State

```bash
./set-geminiddy-state.sh working
./set-geminiddy-state.sh chilling
./set-geminiddy-state.sh alerting
```

If the Bluetooth helper is not already running, the script starts it and leaves
it running for faster future switches.

## Put It On PATH

```bash
mkdir -p "$HOME/.local/bin"
ln -sf /path/to/apps/geminiddy/set-geminiddy-state.sh "$HOME/.local/bin/set-geminiddy-state.sh"
export PATH="$HOME/.local/bin:$PATH"
```

Persist the PATH line in `~/.zshrc` if needed:

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
```

Then call from anywhere:

```bash
set-geminiddy-state.sh working
```

## Wire To Gemini CLI

Gemini CLI doesn't have built-in hooks yet. To show status automatically, use the provided `gemini-with-status.sh` wrapper script.

### Use the wrapper

Put `geminiddy-hook.sh` and `gemini-with-status.sh` on your `PATH`:

```bash
ln -sf /path/to/apps/geminiddy/geminiddy-hook.sh "$HOME/.local/bin/geminiddy-hook.sh"
ln -sf /path/to/apps/geminiddy/gemini-with-status.sh "$HOME/.local/bin/gemini-with-status.sh"
```

Then, instead of running `gemini ...`, run:

```bash
gemini-with-status.sh chat
```

The script will:
1. Set the MiniToo to `working`.
2. Launch Gemini CLI and wait for it to exit.
3. Set the MiniToo back to `chilling`.

You can also alias `gemini` in your `.zshrc` or `.bashrc`:

```bash
alias gemini='gemini-with-status.sh'
```

## Multiple Agent Instances

The MiniToo is a single shared device with no awareness that several agent
sessions might be talking to it. With three windows open, a `chilling` from one
session can clobber a `working` from another a millisecond later.

`geminiddy-hook.sh` mitigates this with a small severity model written to
`/tmp/geminiddy-hook-state`:

- Severity ranks `chilling` < `working` < `alerting`. A higher-severity face
  is held against downgrades from any session for a short TTL (`alerting` for
  5s, `working` for 2s by default).
- If a downgrade arrives during the hold, it is deferred — a background retry
  re-evaluates once the hold expires, so the face still clears even if no
  further hook fires from any session.
- A request that matches the face already showing skips the Bluetooth round
  trip entirely, which keeps the device quiet under spammy session events.

Tunables (set in your shell or `settings.json` env block):

- `GEMINIDDY_ALERT_HOLD` — seconds an `alerting` face is held (default `5`).
- `GEMINIDDY_WORK_HOLD` — seconds a `working` face is held (default `2`).
- `GEMINIDDY_HOOK_STATE_FILE` — path to the shared state file
  (default `/tmp/geminiddy-hook-state`).

This wrapper is the only Claude-Code-specific glue; nothing in
`set-geminiddy-state.sh` or the daemon was changed to support it. Direct CLI
use of `set-geminiddy-state.sh` still works exactly as before and bypasses the
gating logic on purpose.

## Errors

If install or switching says Bluetooth cannot connect:

1. Power on and wake the MiniToo.
2. Pair it in macOS System Settings.
3. Disconnect the official phone app from the MiniToo.
4. Confirm the Bluetooth MAC in `~/.geminiddy/config`.

If `Pillow` is missing:

```bash
python3 -m pip install Pillow
```
