# Ambience

**Drop any audio file in this directory and the Blackwall will loop it while
the session is locked.** The filename does not matter — the first
`.mp3`, `.ogg`, `.opus`, `.flac`, `.wav`, or `.m4a` found here is used.

No audio ships with the plugin. Without a file the lock is simply silent;
nothing errors and nothing is missing.

## The recommended track

**"Cyberpunk 2077 — Standing in front of the Blackwall (Ambience)" by
Anendale.** It is what the lock screen was built against: a low, patient hum
that suits a wall you cannot argue with. Roughly 1:42, loops cleanly.

Source your own copy — it is not redistributed here because it is not ours to
license. Search that title, save the audio, and drop the file in this
directory:

```
~/.config/omarchy/plugins/zds.blackwall/sounds/
```

Anything works, though. A rainstorm, a drone, a synth pad, the hum of a server
room. Long and uneventful beats short and melodic — you may be listening to it
for half an hour, and the loop point will be obvious if the track has a shape.

## Using a file somewhere else

To point at something you already have rather than copying it here, set
`soundPath` in `~/.config/omarchy/zds.blackwall.json`:

```json
{
  "version": 1,
  "persistAcrossReboot": true,
  "soundPath": "~/Music/ambience/blackwall.mp3"
}
```

`~` is expanded. An explicit `soundPath` wins over anything in this directory;
leave it as `""` to go back to auto-discovery. Or set it from the shell:

```bash
omarchy-shell blackwall setSound ~/Music/ambience/blackwall.mp3
omarchy-shell blackwall setSound ""     # back to auto-discovery
omarchy-shell blackwall sound           # what is actually loaded right now
```

## Volume

`0.3`, set by `audioVolume` in `../BlackwallLockView.qml`. It is meant to sit
under the room, not fill it.
