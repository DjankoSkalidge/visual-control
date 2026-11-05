# MIDI files

A MIDI file can trigger [press effects](effects.md#press-effects-one-shot-animations) on its own, like a drummer hitting pads. You choose a channel and an effect for each of its notes, and the file plays on a loop, firing those effects in time.

## Set up a MIDI file

1. Drag a `.mid` or `.midi` file onto the window. You can drop it together with an image or video to open both.
2. A panel opens. **Channel** lists the channels that have notes, with how many hits each has in one loop. It starts on the drum channel if the file has one, or else on the busiest channel.
3. Below it are the notes played most often on that channel, up to 10. Each row shows the drum's name, its note number, and how many times it's played in one loop.
4. Choose an effect for each note you want. Notes left on **None** do nothing. Choosing another channel shows its notes instead, and starts their choices over.
5. Click **Start**. The file plays from the beginning and loops until you remove it, drop another one or close the app.

While the panel is open:

- **The video pauses**, and plays again when the panel closes. A video you'd already paused stays paused.
- **Every effect turns off**, as when [setting up a controller](controllers.md#set-up-a-controller). Effects come back as soon as something triggers them.
- **Controllers are ignored**, and so is any MIDI file that's already playing.

**Cancel** leaves things as they were, so a MIDI file that was already playing carries on.

## What can be assigned

Each note gets one effect, but you can give the same effect to several notes, such as a ripple on both the kick and the snare.

All press effects are available except **pause**, because a file pausing the picture would stop it at moments nobody chose. Toggles such as black and white flip on every hit of their note, so they suit notes that are played rarely, like a crash cymbal.

> Assigning **flash** to a busy part, like hi-hats, makes a fast strobe. Take care if an audience could include photosensitive people.

## How the file is played

- **Only the chosen channel plays.** Notes on every other channel are ignored, so a melody can't trigger anything.
- **Which channel has the drums** depends on where the file came from. General MIDI puts drums on channel 10, so a full song usually has them there. Drum loops made for a sampler, like most downloaded beats, often use channel 1.
- **Notes are named as General MIDI drums** on every channel, because drum loops use the same note numbers wherever they are. A file made for other drum sounds, or a melody, may be labelled oddly, but the note numbers are always right.
- **The loop is as long as the file**, including any silence at the end, so a one-bar pattern stays in time as it repeats.
- **Tempo changes are followed**, wherever they are in the file.
- **It runs on its own clock**, separate from the video. The video's length, pause and playback speed don't affect it, and it plays over still images and with nothing loaded at all.
- **Velocity is ignored.** Every hit plays its effect at full strength.
- **If the app stalls**, for example when the computer sleeps, the notes it missed are skipped instead of all playing at once.

The status bar shows `Playing` and the file name while a file is playing. Only one MIDI file plays at a time.

To stop it, click **Remove MIDI file** in the status bar. Any black and white or removed color that the file left on turns off, but only for effects the file was assigned. Effects from your controller stay as they are.

Assignments aren't saved, so dropping the same file again starts with every note on None.

## Files that can't be used

The status bar names the file and the problem, and nothing changes. A file that's already playing keeps playing.

| Message | Cause |
|---|---|
| `has no notes` | The file has no notes on any channel |
| `can't read it as a MIDI file` | The file is damaged, or isn't a MIDI file |
| `type 2 MIDI files aren't supported` | The file stores separate patterns rather than one piece. These are rare. |
| `is too short to loop` | Every note is at the very start, so the file has no length |
